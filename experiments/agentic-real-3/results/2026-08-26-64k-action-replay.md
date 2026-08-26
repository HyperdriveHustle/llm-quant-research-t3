# GLM-5.3 Action Replay: 32K vs 64K Output Budget

Experiment date: `2026-08-26`

Purpose: replay historical Agent states that previously produced truncated JSON at the provider's 32,768-token output ceiling. System prompt, serialized ResearchState and temperature were kept unchanged; only `max_output_tokens` and, for the final T1 replay, client timeout were increased. Replays did not call FFO or mutate original trajectories.

## Samples

| Sample | Input tokens | Original 32K result | 64K result | Elapsed | Schema |
|---|---:|---|---|---:|---|
| T3 rank-form refinement | 15,209 | 32,768 output tokens; 2,926-character partial JSON | 30,946 output tokens; `status=completed`; 4,107-character action | 439.1s | Valid |
| T1 post-refinement decision | 16,314 | 32,768 output tokens; visible text `{"` | 65,536 output tokens; `status=incomplete`; `reason=length`; visible text `{"` | 944.7s | Invalid |

The first T1 64K attempt used the old 600-second timeout and ended in a client read timeout. Repeating the same sample with a 1,200-second timeout allowed the provider response to finish and confirmed that the model itself exhausted the full 65,536-token allowance.

## T3 successful replay

- Source response: `resp_021787720450820c175de5f11b223efcc3ac4becea38bcf4b7ad2`
- Replay response: `resp_021787747220117c307614e525f20fb46bf280deeb3243dea29f5`
- Action: `refine`
- Action ID: `act_011_rankvol_refine_from_seed_klen`
- Output items: `reasoning`, `message`
- Content block: `output_text`
- Requested output budget reached: `false`
- JSON/action schema valid: `true`

Runtime report:

```text
runs/replay/glm53-action-64k-20260826.json
```

## T1 failed replay

- Source response: `resp_0217877192767012bb0e15ce9d6e916e2131d2dc0777c54abdc85`
- Replay response recorded in the runtime report
- Output tokens: `65,536`
- Provider status: `incomplete`
- Incomplete reason: `length`
- Output items: `reasoning`, `message`
- Visible message: `{"`
- JSON error: `Unterminated string starting at`

Runtime report:

```text
runs/replay/glm53-action-64k-1200s-t1-20260826.json
```

## Conclusion

Increasing the output budget from 32K to 64K can recover some complex actions, but it does not reliably solve schema stability. One of two representative replays became valid; the harder T1 state consumed the entire doubled allowance and still failed. Raising the invalid-action or total-turn limit without reducing this failure mode would multiply latency and token cost: the failed T1 replay consumed 65,536 output tokens and almost 16 minutes for no usable action.

The next experiment should not immediately rerun the full suite. It should compare a compact ResearchState plus an action-serialization mode with deep thinking disabled or function-call arguments. Provider truncation/incomplete responses must be classified separately from model schema violations and must not increment the research invalid-action threshold.

## Follow-up compatibility and compact-state tests

Further provider tests showed that this GLM-5.3 endpoint does not support `thinking.type=disabled`, and Chat Completions does not support `response_format.type=json_schema`. Chat JSON mode still exhausted an 8,192-token budget on the uncompressed T1 state and returned only `{"`.

The deterministic StateProjector was then compacted: repeated expected observations/decision rules were removed from recent experiments and last observation, top-factor rationale was omitted, and checkpoint/history views were bounded. The same T1 state fell from 51,492 to 29,145 characters and from 16,314 historical input tokens to 11,538 replay input tokens. A Responses replay with 65,536 output budget completed in 314.9 seconds using 19,693 output tokens and returned a 4,899-character, schema-valid `pivot` action. This validates `compact state + Responses 64K` as the rerun configuration; unsupported structured-output/thinking controls remain disabled.
