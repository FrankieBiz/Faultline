# FaultLine scripts

- `setup.sh` installs locked Python/Node dependencies and Chromium; also available as `make setup`.
- `start-demo.sh` builds the web applications and trusted runner, then supervises the four loopback services. It refuses occupied ports and retains history. Ctrl+C terminates only this session's process groups.
- `rehearse-demo.sh` submits through the Inspector's server-side proxy and checks actual baseline, candidate, and cleanup results. It identifies deterministic mode explicitly, fails on unsuccessful terminal outcomes, and cancels if its overall deadline expires.
- `reset.sh` asks the running controller to reconcile its owned resources. Active jobs return an error. It preserves durable reports and never overwrites source or kills unrelated processes.

Requires `uv`, Node.js 24+, npm, curl, and Linux `setsid`; the rehearsal also uses `jq`. For contained candidate execution, install Bubblewrap and allow unprivileged user namespaces. See the root README.
