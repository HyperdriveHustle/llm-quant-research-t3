# Implementation Review

## Summary

- Scope: standalone Harness, pinned Paper Runtime overlay, data pipeline, dual FFO runtime, model adapter, verifier, artifacts, trajectory, reports and tests.
- Review perspectives: Skeptic, Architect, Minimalist.
- Verdict: PASS for v0.1 paper-compatible Harness and v0.2 agentic extension.
- Not claimed: exact author data reproduction, full benchmark execution, arbitrary-code Agent sandbox.

## Intent

The implementation should reproduce AlphaBench T3 with the smallest possible local Harness, configure GLM-5.3 through Ark Responses API, preserve original search semantics, and prevent the research model from reading or modifying verifier state.

## Skeptic Review

### Resolved HIGH: upstream credential exposure

The paper-period LLM client contained a hard-coded third-party key. The runtime overlay replaces the transport completely and scans the patched runtime for hard-coded sk-style credentials. Project config stores only environment variable names.

### Resolved HIGH: wrong Qlib sample

Qlib's package downloader returned example data ending 2020-09-25, which cannot cover the paper. The audit rejected it. The implementation now pins community release 2026-07-29, verifies the publisher manifest, archive length and SHA256, and removes the inadequate sample.

### Resolved HIGH: macOS process failure

The paper commit used a nested multiprocessing target, which is not picklable with macOS spawn. The overlay moves only that wrapper to module scope; evaluator logic is unchanged.

### Resolved HIGH: internal evaluator misrouting

The paper generator's validity check defaulted to port 9889 while Harness Search FFO used a role-specific port. The overlay makes the URL environment-driven and PaperRunner injects only the Search endpoint.

### Resolved HIGH: verifier input substitution

Submission hashing alone did not prove that Verifier used the same config and data snapshot. Verifier now rejects any mismatch in config SHA256, data-manifest SHA256 or upstream commit before computing metrics.

### Remaining MEDIUM: process isolation is not an OS sandbox

Agent and Verifier use different processes, ports, credentials and caches, and run sequentially. Because strict T3 only allows formula text generation, the model has no arbitrary filesystem or network tool. Before a future Agentic profile receives shell/Python tools, Verifier must move to another OS user or container with a one-way artifact mount.

### Remaining MEDIUM: exact paper bytes are unavailable

The paper states 2020–2025 but provides no data snapshot hash or paper tag. The implementation is therefore explicitly paper-compatible, not bitwise identical. Config validation prevents paper_result=true without an exact snapshot attestation.

## Architect Review

The dependency direction is intentionally narrow:

    CLI/Orchestrator
      → PaperRunner → pinned AlphaBench searchers
      → FFOClient → paper FFO
      → ArtifactFreezer
      → isolated VerifierWorker

Stable interfaces exist for ModelClient, FactorEvaluator, SearchRunner, FrozenSubmission, TrajectorySink and Verifier. Initial implementations are direct adapters to the paper code; no parallel DSL, backtester or metric engine was created.

Search and Verifier caches are role-specific and include the data-manifest hash in their filename, preventing stale results after snapshot changes. Verifier receives no model credentials and refuses to run if any secret-like provider variable survives sanitization.

The main architectural limitation is global import/cwd behavior in the paper runtime. PaperRunner restores cwd, sys.path and temporary environment values and should remain single-run-per-process. Parallel benchmark execution should use one Harness process per run.

## Minimalist Review

The implementation reuses:

- paper CoE/ToT/EA classes;
- paper Alpha158 JSON library;
- paper prompt and retry logic;
- paper FFO and factor metrics;
- Qlib data format and loader.

Custom code is limited to transport, configuration, integrity, isolation, orchestration, data provenance and normalized reporting. Earlier fragmented design documents and experiments were consolidated into four core documents. The obsolete task-manifest template and insufficient Qlib sample were removed.

No separate web UI, database service, generic multi-agent framework, strategy engine or portfolio optimizer was introduced.

## Evidence

Static and unit verification:

    ruff check src tests
    pytest
    python -m compileall -q src tests

All pass. The test suite covers config rejection, secret redaction, model response parsing, archive validation, data audit, FFO normalization, artifact tamper detection, verifier hash gates, dual-runtime ordering, upstream alignment, paper metrics and trajectory secret protection.

Real smoke run:

    run_20260826_002829_671ae567

The model required two Responses API calls because the first output failed the paper generator's JSON/validation path. The accepted candidate achieved IC 0.0286427, RankIC 0.0498399 and ICIR 0.213646 on the smoke period. Independent Verify FFO reproduced all values exactly with no mismatch and no model credentials. Since IC is below the paper's 0.03 effective threshold and the period/budget are smoke settings, the result is correctly classified as a pipeline success, not an effective factor or paper result.

## Verdict Rationale

PASS means the v0.1 Harness is suitable for running a paper-compatible T3 experiment. It does not mean the full paper result has been reproduced. The remaining limitations are explicit, fail-closed in config, and do not invalidate the completed strict smoke path.

## v0.2 Agentic Extension Review

The v0.2 branch adds a second SearchRunner without changing PaperRunner. GLM-5.3 owns `propose / evaluate / refine / pivot / stop`; deterministic code owns JSON-schema validation, immutable ID registration, Search FFO execution, state reduction, safety finalization and artifact freezing. Every valid action and invalid repair turn is hash-chained in `ledger.jsonl`, and ProtocolVerifier replays the full state before any outcome metric is accepted.

Skeptic review found and resolved four material issues during real smoke: an orchestrator-created `service_logs` directory conflicted with runner initialization; a 180-second model timeout was too short for GLM-5.3 long reasoning; auxiliary seed evidence was initially rejected even though it legitimately supported a relative-performance claim; and FFO exceptions could abort an episode instead of becoming failed experiments. Tests now cover run-directory reuse, oversized/malicious actions, unknown IDs, failed evidence, FFO exceptions, forced stop, hash tampering and hidden-period separation.

Architect review confirmed that AgenticSearchRunner receives a Search-role client only. Search FFO terminates before the Verifier FFO and credential-sanitized verifier worker start. The frozen boundary includes config, data manifest, pinned upstream, Harness Python/schema source tree and pre-freeze ledger head. Search evidence is independently recomputed before hidden OOS is evaluated; OOS output never returns to the ended episode.

Minimalist review removed the over-restrictive auxiliary-evidence rule and retained the original Alpha158 loader, Qlib DSL, FFO engine, metrics and FrozenSubmission channel. No shell, Python execution, general network tool, portfolio engine or parallel factor evaluator was introduced into the model tool surface.

The final current-HEAD real run `run_20260826_100425_b856dd77` used six model calls, five factor evaluations and two recorded invalid/repair turns. It established all three seed baselines, then evaluated `REV5` and `VREV5`; both had negative IC and failed the pre-registered positive-direction gate. The model correctly stopped with `no_discovery` and cited all five experiments as counter-evidence. Protocol, input/source hashes and hidden seed recomputation passed with zero mismatch; `verification_status=passed` and `research_outcome.status=no_submission_to_assess`. A preceding submitted-factor run (`run_20260826_093911_1862939f`) selected a sign-reversed seed transform that failed hidden OOS, motivating the explicit separation between verifier integrity and research outcome.

Remaining limitations are explicit: arbitrary-code tools still require OS/container isolation; null/falsification task groups are not yet run; exact-prefix hidden replay and cross-run checkpoint aggregation remain future analysis; formula-equivalence/novelty gating is not yet implemented (the final smoke's `REV1R` is a sign reversal of a seed); and the publisher still does not provide the authors' exact Qlib snapshot hash.
