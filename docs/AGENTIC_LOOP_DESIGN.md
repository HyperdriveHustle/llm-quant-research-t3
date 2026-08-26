# Model-controlled Agentic Research Loop Design

Status: implemented and smoke-tested
Target version: v0.2
Baseline: v0.1.0-paper-harness
Implementation branch: codex/agentic-loop-v0.2

## 1. Decision

The new loop gives GLM-5.3 control over research decisions while keeping all numerical truth and security boundaries outside the model.

The model decides:

    propose → evaluate → refine → pivot → stop

The Harness decides only:

    validate contract
    register immutable IDs
    execute Search tools
    return factual observations
    maintain append-only state
    enforce hard safety limits
    freeze the final artifact

The Harness must not choose the next hypothesis, parent factor, branch, pivot or normal stopping point for the model.

## 2. Compatibility strategy

The existing PaperRunner remains unchanged and is the control condition.

    SearchRunner
      ├── PaperRunner             # v0.1 behavior; external CoT/ToT/EA
      └── AgenticSearchRunner     # v0.2; model-controlled actions

Both runners reuse:

- the same pinned AlphaBench/Qlib environment;
- the same Alpha158 seeds and DSL;
- the same Search FFO interface;
- the same FrozenSubmission format;
- the same independent Verifier Runtime;
- the same data and upstream hash gates.

This keeps the difference attributable to loop control.

## 3. Responsibility boundary

| Concern | Model | Harness |
|---|---:|---:|
| Form a hypothesis | Yes | Store and validate schema |
| Choose a factor to test | Yes | Resolve factor ID |
| Generate/refine formula | Yes | DSL/static validation |
| Choose next branch | Yes | No ranking intervention |
| Choose pivot | Yes | Close/open hypothesis records |
| Request search evaluation | Yes | Execute Search FFO |
| Calculate IC/RankIC/ICIR | No | Search FFO |
| Access hidden validation/test | No | Verifier only |
| Decide normal stop | Yes | Validate/freeze |
| Force safety stop | No | Yes |
| Modify/delete history | No | Append-only ledger |

## 4. Architecture

    ┌──────────────────── Agent Runtime ─────────────────────┐
    │                                                        │
    │  StateProjector → GLM-5.3 → ActionParser               │
    │       ↑                         ↓                      │
    │  ResearchLedger ← ToolResult ← ToolGateway             │
    │                              ↓                         │
    │                         Search FFO                      │
    └───────────────────────────┬────────────────────────────┘
                                │
                       FrozenSubmission
                                │
                                ▼
    ┌────────────────── Verifier Runtime ────────────────────┐
    │ ProtocolVerifier + HiddenOutcomeVerifier + Verify FFO  │
    └────────────────────────────────────────────────────────┘

Verifier is never an Agent tool and its endpoint is absent from Agent configuration.

## 5. Agent actions

The action set is intentionally small. Batch evaluation and ablation are represented through these actions rather than additional top-level verbs.

### propose

Purpose: create a falsifiable hypothesis and one or more initial factor candidates.

Required model decisions:

- market mechanism;
- expected signal direction;
- why the mechanism may predict future returns;
- falsification rule;
- initial formulas.

Harness behavior:

- assign hypothesis_id and factor_id values;
- reject malformed or duplicate formulas;
- perform static DSL checks;
- do not evaluate IC automatically.

### evaluate

Purpose: request evidence for registered factor IDs.

Required model decisions before seeing results:

- which factors to evaluate;
- permitted search-window alias;
- expected observation;
- decision rule after success/failure.

Harness behavior:

- verify IDs and window alias;
- call Search FFO only;
- count every unique and repeated trial;
- return structured metrics/errors;
- append Experiment records.

The model cannot provide an arbitrary date range. It chooses only registered aliases such as search_full, search_early or search_late.

### refine

Purpose: create child factors from a selected parent.

Required model decisions:

- parent_factor_id;
- edit type: parameter, structural, normalization, interaction or ablation;
- rationale tied to existing evidence;
- child formulas.

Harness behavior:

- preserve parent-child edges;
- static check and deduplicate;
- never auto-promote the child;
- never evaluate unless the model later requests evaluate.

### pivot

Purpose: explicitly close or suspend the current hypothesis and open a different mechanism branch.

Required model decisions:

- old hypothesis ID;
- evidence-based closure reason;
- new hypothesis and falsification rule;
- optional initial candidates.

Harness behavior:

- preserve the abandoned branch;
- mark status rejected, suspended or inconclusive;
- create the new branch;
- prevent deletion/relabeling of old evidence.

