# ADR 0001: Model-controlled research loop

Status: Proposed

## Context

AlphaBench T3 places CoT/ToT/EA control in deterministic external code. The model generates factor candidates but does not decide when to evaluate, refine, pivot or stop. The next research phase needs a genuine long-horizon quantitative researcher while retaining the paper baseline and independent verifier.

## Decision

Add AgenticSearchRunner behind the existing SearchRunner boundary. The model emits one strict JSON action per turn from a small action set:

    propose
    evaluate
    refine
    pivot
    stop

Harness validates and executes actions through ToolGateway. It does not select the model's next branch or normal stopping point.

PaperRunner remains unchanged and is used as the control condition.

## Alternatives

### Extend the existing CoT class

Rejected. It would keep branch and stopping control in external code and blur paper baseline with Agentic behavior.

### Let the model call FFO directly

Rejected. Direct access prevents query accounting, period alias enforcement, result sanitization and future verifier isolation.

### Use native provider function calling as the only protocol

Rejected for v0.2. Strict JSON actions are provider-neutral and replayable. Native tool calling may be added as a transport adapter later.

### Put Verifier tools in the Agent tool list

Rejected. Verifier must remain unreachable until after Agent termination.

### Force stop on statistical plateau

Rejected as normal behavior. Plateau is an observation for the model. Harness force-stops only at the high safety ceiling or operational failure.

## Consequences

Positive:

- model genuinely owns research policy;
- decisions and evidence are attributable;
- paper and Agentic loops remain comparable;
- no-discovery becomes measurable;
- long trajectories support later SFT/RL.

Negative:

- structured state projection becomes necessary;
- invalid/repeated actions require careful handling;
- more trials increase false-discovery risk;
- Group B/F verifiers are prerequisites for credible claims;
- future arbitrary-code tools require stronger container isolation.

## Versioning

- main and v0.1.0-paper-harness remain the baseline.
- this ADR lives on codex/agentic-loop-design.
- implementation starts only after ADR approval on codex/agentic-loop-v0.2.
