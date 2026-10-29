#!/usr/bin/env bash
# Prepare the FaultLine live repair service on a fresh Linux VM.
#
# Run ON THE VM, as the unprivileged demo user, from an SSH login as that user
# (not `sudo -u`/`su`, which give no connection to the user's systemd manager):
#
#   bash deploy/bootstrap.sh          # from a checkout, or
#   curl -fsSL https://raw.githubusercontent.com/FrankieBiz/Faultline/main/deploy/bootstrap.sh | bash
#
# Safe to re-run. It never uses sudo: when something needs root it prints the
# exact command and stops. It checks the sandbox prerequisites, installs uv
# (user-local) if missing, clones or fast-forwards the repository, syncs the
# Python environments, runs the isolated-runtime preflight inside the systemd
# user manager with the unit's hardening, and installs (but does not start)
# the faultline-live user unit. Node.js and Playwright are not needed: the live
# service runs only the backend evaluation path.
#
# Optional environment: FAULTLINE_DIR (default ~/faultline), FAULTLINE_REPO_URL,
# FAULTLINE_BRANCH (default main), FAULTLINE_UV_VERSION (default 0.13.0).
set -euo pipefail

REPO_URL="${FAULTLINE_REPO_URL:-https://github.com/FrankieBiz/Faultline.git}"
BRANCH="${FAULTLINE_BRANCH:-main}"
DIR="${FAULTLINE_DIR:-$HOME/faultline}"
UV_VERSION="${FAULTLINE_UV_VERSION:-0.13.0}"
UNIT=faultline-live.service
UNIT_DIR="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/faultline"
ENV_FILE="$ENV_DIR/live.env"
export PATH="$HOME/.local/bin:$PATH"

if [ -t 1 ]; then
  BOLD=$'\e[1m' RED=$'\e[31m' GREEN=$'\e[32m' AMBER=$'\e[33m' RESET=$'\e[0m'
else
  BOLD='' RED='' GREEN='' AMBER='' RESET=''
fi
step() { printf '\n%s%s%s\n' "$BOLD" "$1" "$RESET"; }
ok() { printf '  %sok%s    %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '  %swarn%s  %s\n' "$AMBER" "$RESET" "$1"; }
fail() {
  printf '  %sfail%s  %s\n' "$RED" "$RESET" "$1" >&2
  shift
  for line in "$@"; do printf '        %s\n' "$line" >&2; done
  exit 1
}

if [ "$(id -u)" -eq 0 ]; then
  fail "Run this as the unprivileged demo user, not root." \
    "See deploy/README.md, step 3, for creating that user."
fi

step "1. System packages"
missing=()
for pair in git:git bwrap:bubblewrap curl:curl jq:jq; do
  command -v "${pair%%:*}" >/dev/null || missing+=("${pair#*:}")
done
for program in systemctl systemd-run loginctl; do
  command -v "$program" >/dev/null || fail "$program not found; this host does not run systemd."
done
if [ "${#missing[@]}" -gt 0 ]; then
  command -v caddy >/dev/null || missing+=(caddy)
  if command -v dnf >/dev/null; then
    fail "Missing: ${missing[*]}. As root (or with sudo), run:" "sudo dnf install -y ${missing[*]}"
  fi
  fail "Missing: ${missing[*]}. Install them with the system package manager, then re-run."
fi
ok "git, bubblewrap, curl, jq"
if command -v caddy >/dev/null; then
  ok "caddy $(caddy version 2>/dev/null | cut -d' ' -f1)"
else
  warn "caddy is not installed yet (needed for HTTPS, step 6): sudo dnf install -y caddy"
fi

step "2. Kernel and sandbox prerequisites"
BWRAP="$(command -v bwrap)"
if [ -u "$BWRAP" ]; then
  fail "$BWRAP is setuid. FaultLine needs unprivileged user namespaces with a non-setuid bwrap."
fi
userns_max="$(cat /proc/sys/user/max_user_namespaces 2>/dev/null || echo 0)"
[ "$userns_max" -gt 0 ] || fail "user.max_user_namespaces is 0; unprivileged user namespaces are disabled."
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = 1 ]; then
  warn "AppArmor restricts unprivileged user namespaces (Ubuntu 23.10+). The preflight below"
  warn "will likely fail; see 'Ubuntu 24.04' in deploy/README.md. Fedora is recommended."
