# GLM-5.3 Long-horizon Research Plan

## Principle

The long-horizon study does not optimize or constrain model-call cost. Paper reproduction keeps the paper's original rounds; autonomous tasks may continue for as many model calls as needed.

Tokens, model calls and factor evaluations are still recorded because:

- every attempted factor must enter the multiple-testing ledger;
- prefix checkpoints reveal whether longer research improves OOS evidence;
- repeated validation queries are a signal of selection overfitting;
- runs must remain finite and operationally safe.

Long autonomous episodes terminate by scientific criteria, not by token budget:

1. required evidence gates are satisfied and the Agent submits;
2. the Agent concludes that the hypothesis should be rejected;
3. a plateau is reached across multiple hypothesis branches;
4. only a generous fail-safe evaluator ceiling is reached.

All groups reuse GLM-5.3, the pinned Qlib snapshot, CSI300 daily OHLCV, close_return, Alpha158, pinned AlphaBench code, isolated Search/Verify FFO, immutable submissions and complete trajectories.

## Group A — Paper-compatible T3

Group A establishes the original benchmark baseline. Its search depth remains fixed because changing it would no longer reproduce the paper task.

### A1: CoT sequential refinement

Goal:

> Starting from each KBar and price Alpha158 seed, find a valid formula with higher IC than the seed and determine whether IC exceeds 0.03.

| Setting | Value |
|---|---|
| Seeds | KBar + Price, VWAP excluded |
| Rounds | 10 per seed |
| Generation | 1 candidate per round |
| Retry | Up to 5 per valid step |
| Selection | IC; RankIC/IR tie-break |
| Verifier | PaperFactorVerifier |

Approximate upper-bound workload: 13 seeds × 10 rounds = 130 candidates before retries.

### A2: ToT branching search

Goal:

> Determine whether branching exploration finds better and more diverse factors than the sequential chain.

| Setting | Value |
|---|---|
| Seeds | KBar + Price |
| Depth | 3 |
| Candidates per node | 6 |
| Survivors | Up to 3 |
| Verifier | PaperTreeVerifier |

Worst-case workload is about 78 candidates per seed, approximately 1,014 candidates over 13 seeds.

### A3: EA population search

Goal:

> Evolve an Alpha158 population through mutation and crossover and measure how often the best population is updated.

| Setting | Value |
|---|---|
| Initial pool | KBar + Rolling in pinned paper commit |
| Population | 30 |
| Generations | 10 |
| New candidates | 30 per generation |
| Mutation / crossover | 0.4 / 0.6 |
| Seed context | Top 12 by IC |
| Verifier | PaperPopulationVerifier |

Expected workload: initial seed evaluation plus approximately 300 new candidates and 20 primary generation calls.

## Group B — Temporal generalization

Group B detects whether long search merely adapts to one historical period. The Agent sees search metrics only; validation/test remain verifier-only.

| Task | Search | Validation | Test | Research question |
|---|---|---|---|---|
| B1 | 2020–2022 | 2023 | 2024 | Does early-history alpha survive a later regime? |
| B2 | 2020–2023 | 2024 | 2025 | Does bear-period research survive the rebound? |
| B3 | 2020–2024 | 2025 H1 | 2025 H2 | Does recent research survive immediate forward time? |

Primary verifier:

    selection_gap = search IC - test IC
    oos_delta = test IC(candidate) - test IC(seed)
    direction_retention = sign(search IC) == sign(test IC)

EA is the primary algorithm because it supports large, explicit populations. CoT/ToT become secondary comparisons.

## Group C — Deep single-family research

These are genuine long-horizon Agent tasks. Each episode receives a broad research goal and may repeatedly propose, evaluate, refine, ablate, reject or pivot.

| Task | Goal | Required final evidence |
|---|---|---|
| C1 Momentum | Discover robust trend/momentum formulas | Search IC>0.03 candidate; positive OOS direction; ablation |
| C2 Reversal | Discover short/medium reversal formulas | Same, across at least two regimes |
| C3 Volume | Discover volume/liquidity proxy formulas | Incremental value beyond price-only seed |
| C4 Volatility | Discover volatility-conditioned return signals | Stable ICIR and regime analysis |
| C5 Price–Volume | Discover interaction/divergence formulas | Low correlation with C1–C4 pool |

