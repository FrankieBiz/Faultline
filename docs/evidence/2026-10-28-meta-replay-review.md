# Review of retained Meta controller evidence

Reviewed October 28, 2026 from committed files. No model call was made as part of this review.

The retained [job record](../replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/job.json) records job `3573b32b-09bd-4f14-897d-cf6dccf9b118`, created at 22:43:59 UTC on October 28, 2026. Its attempt metadata records `dispatched_provider=meta`, `provider=meta`, and `model=muse-spark-1.3`, a returned proposal, token usage, and 6,863 ms generation time. The controller labels the job `succeeded` / `verified` with successful cleanup. The baseline failed with the seeded TypeError; the candidate passed all 44 recorded assertions in an isolated browser runtime with verified cgroup limits.

Checks performed:

- All 16 files in this replay's `SHA256SUMS` match their recorded hashes, including the unedited controller job record, returned proposal, diff, reports, screenshots, logs, and archives.
- `python tools/verify_bundle.py docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/artifacts/0ba43aa4-dbe2-4f2e-8b33-322a8efa116c.json --artifacts-dir docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/artifacts` reports a matching bundle digest and patch hash, a failing baseline followed by 44/44 assertions, and matching hashes for all 12 listed artifacts.
- The other committed Meta replay, `82ac2dcc-e7f9-4ea7-9187-a0c0d79d8ba3`, also has 16 matching checksummed files and records a rejected first candidate followed by a verified second attempt. These are retained controller records, not a repeated-trial ledger. The first rejection was not a failed business check. The model's first diff had a zero-context hunk and passed policy, but the snapshot step's `git apply` refused it, and the attempt was recorded as `Git rejected the disposable snapshot operation`. The second attempt received that error and submitted the same change (`discounts.get(coupon_code) or 0`) with context lines. Commit `a69d705` later added `--unidiff-zero` to snapshot patch application.
- Both ZIP archives in replay `3573b32b` contain workstation source paths in `trace.stacks`. Their contents were inspected to establish that specific finding. The archives remain intact. Review or omit those files before any further publication; this review does not assert that the archives contain credentials.

The checksum verifies internal consistency, not provider-signed authenticity. Provider identity is evidence recorded by the controller, whose adapter derives it from the endpoint host and attributes attempts only after a response. This supports describing a **retained Meta controller repair**, with that provenance limit. It does not establish a new live call during this review, a reliability rate, or Meta performance on the unfamiliar-defect evaluation corpus.

**Publication status, rechecked October 28, 2026.** GitHub Pages serves `docs/` from `main` at <https://frankiebiz.github.io/Faultline/> (GitHub API status `built`). All three committed replays are publicly downloadable there and in the public repository. That includes the two `3573b32b` trace archives with workstation paths; the other two replays contain no trace archives. Whether to keep, replace, or remove those archives is the owner's decision.

The broader evaluation remains [separately documented](../EVALUATION.md): its real model runs used a labeled non-Meta provider. Repeated Meta trials and a Meta holdout evaluation are still needed.