fi
if "$BWRAP" --unshare-all --unshare-user --die-with-parent --ro-bind / / --proc /proc --dev /dev true 2>/dev/null; then
  ok "bwrap can create user, mount, pid, and network namespaces"
else
  fail "bwrap cannot create namespaces as this user. Error:" \
    "$("$BWRAP" --unshare-all --unshare-user --ro-bind / / --proc /proc --dev /dev true 2>&1 | head -1)"
fi
[ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || fail "/sys/fs/cgroup is not cgroup v2 (unified hierarchy)."
ok "cgroup v2"

step "3. systemd user manager"
if [ -z "${XDG_RUNTIME_DIR:-}" ] || ! systemctl --user show --property=Version >/dev/null 2>&1; then
  fail "No connection to your systemd user manager." \
    "Log in over SSH directly as $(id -un); sudo -u, su, and cron do not start a user session."
fi
ok "user manager reachable ($(systemctl --user show --property=Version --value))"
manager_cgroup="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service"
controllers="$(cat "$manager_cgroup/cgroup.controllers" 2>/dev/null || true)"
for controller in memory pids cpu; do
  [[ " $controllers " == *" $controller "* ]] ||
    fail "cgroup controller '$controller' is not delegated to your user manager ($manager_cgroup)." \
      "Upstream systemd delegates 'pids memory cpu' to user@.service; check for local overrides:" \
      "systemctl cat user@.service"
done
ok "memory, pids, and cpu controllers delegated to the user manager"
if [ "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null)" != yes ]; then
  if loginctl enable-linger "$(id -un)" 2>/dev/null; then
    ok "lingering enabled (the service keeps running after you log out)"
  else
    fail "Could not enable lingering. As root, run:" "sudo loginctl enable-linger $(id -un)"
  fi
else
  ok "lingering enabled"
fi

step "4. uv and Python 3.13"
if ! command -v uv >/dev/null; then
  echo "  installing uv $UV_VERSION into ~/.local/bin (official installer, no shell profile changes)"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh >/dev/null
fi
ok "$(uv --version)"
uv python install --quiet 3.13
ok "Python 3.13 (uv-managed)"

step "5. Repository"
if [ ! -e "$DIR" ]; then
  # A full clone: the seeded fixture is pinned to a commit in this history.
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$DIR"
  ok "cloned $REPO_URL ($BRANCH) into $DIR"
else
  git -C "$DIR" rev-parse --git-dir >/dev/null 2>&1 || fail "$DIR exists but is not a Git checkout."
  if [ "$(git -C "$DIR" rev-parse --is-shallow-repository)" = true ]; then
    git -C "$DIR" fetch --quiet --unshallow origin
    ok "converted a shallow clone to a full clone"
  fi
  if [ -n "$(git -C "$DIR" status --porcelain --untracked-files=no)" ]; then
    warn "$DIR has local changes; not updating it"
  else
    git -C "$DIR" fetch --quiet origin "$BRANCH"
    git -C "$DIR" checkout --quiet "$BRANCH"
    git -C "$DIR" merge --quiet --ff-only "origin/$BRANCH" ||
      fail "Could not fast-forward $DIR to origin/$BRANCH; resolve it by hand."
    ok "$DIR is at origin/$BRANCH"
  fi
fi
ok "commit $(git -C "$DIR" rev-parse --short HEAD)"

step "6. Python environments and pinned fixtures"
# The Python half of scripts/setup.sh; npm packages and Chromium are not needed.
for project in apps/buggyshop-backend services/repair-orchestrator; do
  uv sync --quiet --project "$DIR/$project" --python 3.13 --locked
done
ok "uv sync (backend fixture and repair orchestrator)"
(cd "$DIR" && uv run --quiet --project apps/buggyshop-backend --python 3.13 --locked \
  python -m fixtures.provenance >/dev/null && uv run --quiet --project apps/buggyshop-backend \
  --python 3.13 --locked python -m fixtures.evaluation.corpus >/dev/null) ||
  fail "Fixture provenance check failed; the clone may be incomplete (see output above)."
ok "pinned seed commit and evaluation corpus verified"

step "7. Isolated runtime preflight (inside the user manager, with the unit's hardening)"
UNIT_SOURCE="$DIR/deploy/$UNIT"
[ -f "$UNIT_SOURCE" ] || fail "$UNIT_SOURCE is missing; is $BRANCH up to date?"
properties=()
while IFS= read -r line; do
  properties+=(--property "$line")
done < <(sed -n '/^# --- hardening/,/^# --- end hardening/p' "$UNIT_SOURCE" | grep -E '^[A-Za-z]+=')
[ "${#properties[@]}" -gt 0 ] || fail "No hardening block found in $UNIT_SOURCE."
# The same call as scripts/demo-chaos.sh step 1, run as a transient service of
# the user manager (like the real unit) rather than from this SSH session.
PREFLIGHT="$(
  cat <<'PY'
import asyncio
import sys

from app.isolated_runtime import IsolatedRuntime
from app.runtime import RuntimeUnavailable

runtime = IsolatedRuntime()
try:
    asyncio.run(runtime.backend_preflight())
except RuntimeUnavailable as exc:
    print(f"FAILED: {exc}")
    sys.exit(1)
status = runtime.resource_limits_status
if status["enforcement_preflight"] != "passed":
    print(f"FAILED: aggregate limits not enforced ({status['reason']})")
    sys.exit(1)
probe = status["probe"] or {}
print(
    "PASSED: sandbox profile ready and aggregate limits enforced by the kernel "
    f"(memory hog exit {probe.get('hog_exit_code')}, "
    f"oom_kill events {probe.get('oom_kill_events')}, "
    f"threads started {probe.get('threads_started')} of 64 under TasksMax=16)"
)
PY
)"
if result="$(systemd-run --user --wait --pipe --quiet --collect \
  --property=WorkingDirectory="$DIR/services/repair-orchestrator" \
  --property=Environment="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin" \
  --property=Environment="PYTHONPATH=$DIR" \
  --property=UnsetEnvironment="META_API_KEY MODEL_API_KEY" \
  "${properties[@]}" \
  -- "$(command -v uv)" run --quiet --python 3.13 --locked python -c "$PREFLIGHT" </dev/null 2>&1)"; then
  ok "${result##*PASSED: }"