### stop

Purpose: end the episode by submitting supported factors or by declaring no supported discovery.

Modes:

    submit
    no_discovery

For submit, the model supplies factor IDs, evidence IDs, limitations and the frozen direction.

For no_discovery, the model records its conclusion and limitations; rejected hypotheses and counter-evidence remain in the immutable ledger.

Harness behavior:

- ensure referenced factors/evidence exist;
- allow no_discovery without forcing a factor;
- freeze submission and end the Agent process;
- never expose verifier results to the ended episode.

## 6. Action envelope

Every model turn returns exactly one JSON action:

    {
      "schema_version": "0.2",
      "action_id": "model-generated-id",
      "action": "evaluate",
      "reason": "Why this is the next best research step",
      "hypothesis_id": "hyp_...",
      "expected_observation": "What should happen if the hypothesis is true",
      "decision_rule": "What I will do for positive/negative evidence",
      "arguments": {}
    }

The complete machine-readable contract is in ../schemas/agent_action.schema.json.

expected_observation and decision_rule are mandatory for propose/evaluate/refine/pivot so the research intent is registered before results. They are not required for the terminal stop action.

Invalid action handling:

1. ActionParser returns a structured validation error.
2. The invalid turn is recorded.
3. The model may repair the action.
4. No research state or evaluation count changes until a valid action executes.

## 7. Tool result envelope

The Harness returns:

    {
      "schema_version": "0.2",
      "action_id": "...",
      "status": "ok | rejected | error",
      "state_version": 42,
      "observations": {},
      "registered_ids": [],
      "protocol_flags": [],
      "checkpoint": {}
    }

Tool outputs contain only structured data. They cannot contain instructions, arbitrary HTML, paths, URLs or verifier information.

## 8. Research state

ResearchState is versioned and append-only through the ledger.

    goal
    task_manifest_hash
    state_version
    hypothesis_graph
    factor_graph
    experiment_ledger
    rejected_branches
    submitted_artifacts
    trial_counts
    duplicate_counts
    checkpoint_history
    safety_state

### Hypothesis state

    proposed → active → supported
                      → rejected
                      → suspended
                      → inconclusive

### Factor state

    registered → valid → evaluated → selected
                        → rejected
                        → superseded

Only the model may request selected/rejected/superseded transitions. The Harness may mark invalid or duplicate based on deterministic checks.

## 9. State projection and long context

The model must not receive the entire raw trajectory on every turn.

StateProjector builds a deterministic view containing:

- task goal and allowed actions;
- all active hypotheses;
- top and recently changed factors;
- rejected branches and their reasons;
- recent experiments;
- aggregate trial/duplicate statistics;
- best-so-far search metrics;
- plateau advisory;
- current evaluator-call checkpoint.

Raw events remain in the verifier-readable ledger. The model receives recent experiments plus compact evidence IDs on top factors; v0.2 does not expose a free-form history tool. No second LLM summarizes state, avoiding summary drift and hidden decision-making by another model.

## 10. Loop algorithm

    initialize task and Alpha158 seeds
    create immutable ResearchState v0

    while not terminal:
        view = StateProjector.project(state)
        response = AgentPolicy.next_action(view)
        action = ActionParser.validate(response)

        if action invalid:
            record invalid_action
            return validation error to model
            continue

        result = ToolGateway.execute(action, state)
        state = ResearchLedger.append_and_reduce(action, result)

        if action == stop:
            FrozenSubmission = SubmissionFreezer.freeze(state, action)
            terminate Agent Runtime

        if hard safety ceiling reached:
            freeze ForcedStop artifact
            terminate Agent Runtime

The model can imitate CoT, ToT, EA or invent a different search policy through its actions; the Harness does not impose those structures.

## 11. Stopping semantics

Normal stopping belongs to the model.

Harness provides advisory signals:

- no robust improvement in the last 100 valid evaluations;
- all active branches weak or redundant;
- duplicate rate rising;
- current evidence gates;
- evaluator-call checkpoints.

The advisory cannot terminate the run.

Harness force-stops only for:

- 5,000 factor-evaluation safety ceiling;
- repeated schema abuse beyond the protocol threshold;
- runtime/resource failure;
- explicit operator cancellation.

ForcedStop is not considered a successful model stop.

## 12. Checkpoints without model-call budget

The episode is not token-limited. Research profiles may set the emergency model-turn ceiling to null. Harness records the first immutable state at or after each configured evaluator-call threshold:

    50 / 100 / 250 / 500 / 1000 / 2500 / 5000 factor evaluations

