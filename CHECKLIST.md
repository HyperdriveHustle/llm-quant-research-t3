# Implementation Checklist

## Paper Alignment

- [x] AlphaBench paper revision reviewed.
- [x] Paper-period runtime pinned to full SHA 3a880599358fc81d8b3e0ec89419a7912a5dc694.
- [x] Qlib backend retained; Assay disabled.
- [x] CSI300, daily OHLCV, Alpha158, VWAP exclusion retained.
- [x] CoE, ToT and EA classes reused rather than rewritten.
- [x] Paper IC>0.03 threshold and retry/success/update/diversity metrics implemented.
- [x] Smoke and extension outputs cannot be labeled paper results.
- [ ] Author's exact Qlib data snapshot/hash is unavailable.
- [ ] Full paper-budget CoE/ToT/EA matrix has not been executed.

## Data

- [x] Project-local data path; no ~/.qlib or existing repository data.
- [x] Data release tag pinned to 2026-07-29.
- [x] Release manifest, archive size and archive SHA256 verified.
- [x] Safe extraction rejects path traversal, links and device entries.
- [x] Snapshot manifest contains 61,258 files and aggregate content hash.
- [x] Calendar covers 2000-01-04 through 2026-07-29.
- [x] Paper range 2020–2025 is covered.
- [x] Historical CSI300 membership ranges are present.
- [x] Sampled instruments contain open/high/low/close/volume files.
- [x] Inadequate Qlib sample ending 2020-09-25 was removed.

## Model

- [x] Ark Coding OpenAI-compatible base URL configured through environment variables.
- [x] Responses API tested with glm-5.3.
- [x] API key stored only in ignored chmod-600 .env.
- [x] API key excluded from config, logs, artifacts and trajectories.
- [x] Upstream hard-coded third-party credential removed by overlay.
- [x] PaperRunner prompt semantics preserved; Agentic profile uses its separately versioned action prompt.
- [x] Token usage and response hashes recorded.

## Agent / Verifier Isolation

- [x] Search and Verify FFO use separate processes.
- [x] Search and Verify FFO use different loopback ports.
- [x] Search and Verify FFO use separate snapshot-scoped caches.
- [x] Verifier subprocess receives a sanitized environment.
- [x] Verifier refuses to start if model credentials are present.
- [x] Verifier never calls GLM.
- [x] Agent completes and freezes before Verifier starts.
- [x] FrozenSubmission is hash-addressed and read-only.
- [x] Verifier checks submission, config, data manifest and upstream hashes.
- [x] Verifier checks the Harness Python/schema source-tree fingerprint.
- [x] Verifier recomputes metrics rather than trusting Agent output.
- [x] Verifier results are stored in a separate trajectory.
- [ ] OS-user/container isolation is required before enabling arbitrary-code Agent tools.

## Reliability

- [x] macOS multiprocessing spawn bug in paper runtime patched without changing evaluation logic.
- [x] Generator validation is routed to configured Search FFO.
- [x] Failed evaluator calls return structured failure records.
- [x] FFO services have health checks, startup deadline and forced termination fallback.
- [x] Download supports resumable Range requests and detects truncation.
- [x] Ruff passes.
- [x] Python compileall passes.
- [x] 68 tests pass.
- [x] Measured unit-test coverage is 74%; real end-to-end paths are additionally exercised.

## Real Smoke Evidence

- [x] Ark model smoke succeeded.
- [x] End-to-end Search FFO → GLM → freeze → Verify FFO succeeded.
- [x] Natural invalid-output retry occurred and was logged.
- [x] Final smoke candidate was independently recomputed with zero metric mismatch.
- [x] Artifact/log/trajectory secret scan passed.
- [x] Smoke result remains labeled paper_result=false.
- [x] Agentic GLM-5.3 smoke completed Search FFO → freeze → protocol verifier → hidden OOS.
- [x] Search evidence recomputed with zero metric mismatch.
- [x] Hidden OOS exposed search overfit rather than feeding results back to the Agent.
- [x] Verifier separates integrity `verification_status` from `research_outcome.status`.
- [x] Three real GLM-5.3 task configs pass config/data/runtime doctor.
- [x] Background suite launcher, sequential worker, live status and aggregate analysis are tested.
- [x] Parallel suite launches three process-isolated tasks with distinct FFO ports and caches.
- [x] Paper-compatible strict 1% NaN gate remains active in all three real tasks.
- [x] All three real-task rolling-factor preflights pass on the frozen Qlib snapshot.
- [x] Candidate-registration stall is bounded independently of token or evaluator-call budgets.

## Extensions

- [x] Agentic Goal Loop action/state/ledger/gateway runtime is implemented in v0.2.
- [x] Controlled hidden OOS and seed-relative diagnostics are implemented for the agentic profile.
- [x] Evaluator-call/token checkpoints are recorded for long-horizon analysis.
- [x] All extensions are disabled in paper-compatible config.
- [ ] Null/falsification-world task groups remain future experiment work.
- [ ] Exact-prefix OOS replay and cross-run checkpoint aggregation remain future analysis work.
- [ ] Algebraic factor-equivalence/novelty gating remains future verifier work.