else
  fail "Preflight did not pass. The live service fails closed until it does." "$result"
fi

step "8. Settings file and user unit"
install -d -m 700 "$ENV_DIR"
if [ ! -e "$ENV_FILE" ]; then
  (
    umask 077
    cat >"$ENV_FILE" <<'EOF'
# FaultLine live service settings, read by systemd (EnvironmentFile=).
# KEY=value per line; no quotes, no `export`. Keep this file mode 0600 and
# never copy it into the repository.
#
# Required. The unit sets LIVE_DEMO_REQUIRE_PROVIDER=meta, so without a
# working Meta key the service stays closed (status available=false).
#META_API_KEY=
#META_MODEL_NAME=muse-spark-1.3
#
# Abuse and spend limits (defaults shown). Each run makes one or two Meta calls.
#LIVE_DEMO_PER_CLIENT_PER_HOUR=4
#LIVE_DEMO_DAILY_CAP=150
#LIVE_DEMO_MAX_WAITING=3
#
# Production settings live in the unit (LIVE_DEMO_PORT=9600,
# LIVE_DEMO_TRUST_PROXY=1, LIVE_DEMO_ALLOWED_ORIGINS=https://frankiebiz.github.io,
# LIVE_DEMO_REQUIRE_PROVIDER=meta, LIVE_DEMO_EXIT_ON_FAILURE=1). A line here
# overrides the unit; do not override them unless you mean to.
EOF
  )
  ok "created $ENV_FILE (mode 0600) from a template"
