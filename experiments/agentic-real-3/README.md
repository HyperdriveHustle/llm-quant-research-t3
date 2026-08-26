# GLM-5.3 三任务真实 Agent Loop 实验

本实验用于评估 GLM-5.3 作为量化研究员时的长程研究能力，而不是复现论文排行榜。三项任务共享同一套 pinned AlphaBench/Qlib/CSI300/Alpha158/FFO 环境、同一模型、采样温度和时间切分，只改变研究目标与任务难度。三个隔离子进程并行运行，各自使用不同端口和 cache；Verifier 在对应 Agent episode 冻结并退出后独立启动，隐藏 OOS 结果不回流。

| 任务 | 真实目标 | 搜索期 / 隐藏 OOS | 安全评价上限 | 成功判定重点 |
|---|---|---|---:|---|
| T1 Cross-regime trend | 找到跨阶段稳定的趋势或动量因子 | 2020–2023 / 2024–2025 | 48 | early、late、full 均为正，full IC≥0.03、超过 seed，OOS IC≥0.01 |
| T2 Liquidity reversal | 找到具有价格、区间或相对成交量机制的反转因子 | 2020–2023 / 2024–2025 | 48 | 三窗口稳定、full IC≥0.025、超过 seed，并通过 OOS |
| T3 Diverse pool | 找到两个不同机制且互补的因子 | 2020–2023 / 2024–2025 | 64 | 两个不同 hypothesis，三窗口与 OOS 均有效，OOS 平均绝对相关≤0.70 |

这些阈值是预注册的实验 gate。模型正常停止仍由模型决定；若它提交不完整证据，离线 objective assessor 会判为未达成，而不会事后修改 trajectory。`emergency_model_turns=null` 表示不设置实验性模型调用或 token 总预算；factor-evaluation ceiling 与连续候选注册失败熔断只是防止失控的操作安全边界。正式任务继续使用论文的严格 1% NaN gate，但把 check period 扩展到共同的 2020–2023，启动前必须通过 5/20/60 日代表性 rolling-factor preflight。

每个 run 的 `ledger.jsonl` 记录模型 action、无效修复、假设、父子因子、每次 FFO 结果、累计 model calls/tokens 和 checkpoints。任务完成后生成独立 analysis JSON，其中包括模型轮次、动作分布、候选与假设数量、总 tokens、Agent 耗时、模型延迟统计、逐次评价的 best-IC 优化曲线、checkpoint 状态、Verifier 结果和预注册目标是否达成。Suite status 在任务运行中可动态读取 ledger，显示当前轮次、评价数、tokens、耗时和最后事件。

启动与查看状态：

    ./.venv/bin/qharness agentic-preflight \
      --config configs/real-t1-trend.yaml

    ./.venv/bin/qharness start-suite \
      --suite experiments/agentic-real-3/suite.yaml

    ./.venv/bin/qharness suite-status \
      --suite-run-dir runs/suites/<suite-run-id>

后台日志位于 `runs/suites/<suite-run-id>/suite.log`；每项任务完成后生成 `<task-id>-analysis.json`，全部完成后生成 `suite-summary.json`。运行数据、模型日志、submission 与 verifier report 均保持在 Git ignored 的运行目录中，配置、任务定义、代码和测试进入版本管理。

## Pilot 与重设计记录

首个串行 pilot `glm53-real-agentic-3_20260826_103650_ef9b8c` 在 T1 运行 16 个模型回合、消耗 362,663 logical tokens，只完成 5 个 seed 评价。两个月 check period 使 24 个合法 rolling 候选因 `3.74%–5.04%` NaN 被严格 1% gate 拒绝，模型无法注册非 seed 因子。该 pilot 已保留并标记 `aborted_for_redesign`。

重设计没有放宽正式 gate：三个任务统一到论文公开范围内的 `2020–2023 search / 2024–2025 hidden OOS`，check period 扩展为完整搜索期。严格 1% policy 下的 5/20/60 日代表性 preflight 实测 NaN 为 `0.09%–0.15%`，三项配置全部通过。另增加候选注册停滞熔断，避免合法 action 持续产生零候选；执行方式改为三个端口/cache/进程隔离的并行任务。
