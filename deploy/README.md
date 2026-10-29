# Deploying the FaultLine live repair service

This runbook takes a fresh VM to a public `https://<host>/api/live/status` in about 30 minutes, then points the judge page at it. Commands marked **root** run as root on the VM. Commands marked **demo user** run over SSH as the unprivileged `faultline` user. Commands marked **laptop** run in your local checkout.

Facts from external sources carry a link and the date they were checked, 2026-10-29. Prices change; treat them as approximate.

## What runs where

- **Caddy** (system service, root-managed) terminates TLS for one host name, proxies only `/api/live/*` to `127.0.0.1:9600`, and returns 404 for everything else. Config: [`Caddyfile`](Caddyfile).
- **`faultline-live.service`** is a systemd *user* service of the `faultline` account. It runs `scripts/start-live-demo.sh`, a FastAPI app on loopback port 9600. Unit: [`faultline-live.service`](faultline-live.service).
- **Each repair run** starts candidate backends in Bubblewrap namespaces inside transient cgroup v2 scopes (512 MiB, no swap, 64 tasks, one CPU). The scopes are created with `systemd-run --user --scope`. The service fails closed: it stays `available: false` unless the sandbox check, the aggregate-limit enforcement probe, fixture provenance, storage, and the provider probe all pass.
- **The judge page** (GitHub Pages, `main:/docs`) reads the service URL from `<meta name="faultline-live-api">`. [`scripts/configure-live-demo.py`](../scripts/configure-live-demo.py) sets that value.

### What the host needs, and what it does not