else
  ok "$ENV_FILE exists; left unchanged"
fi
if [ "$(stat -c %a "$ENV_FILE")" != 600 ]; then
  chmod 600 "$ENV_FILE"
  ok "tightened $ENV_FILE to mode 0600"
fi
if grep -Eq '^[[:space:]]*META_API_KEY=[^[:space:]]+' "$ENV_FILE"; then
  ok "META_API_KEY is set in $ENV_FILE (value not shown)"
else
  warn "META_API_KEY is not set in $ENV_FILE; the service will stay closed until it is"
fi
for name in LIVE_DEMO_PORT LIVE_DEMO_TRUST_PROXY LIVE_DEMO_ALLOWED_ORIGINS \
  LIVE_DEMO_REQUIRE_PROVIDER LIVE_DEMO_EXIT_ON_FAILURE; do
  if grep -Eq "^[[:space:]]*$name=" "$ENV_FILE"; then
    warn "$ENV_FILE overrides the unit's production $name"
  fi
done
# scripts/start-live-demo.sh sources a repository .env, which would override
# everything above. Only its presence is checked; it is never read here.
if [ -e "$DIR/.env" ]; then
  warn "$DIR/.env exists and overrides the unit's settings; move it out of the checkout"
fi

install -d -m 700 "$UNIT_DIR"
case "$DIR" in
  "$HOME/faultline") target="%h/faultline" ;;
  "$HOME"/*) target="%h/${DIR#"$HOME"/}" ;;
  *) target="$DIR" ;;
esac
staged="$(mktemp "$UNIT_DIR/.$UNIT.XXXXXX")"
sed "s#%h/faultline#$target#g" "$UNIT_SOURCE" >"$staged"
chmod 644 "$staged"
if cmp -s "$staged" "$UNIT_DIR/$UNIT"; then
  rm -f "$staged"
  ok "$UNIT_DIR/$UNIT is current"
else
  mv "$staged" "$UNIT_DIR/$UNIT"
  ok "installed $UNIT_DIR/$UNIT"
fi
systemctl --user daemon-reload
if [ ! -f "$DIR/scripts/start-live-demo.sh" ]; then
  warn "scripts/start-live-demo.sh is not in this checkout yet; the unit cannot start until it is"
fi

step "Next steps"
if systemctl --user is-active --quiet "$UNIT"; then
  cat <<EOF
  The service is running. Apply the updated code and settings with:
    systemctl --user restart $UNIT
EOF
else
  cat <<EOF
  1. Put the Meta key in the settings file (the value is never printed):
       \${EDITOR:-vi} $ENV_FILE        # set META_API_KEY=...
  2. Start the service now and at every boot:
       systemctl --user enable --now $UNIT
EOF
fi
cat <<EOF
  3. Check it on the VM:
       systemctl --user status $UNIT --no-pager
       journalctl --user -u $UNIT -n 50 --no-pager
       curl -s http://127.0.0.1:9600/api/live/status | jq '{available, reason, provider, classification}'
  4. As root, put Caddy in front (deploy/README.md, step 6):
       sudo install -m 0644 $DIR/deploy/Caddyfile /etc/caddy/Caddyfile
       sudo systemctl edit caddy     # [Service] Environment=FAULTLINE_LIVE_HOST=<host>
       sudo systemctl enable --now caddy
EOF
