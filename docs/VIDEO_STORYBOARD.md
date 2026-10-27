# FaultLine: three-minute evidence-led demo

Record at 1080p with readable browser text. Open the actual Inspector and preserve the job's evidence. Never expose credentials. Verify the selected provider before recording.

| Time | Picture | Narration |
| --- | --- | --- |
| 0:00–0:12 | Actual failed baseline screenshot or storefront checkout without a coupon | “A valid coupon works. Leaving it empty crashes this checkout. Can a model fix that without breaking pricing?” |
| 0:12–0:30 | Inspector readiness and provider, then start a job | “This is a deliberately seeded defect. FaultLine reproduces it in a browser and asks Meta for a bounded source patch.” |
| 0:30–1:05 | Observed baseline report, HTTP 500, real trace | “The baseline must fail for the expected reason. A red dashboard alone is not evidence.” |
| 1:05–1:35 | Actual proposal, provider identity, diff, patch validation | “The model proposes the change. Exact paths, source hashes, hunk checks, and AST policy decide whether it can enter verification.” |
| 1:35–2:10 | Candidate browser screenshot and independent assertion results | “The candidate runs separately. The same browser checkout must succeed; independent checks protect coupons, quantities, totals, and stored orders.” |
| 2:10–2:35 | Download trace/report, show cleanup status | “These are the recorded artifacts. Green requires passing checks and confirmed cleanup. This verifies a candidate; it does not deploy to production.” |
| 2:35–3:00 | Visible source link and final job result | “The useful output is a repair you can inspect and reproduce. The next test is whether this holds up on unfamiliar defects.” |

If generation takes longer, leave enough screen time to read the result. Disclose any cut or speed-up and retain the original job duration. Do not substitute authored previews for measured evidence. If Meta is unavailable, identify the deterministic rehearsal and record the live Meta portion separately once it is available.

Before recording: `make check`, the contained runtime integration check, and `./scripts/rehearse-demo.sh`. Show an actual policy rejection in a separate technical clip if useful; do not claim a rejected patch was generated live unless its attempt record proves it.

The first clip should show the failure immediately. For a short social post, use the failed browser view, the actual diff, the passed candidate, and the source link. Do not promise a recovery time, uptime guarantee, avoided loss, certification, or hackathon score without supporting evidence.