| Needed | Why |
| --- | --- |
| Linux with unprivileged user namespaces and a non-setuid `bwrap` | Candidate isolation |
| cgroup v2, with `memory`, `pids`, and `cpu` delegated to the user's systemd manager | Aggregate limits. Upstream systemd's `user@.service` sets `Delegate=pids memory cpu` ([source](https://github.com/systemd/systemd/blob/main/units/user%40.service.in), checked 2026-10-29). |
| A systemd *user* service with lingering, not an SSH login shell | Only a process inside the user manager's own cgroup subtree can be moved into a new scope. An SSH session lives in `session-N.scope`, which the system manager owns. |
| Git with **full** history | The seeded fixture is pinned to a commit in the history, and provenance is verified at startup. Do not use `--depth 1`. |
| `uv` and Python 3.13 | The service and its locked dependencies. `bootstrap.sh` installs both for the user. |
| Outbound HTTPS | Meta API, ACME certificates, GitHub, PyPI |

**Not needed:** Node.js, npm packages, Playwright, Chromium, or the Next.js builds. The live service runs only the backend evaluation path: `IsolatedBackendLauncher` with `backend_preflight` and `backend_session`, plus the 27-check HTTP oracle. This was verified on 2026-10-29. In a fresh clone where only the Python environments were synced, and with no Node on the unit's `PATH`, the service passed its preflight and verified live runs end to end. `make setup` installs far more than the service uses; `bootstrap.sh` runs only its Python half.

## 1. Choose a host

**Recommended: Fedora 44 (x86_64), 2 vCPU, 4 GB RAM, 25 GB or more of disk.**

- **Fedora:** the project is developed and tested on Fedora 44 (systemd 259, SELinux enforcing). User namespaces are enabled, Bubblewrap is not setuid, and the `caddy` package already allows Caddy to proxy to local ports under SELinux. Its install scriptlet runs `setsebool -P httpd_can_network_connect on` (from `caddy-2.10.2-9.fc44`, inspected 2026-10-29).
- **Size:** a candidate scope may use 512 MiB and one CPU. The controller is capped at 1 GiB by the unit. Caddy and the OS need the rest. 2 GB is probably the floor but was not tested; 4 GB leaves headroom. The second vCPU keeps the API responsive while a candidate is using its CPU.
- **Ubuntu 24.04: not recommended.** Its AppArmor policy restricts unprivileged user namespaces for unconfined programs. A default profile allows creating the namespace but denies capabilities inside it, and Bubblewrap fails under that policy. See [Ubuntu 24.04](#ubuntu-2404) if you must use it.

### Provider example (approximate, checked 2026-10-29)

| Provider | Image | Plan | Approximate cost |
| --- | --- | --- | --- |
| DigitalOcean | "Fedora 44 x64" (`fedora-44-x64`) | Basic, 2 vCPU / 4 GiB / 80 GiB | $24/month or $0.03571/hour, public IPv4 included. Two weeks costs about $12. |
| DigitalOcean (smaller) | same | Basic, 1 vCPU / 2 GiB / 50 GiB | $12/month (untested size) |
| Hetzner Cloud | Fedora | shared vCPU, x86, about 2 vCPU / 4 GB | The cloud page lists shared plans "from €5.99/month" (Cost-Optimized, also labeled "currently not available") and "from €6.49/month" (Regular Performance), excluding VAT. A primary IPv4 costs €0.50/month. Check the console for the current type and price. |

Sources: [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets), [DigitalOcean images](https://docs.digitalocean.com/products/droplets/details/images/) (Fedora 43 and 44 x64 listed), [Hetzner Cloud](https://www.hetzner.com/cloud) (Fedora listed; free stateful firewalls), [Hetzner server overview](https://docs.hetzner.com/cloud/servers/overview/) (IPv4 price). All checked 2026-10-29.

## 2. Create the VM and firewall (about 5 minutes)

1. Create the VM with the Fedora 44 x64 image and your SSH key. DigitalOcean's default login is `root` ([docs](https://docs.digitalocean.com/products/droplets/how-to/connect-with-ssh/), checked 2026-10-29).
2. Attach a provider firewall. Inbound: **TCP 22, 80, 443 only**. Keep the default allow-all outbound rules; the service needs outbound HTTPS. DigitalOcean Cloud Firewalls are free and "block all traffic that isn't expressly permitted by a rule" ([docs](https://docs.digitalocean.com/products/networking/firewalls/), checked 2026-10-29). Hetzner's firewalls are also free. UDP 443 can stay closed: the Caddyfile disables HTTP/3.
3. If `systemctl is-active firewalld` reports `active` on the VM, also open the web ports there (**root**): `firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload`.
4. Note the public IPv4 address. The examples below use `203.0.113.10`, a documentation address; substitute your own.

## 3. Prepare the system and the demo user (root, about 5 minutes)

```bash
dnf -y upgrade --refresh            # reboot afterwards if the kernel was updated
dnf install -y bubblewrap git curl jq caddy
useradd --create-home faultline
install -d -m 700 -o faultline -g faultline /home/faultline/.ssh
install -m 600 -o faultline -g faultline ~/.ssh/authorized_keys /home/faultline/.ssh/authorized_keys
restorecon -R /home/faultline/.ssh
loginctl enable-linger faultline
```

`faultline` gets no sudo rights. Lingering keeps its systemd user manager, and the service, running with nobody logged in.

## 4. Install FaultLine (demo user, about 10 minutes)

Log in **directly**: `ssh faultline@203.0.113.10`. Do not use `su` or `sudo -u`; they do not connect to the user's systemd manager.

```bash
git clone https://github.com/FrankieBiz/Faultline.git ~/faultline
bash ~/faultline/deploy/bootstrap.sh
```

[`bootstrap.sh`](bootstrap.sh) is idempotent and never uses sudo; if something needs root, it prints the exact command and stops. It:

1. Checks for `git`, `bwrap`, `curl`, `jq`, and systemd.
2. Proves that `bwrap` can create user, mount, pid, and network namespaces.
3. Checks for cgroup v2, a reachable user manager, the delegated controllers, and lingering.
4. Installs uv 0.13.0 into `~/.local/bin` if missing, and a uv-managed Python 3.13.
5. Clones or fast-forwards the checkout, converting a shallow clone if needed. Local changes are left alone.
6. Syncs both Python projects and verifies the pinned fixture and evaluation corpus.
7. Runs the isolated-runtime preflight as a transient service of your user manager, with the unit's exact hardening lines. This is the same call as `scripts/demo-chaos.sh` step 1. It must print `sandbox profile ready and aggregate limits enforced by the kernel`.
8. Creates `~/.config/faultline/live.env` (mode 0600) from a template and installs `~/.config/systemd/user/faultline-live.service`. It does not start the service.

Set `FAULTLINE_DIR`, `FAULTLINE_BRANCH`, or `FAULTLINE_REPO_URL` to change the defaults (`~/faultline`, `main`, this repository).

## 5. Add the Meta key and start the service (demo user, about 3 minutes)

The key goes only into `~/.config/faultline/live.env`, outside the repository and readable only by `faultline`. To add it without echoing it or saving it in shell history:

```bash
read -rsp 'META_API_KEY: ' key && printf 'META_API_KEY=%s\n' "$key" >> ~/.config/faultline/live.env; unset key; echo
systemctl --user enable --now faultline-live.service
```

Do not create a `.env` file in `~/faultline`. `start-live-demo.sh` sources one if present, and it would override the unit's settings.

Startup syncs dependencies, runs the preflight, and makes **one real Meta generation call**: the provider probe lists models, then asks for a fixed no-patch proposal capped at 512 completion tokens. Allow up to a minute, then:

```bash
systemctl --user status faultline-live.service --no-pager
curl -s http://127.0.0.1:9600/api/live/status | jq '{available, reason, provider, model, classification, limits, preflight: .runtime_limits.enforcement_preflight}'
```

Expected: `available: true`, `provider: "meta"`, `classification: "meta_model"`, `preflight: "passed"`. The unit sets `LIVE_DEMO_REQUIRE_PROVIDER=meta`, so a missing or wrong key never serves the deterministic fallback. Instead, status says `The configured provider is deterministic, not meta.` (seen in a test on 2026-10-29).

Logs: `journalctl --user -u faultline-live.service -f` (as `faultline`). Data and the public ledger live in `~/faultline/data/live-demo/` (`ledger.jsonl`, `runs/<id>.json`); no client addresses are stored.

## 6. Put Caddy in front (root, about 5 minutes)

Pick the public host name:

- **No DNS needed:** `<dashed-ip>.sslip.io`. For `203.0.113.10` that is `203-0-113-10.sslip.io`. sslip.io answers with the IP embedded in the name; dashed, dotted, and prefixed forms all resolve (for example `faultline-5-75-1-2.sslip.io` → `5.75.1.2`, tested 2026-10-29). Documentation-range addresses such as 203.0.113.x return no answer, so test with your real IP. `sslip.io` now redirects to [nip.io](https://nip.io/), which says the two domains are interchangeable and that Let's Encrypt HTTP-01 certificates work. `sslip.io` is not on the Public Suffix List (checked 2026-10-29), so its Let's Encrypt limits are shared with other users. If Let's Encrypt refuses, Caddy falls back to ZeroSSL ([Caddy docs](https://caddyserver.com/docs/automatic-https), checked 2026-10-29).
- **Your own domain:** create an `A` record such as `live.example.com → 203.0.113.10` and use that name.

```bash
HOST=203-0-113-10.sslip.io          # or live.example.com
install -m 0644 /home/faultline/faultline/deploy/Caddyfile /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=FAULTLINE_LIVE_HOST=%s\n' "$HOST" > /etc/systemd/system/caddy.service.d/faultline.conf
systemctl daemon-reload
FAULTLINE_LIVE_HOST="$HOST" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable --now caddy
journalctl -u caddy -n 30 --no-pager         # look for "certificate obtained successfully"
```

The Caddyfile is copied rather than referenced in place because Fedora's `caddy.service` sets `ProtectHome=true`. It replaces the package's default welcome-page config. Without `FAULTLINE_LIVE_HOST`, the file does not validate and Caddy refuses to start (tested with Caddy 2.10.2).

What the Caddyfile does, as tested on 2026-10-29 with Fedora's Caddy 2.10.2 against the real service:

- It serves HTTPS with automatic certificates, and HTTP redirects to HTTPS.
- `/api/live/*` is proxied to `127.0.0.1:9600`. `/`, `/api/other`, and `/api/live/../..` return 404, and an upstream that is down returns 502.
- With no `trusted_proxies`, Caddy ignores a client-supplied `X-Forwarded-For` and sends exactly one hop, the connecting address ([docs](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [options](https://caddyserver.com/docs/caddyfile/options), checked 2026-10-29). The service runs with `LIVE_DEMO_TRUST_PROXY=1` and uses the last hop. In the test, with the per-client limit set to 2, three POSTs with different spoofed `X-Forwarded-For` values counted as one client, and the third got `429 rate_limited`. Keep Caddy the only path to port 9600: it binds 127.0.0.1, and nothing else may proxy to it.
- Request bodies over 4 KB get 413; the only body is `{"defect_id": "..."}`.
- Timeouts: 10 s header, 10 s body, 30 s write, 60 s idle, 3 s upstream dial, and 30 s upstream response header.
- There is no access log, so client addresses are not written to disk. `Server` is stripped, and `nosniff` and `no-referrer` are set.

## 7. Point the judge page at it (laptop, about 5 minutes)

```bash
curl -s https://203-0-113-10.sslip.io/api/live/status | jq '{available, provider, classification}'
uv run --no-project python scripts/configure-live-demo.py https://203-0-113-10.sslip.io --dry-run
uv run --no-project python scripts/configure-live-demo.py https://203-0-113-10.sslip.io
git diff docs/index.html
```

The script fetches the status with `Origin: https://frankiebiz.github.io` and prints availability, provider, model, classification, and today's remaining runs. It refuses to write, and exits 1, if any of these fail:

- the service does not answer valid status JSON;
- the service does not allow the Pages origin (`LIVE_DEMO_ALLOWED_ORIGINS`);
- the page's Content-Security-Policy `connect-src` would block the URL.

It changes only the `content` of `<meta name="faultline-live-api">`. Use `--force` to write anyway, `--clear` to empty the value, and `--allow-local` to test against `http://127.0.0.1:9600`. Commit and push to `main` (Pages builds from `main:/docs`). Then open https://frankiebiz.github.io/Faultline/ from another network, such as a phone on cellular, and run one defect.

## Operating it

| Task | Command (demo user unless noted) |
| --- | --- |
| Status | `systemctl --user status faultline-live.service --no-pager` |
| Follow logs | `journalctl --user -u faultline-live.service -f` |
| Restart (re-runs preflight and the Meta probe) | `systemctl --user restart faultline-live.service` |
| Update code | `bash ~/faultline/deploy/bootstrap.sh && systemctl --user restart faultline-live.service` |
| Change limits | edit `~/.config/faultline/live.env`, then restart |
| Recover after start-limit | `systemctl --user reset-failed faultline-live.service && systemctl --user start faultline-live.service` |
| Caddy logs (root) | `journalctl -u caddy -f` |

The unit uses `Restart=always`. After an infrastructure failure during a run, the service quarantines itself and SIGTERMs itself (`LIVE_DEMO_EXIT_ON_FAILURE=1`), and systemd starts it again 10 s later through the fail-closed preflight. In a test on 2026-10-29, the restart happened and the persisted ledger survived it. More than 5 starts in 10 minutes leaves the unit failed rather than flapping. Each start costs one Meta probe call, so a flapping host costs at most 5 probe calls per 10 minutes before it stops.

The provider probe runs **once per start**. If the service starts unavailable (for example, Meta was briefly unreachable), it reports the reason in status, then restarts itself after 5 minutes to retry the preflight and probe. That is at most one probe call every 5 minutes, which stays under the start limit. A persistent cause, such as a missing key, keeps it retrying until you fix it or stop the unit.

## Limits and what they cost in Meta usage

| Setting (in `live.env`) | Default | Effect |
| --- | --- | --- |
| `LIVE_DEMO_DAILY_CAP` | 150 | Runs per UTC day, including queued ones. This is the spend ceiling. |
| `LIVE_DEMO_PER_CLIENT_PER_HOUR` | 4 | Runs per client address per hour. Judges behind one NAT, such as venue Wi-Fi, share it. |
| `LIVE_DEMO_MAX_WAITING` | 3 | Queue length behind the single running job. Each run is bounded at 240 s. |

A run makes one Meta call, or two when the first proposal is rejected by a gate. Recorded token usage:

- The one Meta attempt on record ([replay 3573b32b](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/)) used 1,569 prompt and 1,685 completion tokens, 3,254 in total.
- For scale only, a non-Meta model over the ten-defect corpus (`docs/evidence/2026-10-28-evaluation-deepseek-v4-pro.json`) averaged 6,343 tokens per run, with a maximum of 12,372.

A planning range for a fully used daily cap is therefore about 0.5 M tokens per day at the recorded Meta rate, and under 2 M per day in the worst observed case. Add one probe call per service start. **The per-token price of `muse-spark-1.3` and your credit balance are not verified here.** Check the Meta developer dashboard before judging and lower `LIVE_DEMO_DAILY_CAP` if needed. A cap of 0 refuses every new run with `daily_cap_reached`, while status and the ledger keep answering.

## Pre-judging checklist (judging runs Nov 4–8, finals Nov 9, per `docs/HACKATHON_BRIEF.md`)

- [ ] `curl -s https://<host>/api/live/status` shows `available: true`, `provider: "meta"`, `classification: "meta_model"`, and `runtime_limits.enforcement_preflight: "passed"`.
- [ ] `systemctl --user is-enabled faultline-live.service` prints `enabled`, and `loginctl show-user faultline -p Linger` prints `Linger=yes`.
- [ ] After a reboot (root: `systemctl reboot`), both Caddy and the service come back without anyone logging in.
- [ ] The certificate is valid: `curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/live/status` prints `200` with no `-k`.
- [ ] `configure-live-demo.py` has been run, the change is pushed to `main`, and the published page shows the live panel.
- [ ] One full live run from the published page on another network reached a verdict, and it appears in `/api/live/ledger`.
- [ ] Meta balance covers `LIVE_DEMO_DAILY_CAP` × days of judging at the usage above.
- [ ] `journalctl --user -u faultline-live.service --since today` shows no repeated restarts or preflight failures.
- [ ] The VM clock is correct (`timedatectl`); the daily cap resets at 00:00 UTC.

## After judging: stop and delete

1. **Laptop, first:** `uv run --no-project python scripts/configure-live-demo.py --clear`, then commit and push. Once the VM is deleted, its IP returns to the provider's pool, and an sslip.io name embeds that IP. The page must stop sending visitors to an address someone else may receive.
2. **Optionally keep the record:** `scp faultline@203.0.113.10:faultline/data/live-demo/ledger.jsonl ./live-ledger.jsonl`.
3. **Demo user:** `systemctl --user disable --now faultline-live.service`. **Root:** `systemctl disable --now caddy`.
4. **Provider:** delete the VM, its firewall, and any reserved or primary IP that is billed separately (Hetzner bills a kept primary IPv4). Delete the DNS record if you used your own domain.
5. Revoke or rotate the Meta key that was on the VM if the dashboard allows it.

The official dates are judging Nov 4–8 and finals Nov 9. The webinar's community-vote result is announced Nov 16; keep the service up through that date only if you want visitors to keep running repairs.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| bootstrap: `No connection to your systemd user manager` | You used `su` or `sudo -u`. SSH in directly as `faultline`. |
| preflight: `FAILED: isolated_profile_unavailable` | bwrap cannot build the sandbox. Check user namespaces, AppArmor on Ubuntu, or a setuid bwrap. |
| preflight: `FAILED: aggregate_limits_unavailable` | Not running inside the user manager, or `memory`/`pids`/`cpu` are not delegated. See `systemctl cat user@.service`. |
| status: `The configured provider is deterministic, not meta.` | `META_API_KEY` is missing from `live.env`. Add it and restart. |
| status: a provider error code, or `Repair provider probe failed.` | Check the key, model access, and credits, then restart. It also retries by itself every 5 minutes. |
| status: `Runtime, provenance, or persistent storage preflight failed.` | Run `bootstrap.sh` again; its output names the failing check. |
| unit `failed` with `start-limit-hit` | It restarted more than 5 times in 10 minutes. Read the journal, fix the cause, then use the recover command above. |
| Caddy will not start: `server block without any key is global configuration` | `FAULTLINE_LIVE_HOST` is not set for Caddy. Check `systemctl cat caddy` for the drop-in. |
| No certificate | TCP 80 and 443 must reach the VM, and the name must resolve to this IP. With sslip.io, check the dashes. |
| Browser console shows a CORS or CSP error | Run `configure-live-demo.py` again; it checks both `LIVE_DEMO_ALLOWED_ORIGINS` and the page's `connect-src`. |

## Unit hardening, briefly

The unit sets `NoNewPrivileges`, `UMask=0077`, `LockPersonality`, `RestrictRealtime`, `RestrictSUIDSGID`, `SystemCallArchitectures=native`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, `MemoryMax=1G`, and `TasksMax=256`. A full holdout run passed with exactly these settings: 2 of 2 backend sessions ran under kernel-verified limits.

The following were tested and break the sandbox: `RestrictNamespaces=`, `ProtectKernelTunables=`, `ProtectKernelLogs=`, `SystemCallFilter=@system-service`, and leaving out `AF_NETLINK`.

Filesystem namespacing (`PrivateTmp=`, `ProtectSystem=`, `PrivateUsers=`) is omitted. In a user manager these make systemd create a user namespace itself, which is one more failure mode on hosts that restrict namespaces. `Delegate=` is not needed: scopes are created by the user manager under `app.slice`, not inside the service's cgroup. Comments in the unit give the details.

## Ubuntu 24.04

Not recommended. Ubuntu 24.04 restricts unprivileged user namespaces for unprivileged, unconfined programs. Its default profile denies capabilities inside the namespace, which Bubblewrap needs. The [24.04 release notes](https://discourse.ubuntu.com/t/ubuntu-24-04-lts-noble-numbat-release-notes/39890) and the [Ubuntu blog](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces) (both checked 2026-10-29) give two options:

- **A per-program AppArmor profile** with `flags=(unconfined)` and a `userns,` rule. Their example is Chrome. The analogous step here is a profile for `/usr/bin/bwrap`, which lifts the restriction for every program that runs bwrap. It is **untested here**.
- **Disable the restriction** system-wide: put `kernel.apparmor_restrict_unprivileged_userns=0` in `/etc/sysctl.d/60-apparmor-namespace.conf` and reboot. The notes say this "does not mitigate against kernel exploits" that abuse user namespaces.

Whichever you choose, `bootstrap.sh`'s preflight is the test. If it does not print `PASSED`, the service will not open.
