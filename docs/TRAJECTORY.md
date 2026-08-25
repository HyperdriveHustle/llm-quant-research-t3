# Trajectory Schema

Trajectory 必须兼容论文原生输出，同时为未来 Agentic 长程实验提供稳定事件接口。旁路记录不得改变论文 loop。

## 1. 双层保存

### Upstream Native

完整保留官方输出：

    config.yaml
    factor_seed_metrics
    llm_logs
    backtest_records
    initial_pool
    per-round/per-generation state
    final_pool
    best_factor

这些文件用于回答“是否原样运行了上游”。

### Normalized Event Stream

trajectory.jsonl 将不同算法统一成 append-only 事件：

    run_started
    seed_loaded
    model_called
    candidate_generated
    candidate_retried
    candidate_filtered
    factor_evaluated
    population_selected
    best_updated
    artifact_frozen
    run_ended

Extension 才额外使用：

    hypothesis_proposed
    ablation_requested
    pivot_requested
    stop_requested

## 2. 通用事件

    {
      "schema_version": "0.1",
      "event_id": "evt_000123",
      "run_id": "run_xxx",
      "step": 18,
      "event_type": "factor_evaluated",
      "parent_event_ids": ["evt_000122"],
      "timestamp": "RFC3339",
      "profile": "paper_compatible_reproduction",
      "hashes": {
        "paper": "sha256:...",
        "upstream": "git:...",
        "data": "sha256:...",
        "config": "sha256:...",
        "prompt": "sha256:..."
      },
      "model": {
        "provider": "glm",
        "model_id": "glm-3.5",
        "provider_version": "..."
      },
      "usage": {
        "input_tokens": 820,
        "output_tokens": 190,
        "cumulative_tokens": 10420,
        "retry_index": 1
      },
      "payload": {}
    }

API key、认证 header、任意 secret 和非任务个人数据禁止写入。

## 3. 核心 Payload

### candidate_generated

    name
    expression
    algorithm
    seed_or_parent_ids
    generation_or_round
    raw_response_hash

### candidate_filtered

    expression_hash
    valid
    filter_stage
    error_type
    runtime_seconds
    nan_ratio

### factor_evaluated

    expression_hash
    evaluator_endpoint_role
    period_role
    ic
    rank_ic
    icir
    rank_icir
    cached

Agent-visible trajectory只能包含 period_role=search。Validation/test 事件进入 verifier_trajectory.jsonl。

### best_updated

    previous_factor_id
    new_factor_id
    paper_metric
    update_reason

### artifact_frozen

    submission_hash
    factor_ids
    config_hash
    trajectory_hash

## 4. Agent 与 Verifier 轨迹隔离

    trajectories/<run-id>/agent/trajectory.jsonl
    trajectories/<run-id>/verifier/verifier_trajectory.jsonl

Agent Runtime 无 verifier 目录权限。Verifier 只读取 frozen submission 和必要 hashes，不读取可执行的模型指令。

VerifierReport 可以引用 agent trajectory hash，但不能修改 agent trajectory。

## 5. 可直接计算的论文指标

由 normalized events 派生：

- Search Cost：每个有效 step 的 retry 数；
- Success Rate：valid candidates / total candidates；
- IC>0.03 数量；
- normalized IC gain；
- Best Update Rate；
- Diversity；
- token usage；
- 每轮/每代 best IC。

所有派生结果必须与官方原生 summary 对照；不一致时以上游输出为审计起点并调查 adapter。

## 6. Extension 指标

Extension 可以从同一 schema 计算：

- search–test selection gap；
- follow-up depth；
- duplicate rate；
- stop efficiency；
- per-prefix OOS gain；
- evaluator-call/token checkpoint curve。

这些字段不会出现在 paper-compatible 主分数中。

## 7. 最终数据价值

轨迹最终形成：

- GLM-5.3 生成合法/非法因子的样本；
- retry 与修复对；
- CoE/ToT/EA 的父代—候选—选择路径；
- search 成功但 OOS 失败的过拟合路径；
- 同一 task 在不同 evaluator-call 前缀的配对路径；
- 后续 SFT/RL 可使用的结构化研究轨迹。

训练使用必须另行确认 Qlib 数据许可、AlphaBench license、GLM API 条款和轨迹隐私。