Agent-visible tools:

    get_task_spec
    get_seed_pool
    check_factor
    evaluate_factor
    evaluate_batch
    factor_similarity
    record_hypothesis
    record_decision
    freeze_submission

Required research phases:

1. map the mechanism and generate a hypothesis tree;
2. broad exploration across distinct formula structures;
3. deepen promising branches with parameter and structural edits;
4. run ablation and redundancy checks;
5. test regime sensitivity on search-only subwindows;
6. reject, pivot or submit with evidence.

Scientific plateau:

> No improvement in the primary robust-search score across 100 consecutive valid evaluations, with at least three independent hypothesis branches attempted.

The fail-safe ceiling is 5,000 factor evaluations per episode. It prevents runaway execution but is not an optimization target.

Verifier: HiddenHypothesisVerifier. It checks frozen direction, OOS IC/RankIC/ICIR, evidence references, ablation, redundancy and selection gap.

## Group D — Diverse factor-pool construction

Goal:

> Produce a library of complementary factors rather than one historical winner.

Target submission:

- up to 10 frozen factors;
- multiple economic mechanism families;
- paper-valid formulas;
- high structural diversity;
- pairwise absolute output correlation below the registered threshold;
- positive combined OOS IC/RankIC;
- no single factor dominating the combined score.

The Agent may search broadly for thousands of candidates, but all trials remain in the ledger. Individual high IC is insufficient if the factor duplicates an existing signal.

Verifier: FactorPoolVerifier. It recomputes every factor, D_AST, D_corr, combined equal-weight z-scored signal, leave-one-factor-out ablation and OOS stability.

## Group E — Loop-control comparison

Goal:

> Determine whether a self-directed research loop is better than the original external EA loop when both can run long enough to converge.

| Condition | Controller |
|---|---|
| E0 | Original AlphaBench EA |
| E1 | GLM-5.3 Agent Loop |

The primary comparison is unconstrained final OOS quality under the same fail-safe ceiling. Secondary matched-prefix comparisons are made at:

    50, 100, 250, 500, 1000 factor evaluations

This produces a search-quality curve without forcing the long Agent to stop at each checkpoint.

Verifier: PairedLoopVerifier. It checks data/seed/model equality, compares prefix and final OOS results, and reports research depth, duplicate rate, pivot quality and false-discovery behavior.

## Group F — Null and falsification

Long search dramatically increases the chance of finding lucky historical correlations. Group F is mandatory before claiming that Groups C–E discover alpha.

| Task | Environment | Expected behavior |
|---|---|---|
| F1 Label Shuffle | Future returns shuffled within date | No factor should pass final gates |
| F2 Time Permutation | Return dates permuted in blocks | Agent should reject or stop |
| F3 Null Twin | Same market structure with planted alpha removed | False discovery rate remains controlled |

Verifier: NullDiscoveryVerifier. Because ground truth is known, it directly reports:

    false_discovery_rate
    claims_per_1000_trials
    best_visible_null_IC
    hidden_null_IC
    correct_no_discovery_rate

An Agent that always submits a factor is penalized. Correctly concluding “no supported discovery” is a successful outcome.

## Trajectory checkpoints, not budgets

Every long episode records best-so-far and research-process state at:

    evaluator calls: 50 / 100 / 250 / 500 / 1000 / 2500 / 5000
    cumulative logical tokens
    elapsed model calls

These checkpoints answer whether additional research continues to create OOS value. They do not limit the Agent or create separate token-budget tasks.

## Evidence dependency

    A3 → A1/A2
       → B1/B2/B3
       → C1–C5 + F1–F3
       → D
       → E0/E1

This is an evidence dependency, not a time schedule. Group F must accompany any open-ended long search, and no test result may be returned to the active episode.
