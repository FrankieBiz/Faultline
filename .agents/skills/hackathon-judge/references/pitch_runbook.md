# Three-minute rehearsal

Use the maintained [video storyboard](../../../../docs/VIDEO_STORYBOARD.md) as the script. The Inspector is at port 4000 by default; the storefront is at 3000.

1. Run `make check`, `make browser`, and the contained runtime integration suite.
2. Start `./scripts/start-demo.sh`; inspect actual readiness/provider. Alternate ports are supported with `BUGGYSHOP_API_PORT`, `FAULTLINE_PORT`, `BUGGYSHOP_PORT`, and `INSPECTOR_PORT`.
3. Run `./scripts/rehearse-demo.sh`; it must exit zero with a reproduced failure, verified candidate, and confirmed cleanup. Set `FAULTLINE_INSPECTOR_URL` when using another Inspector port.
4. Show the actual failed browser result, the provider's diff, the passing candidate, and the artifact downloads. Keep source and job identity visible.
5. Explain limits: one seeded scenario, isolated verification, no production deployment, no customer-impact or performance benchmark.

Configured provider errors remain visible. Missing-key deterministic rehearsal must be named as such; no offline UI toggle is claimed. If an owned service freezes, stop the launching script and inspect its logs. Never kill unrelated browser processes or erase evidence to recover the demo.