Each checkpoint stores:

- state hash;
- threshold and actual evaluator-call count (a batch may cross a threshold);
- best factor/pool at that recorded state;
- cumulative model calls and tokens;
- hypothesis breadth/depth;
- duplicate and repair rates;
- search metrics.

v0.2 stores replayable checkpoints and performs final hidden-OOS verification. Exact-prefix hidden replay and cross-run aggregation remain follow-up analysis; hidden results are never returned to the run.

## 13. Verifier design

Agentic submissions pass two independent layers.

### ProtocolVerifier

Checks:

- valid action sequence and state versions;
- no unregistered factor/evidence references;
- complete trial ledger;
- no hidden-window calls;
- frozen direction before verification;
- reproducible submission and trajectory hashes;
- stop mode and evidence consistency.

### OutcomeVerifier

Checks:

- hidden OOS IC, RankIC, ICIR;
- seed-relative delta and selection gap;
- regime consistency;
- factor redundancy/diversity;
- ablation and combined-pool results;
- null-world false discoveries where applicable.

Protocol quality cannot substitute for OOS results, and OOS results cannot excuse protocol violations.

## 14. Hack resistance

ToolGateway must reject:

- arbitrary filesystem paths;
- URLs or network destinations;
- Python, shell or SQL code;
- custom date ranges;
- verifier or hidden-data aliases;
- oversized candidate batches;
- mutation of existing records;
- factors not produced through registered actions.

ToolGateway sends Search FFO only allowlisted Qlib expressions and dates resolved from registered period aliases. Verify FFO remains a separate process/cache/credential domain and starts only after Agent termination.

## 15. Multiple testing

Unlimited model calls do not mean uncounted trials.

The ledger records:

- every candidate, including invalid and duplicate;
- every evaluation and repeated evaluation;
- search-window reuse;
- hypothesis branches;
- promoted/rejected candidates;
- prefix checkpoints.

Open-ended tasks must be paired with Group F null/falsification tasks. A no_discovery conclusion is valid and can outperform a system that always submits historical winners.

## 16. Configuration design

The abstract profile is in ../configs/agentic-loop.design.yaml. A runnable, explicitly non-paper smoke profile is in ../configs/agentic-smoke.yaml.

Key controls:

    allowed_actions
    allowed_window_aliases
    max_candidates_per_action
    safety_factor_evaluations
    checkpoint_evaluations
    invalid_action_threshold
    verifier_profile

There is no experimental model-call or token budget. `emergency_model_turns` is an optional operational fail-safe and may be null for long runs.

## 17. Version migration

### v0.1

Tag: v0.1.0-paper-harness

- PaperRunner only;
- paper-compatible metrics;
- independent verifier;
- immutable artifacts.

### v0.2 design

Branch: codex/agentic-loop-design

- design documents and schemas only;
- no runtime behavior changes.

### v0.2 implementation

Create after design approval:

    codex/agentic-loop-v0.2

Implementation commits should be split by responsibility:

1. action/state schemas;
2. ledger and reducer;
3. ToolGateway;
4. AgentPolicy/StateProjector;
5. AgenticSearchRunner;
6. protocol verifier;
7. integration/adversarial tests.

PaperRunner compatibility tests must pass after every commit.

## 18. Test design

### Unit

- every action schema and invalid variant;
- state transition table;
- append-only and version conflict behavior;
- duplicate factor handling;
- stop submit/no_discovery;
- prefix checkpoints;
- secret and hidden alias rejection.

### Integration

- scripted fake model completes each action path;
- real Search FFO with fake Agent policy;
- FrozenSubmission → independent Verifier;
- deterministic replay from trajectory;
- PaperRunner regression unchanged.

### Adversarial

- model requests verifier endpoint;
- model embeds path/URL/code in arguments;
- model references unknown factor/evidence;
- model attempts to rewrite history;
- model submits after seeing hidden result;
- model floods duplicate candidates;
- model never stops;
- malformed/oversized JSON.

## 19. Acceptance criteria

Design is ready for implementation when:

1. PaperRunner behavior remains unchanged.
2. Every research decision is attributable to a model action.
3. Every numerical result is attributable to a Harness tool call.
4. Agent cannot access Verifier or hidden state.
5. no_discovery is a first-class terminal result.
6. state can be replayed exactly from trajectory.
7. long episodes remain finite through a safety-only ceiling.
8. Group B/F verifier requirements are supported before open-ended claims.
