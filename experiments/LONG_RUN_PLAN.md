# GLM-5.3 Long-run IC Experiment Plan

## Decision

The long-run study is divided into four groups. Group A is the required paper-compatible core. Groups B–D answer different research questions and must not be merged into the paper score.

All groups reuse:

- model: GLM-5.3 through Ark Responses API;
- Qlib 0.9.7 and the pinned 2026-07-29 data snapshot;
- CSI300 daily OHLCV;
- close_return, next-day return semantics;
- pinned AlphaBench commit 3a880599;
- Alpha158 seeds and original factor filter;
- Search FFO / Verify FFO isolation;
- IC, RankIC, ICIR and paper search metrics;
- immutable submissions and full trajectories.

## Group A — Paper-compatible T3 Core

### A1: CoE / CoT Sequential Refinement

Goal:

> Starting from each KBar and price Alpha158 seed, find a valid formula with higher IC than the seed; report whether the final IC exceeds 0.03.

Settings:

| Field | Value |
|---|---|
| Seeds | KBar + Price, VWAP excluded |
| Rounds | 10 per seed |
| Candidate generation | 1 per round |
| Maximum retries | 5 per valid step |
| Selection | Higher IC; RankIC/IR tie-break |
| Main outputs | search cost, success rate, seed delta, IC>0.03, trajectory |

Expected upper-bound workload from the pinned seed set is approximately 13 seeds × 10 rounds = 130 candidates, excluding retries.

### A2: ToT Branching Search

Goal:

> Determine whether branching exploration finds better and more diverse factors than the sequential chain under the paper search policy.

Settings:

| Field | Value |
|---|---|
| Seeds | KBar + Price, VWAP excluded |
| Depth | 3 |
| Candidates per node | 6 |
| Survivors per node | Up to 3 |
| Maximum retries | 5 |
| Main outputs | best IC, successful-run fraction, AST/output diversity, search cost |

The worst-case tree contains 1 + 3 + 9 expanded nodes per seed and 6 candidates per node, or about 78 candidates per seed before retries. It is the largest paper-core workload.

### A3: EA Population Search

Goal:

> Evolve an Alpha158 population through mutation and crossover and measure how often the best pool is updated.

Settings:

| Field | Value |
|---|---|
| Initial pool | Pinned paper commit: KBar + Rolling, VWAP excluded |
| Population | 30 |
| Generations | 10 |
| New candidates | 30 per generation |
| Mutation / crossover | 0.4 / 0.6 |
| Seed context | Top 12 by IC |
| Main outputs | best-update rate, IC>0.03, normalized gain, population diversity |

Expected workload is the initial seed evaluation plus approximately 300 generated candidates and 20 model generation calls.

### Group A success criteria

Group A does not require every run to find an effective factor. It succeeds experimentally when:

1. every generated candidate and retry is recorded;
2. Search and Verify FFO results match under the same paper period;
3. paper metrics are computable for all three algorithms;
4. model/runtime failures are distinguishable from “no alpha found”;
5. any IC>0.03 claim is reproduced by independent Verify FFO.

## Group B — Temporal Generalization

This is a controlled extension for detecting selection overfitting. The model sees only the search period; validation/test results remain verifier-only.

| Task | Search period | Validation | Final test | Goal |
|---|---|---|---|---|
| B1 | 2020–2022 | 2023 | 2024 | Early-history discovery → later regime |
| B2 | 2020–2023 | 2024 | 2025 | Bear/search → rebound/test |
| B3 | 2020–2024 | first half 2025 | second half 2025 | Recent-history stability |

Primary measurements:

    selection_gap = search IC - test IC
    oos_delta = test IC(candidate) - test IC(seed)
    direction_retention = sign(search IC) == sign(test IC)

EA is the primary Group B algorithm because its evaluation budget is explicit and easier to hold constant. CoT/ToT can be added only as matched-budget comparisons.

Group B must be implemented as a new controlled_oos profile. It cannot be simulated by showing validation metrics to the search loop.

## Group C — Agent Loop Control

Goal:

> Test whether giving GLM-5.3 control over propose/evaluate/refine/pivot/stop improves hidden OOS results over the external paper loop.

Paired conditions:

| Condition | Loop controller | Data/evaluator/budget |
|---|---|---|
| C0 | Original EA | Fixed |
| C1 | GLM-5.3 Agent Loop | Identical to C0 |

Required controls:

- same seed population;
- same factor-evaluation count;
- same maximum submissions;
- same data snapshot and test split;
- same model version and sampling;
- verifier results never returned to the episode.

This group is not enabled in v0.1.

## Group D — Token Budget Scaling

Goal:

> Measure whether more model tokens improve hidden OOS utility when factor-evaluation calls are held fixed.

Suggested pre-registered logical-token budgets:

    16K, 32K, 64K, 128K per episode

Primary utility:

    U(B) = test signed RankIC(candidate) - test signed RankIC(best seed)

Also report:

- test IC and ICIR;
- selection gap;
- accepted candidates per 1K tokens;
- evaluator calls per effective improvement;
- repeated/duplicate candidate rate;
- marginal utility per additional 1K tokens.

Group D runs only after Group B provides a hidden test protocol. Otherwise more tokens may only mean more adaptation to the same search period.

## Recommended execution order by evidence dependency

    A3 EA paper-compatible core
      → A1 CoT
      → A2 ToT
      → B1/B2/B3 temporal generalization
      → C0/C1 loop-control comparison
      → D token-budget scaling

This is an evidence dependency, not a time schedule. A later group is interpretable only after its required verifier boundary exists.
