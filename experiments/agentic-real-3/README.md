# GLM-5.3 三任务真实 Agent Loop 实验

本实验用于评估 GLM-5.3 作为量化研究员时的长程研究能力，而不是复现论文排行榜。三项任务共享同一套 pinned AlphaBench/Qlib/CSI300/Alpha158/FFO 环境、同一模型与采样温度，只改变研究目标、时间切分和任务难度。任务串行后台运行，避免模型 API、Qlib 内存和本地端口相互争抢；Verifier 在每个 Agent episode 冻结并退出后独立启动，隐藏 OOS 结果不回流。

| 任务 | 真实目标 | 搜索期 / 隐藏 OOS | 安全评价上限 | 成功判定重点 |
|---|---|---|---:|---|
| T1 Cross-regime trend | 找到跨阶段稳定的趋势或动量因子 | 2018–2023 / 2024–2025 | 48 | early、late、full 均为正，full IC≥0.03、超过 seed，OOS IC≥0.01 |
| T2 Liquidity reversal | 找到具有价格、区间或相对成交量机制的反转因子 | 2015–2020 / 2021–2023 | 48 | 三窗口稳定、full IC≥0.025、超过 seed，并通过 OOS |
| T3 Diverse pool | 找到两个不同机制且互补的因子 | 2017–2022 / 2023–2025 | 64 | 两个不同 hypothesis，三窗口与 OOS 均有效，OOS 平均绝对相关≤0.70 |

这些阈值是预注册的实验 gate。模型正常停止仍由模型决定；若它提交不完整证据，离线 objective assessor 会判为未达成，而不会事后修改 trajectory。`emergency_model_turns=null` 表示不设置实验性模型调用或 token 总预算；factor-evaluation ceiling 只是防止失控的操作安全边界。

每个 run 的 `ledger.jsonl` 记录模型 action、无效修复、假设、父子因子、每次 FFO 结果、累计 model calls/tokens 和 checkpoints。任务完成后生成独立 analysis JSON，其中包括模型轮次、动作分布、候选与假设数量、总 tokens、Agent 耗时、模型延迟统计、逐次评价的 best-IC 优化曲线、checkpoint 状态、Verifier 结果和预注册目标是否达成。Suite status 在任务运行中可动态读取 ledger，显示当前轮次、评价数、tokens、耗时和最后事件。

启动与查看状态：

    ./.venv/bin/qharness start-suite \
      --suite experiments/agentic-real-3/suite.yaml

    ./.venv/bin/qharness suite-status \
      --suite-run-dir runs/suites/<suite-run-id>

后台日志位于 `runs/suites/<suite-run-id>/suite.log`；每项任务完成后生成 `<task-id>-analysis.json`，全部完成后生成 `suite-summary.json`。运行数据、模型日志、submission 与 verifier report 均保持在 Git ignored 的运行目录中，配置、任务定义、代码和测试进入版本管理。
