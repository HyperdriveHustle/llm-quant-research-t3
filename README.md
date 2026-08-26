# LLM Quant Research T3

这是一个全新、独立的 AlphaBench T3 Harness。项目不依赖本仓库已有的量化代码或数据；Qlib 数据、pinned upstream、配置、运行记录、trajectory 和评测产物均在本目录隔离。

v0.1 回答：在 AlphaBench T3 的 seed、搜索算法、过滤和指标下，GLM-5.3 的因子搜索表现如何。v0.2 新增独立的 `agentic_goal_loop` profile：模型自主决定 propose / evaluate / refine / pivot / stop，Harness 只负责协议、工具执行、账本、安全边界和冻结。

论文 profile 继续保持 Qlib/FFO、CSI300 日频 OHLCV、Alpha158 seed、CoE/ToT/EA、论文过滤规则和论文搜索指标。Agentic Goal Loop、long-horizon checkpoints 和隐藏 OOS 诊断是单独的 extension profile，不进入 strict_t3 主分数。

参考基线：

- [AlphaBench 官方论文](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)
- [AlphaBench 官方仓库](https://github.com/CityU-MLO/AlphaBench)

## 项目边界

    llm-quant-research-t3/
    ├── configs/          任务、模型、工具和实验配置
    ├── data/             本项目独占的数据快照
    │   ├── raw/          原始下载文件，只读
    │   └── snapshots/    实验冻结快照
    ├── docs/
    │   ├── PAPER_BASELINE.md   论文基线与数据复用
    │   ├── HARNESS.md          Harness、接口与隔离
    │   └── TRAJECTORY.md       轨迹协议
    ├── experiments/
    │   └── README.md           完整实验协议
    ├── third_party/      锁定的 AlphaBench/FFO 上游代码或容器说明
    ├── patches/          论文期 upstream 的最小安全/兼容 overlay
    ├── src/              独立 Harness
    ├── tests/            环境、工具和 verifier 测试
    ├── runs/             单次运行目录，不提交 Git
    ├── trajectories/     模型逐事件轨迹，不提交 Git
    └── artifacts/        冻结因子、Factor Card 和报告

## 总体实验流程

    Pinned AlphaBench + Qlib Snapshot + Alpha158 Seeds
                        ↓
             Official CoE / ToT / EA Loop
                  或 AgenticSearchRunner
                        ↓
                 GLM-5.3 Candidates
                        ↓
             Official Filter + Search FFO
                        ↓
                 Frozen T3 Submission
                        ↓
        Independent Verifier（结果不回流 Agent）

## 设计文档

| 文档 | 作用 |
|---|---|
| [论文基线](docs/PAPER_BASELINE.md) | 数据、seed、算法、指标、上游版本与扩展边界 |
| [Harness](docs/HARNESS.md) | 组件、接口、Agent/Verifier 隔离和扩展 profile |
| [实验协议](experiments/README.md) | Paper Core、独立验证和关闭的扩展实验 |
| [长时实验分组](experiments/LONG_RUN_PLAN.md) | CoT/ToT/EA、OOS、深度研究、Null 与 Agent Loop |
| [三任务真实 Agent Suite](experiments/agentic-real-3/README.md) | 三个 GLM-5.3 长程任务、成功 gate、后台运行和过程统计 |
| [Trajectory](docs/TRAJECTORY.md) | 上游原生输出、事件流和派生数据 |
| [Agentic Loop 设计](docs/AGENTIC_LOOP_DESIGN.md) | 模型自主 propose/evaluate/refine/pivot/stop 的 v0.2 设计 |

## 项目不变量

- Verifier 数据和结果永不暴露给当前 Agent episode。
- strict_t3 先复用论文 Qlib/FFO、Alpha158、CSI300、OHLCV 和论文指标。
- Agent Runtime 与 Verifier Runtime 使用独立进程、数据权限、endpoint 和 cache。
- 长程任务不限制模型调用；所有尝试和 prefix checkpoints 必须完整记录。
- 因子预测指标与组合收益指标分层报告；Sharpe 不是原始 T3 的唯一目标。
- 失败实验和被拒绝候选同样进入账本。
- 本目录只定义实验流程和依赖，不替用户制定项目时间规划。

## 已实现

- 锁定 AlphaBench paper runtime commit 3a880599；
- Ark Coding Responses API / GLM-5.3 adapter；
- Qlib 0.9.7 与固定 community data release 2026-07-29；
- archive size/SHA256 校验、safe extraction、snapshot manifest 和数据审计；
- 原始 Alpha158、CoE/ToT/EA 与 FFO adapter；
- Search FFO 与 Verify FFO 双进程、双端口、双 cache、无共享模型凭据；
- immutable FrozenSubmission 与 config/data/upstream hash gate；
- 原生 upstream logs + normalized agent/verifier trajectory；
- 论文 IC threshold、retry/success、update 和 diversity 报告；
- 单元、集成、静态检查和真实端到端 smoke；
- v0.2 model-controlled action loop、确定性 StateProjector、hash-chained ResearchLedger；
- Search 证据复算、隐藏 OOS、seed-relative delta 与 generalization diagnostics；
- config/data/upstream/Harness source/ledger 五层输入与轨迹指纹。

## 使用

    python3 -m venv .venv
    ./.venv/bin/pip install -e '.[paper,dev]'

    # 本地密钥：复制 .env.example 为 .env；.env 已被 Git 忽略
    ./.venv/bin/qharness patch-upstream --config configs/smoke.yaml
    ./.venv/bin/qharness download-data --config configs/smoke.yaml
    ./.venv/bin/qharness snapshot-data --config configs/smoke.yaml
    ./.venv/bin/qharness audit-data --config configs/smoke.yaml
    ./.venv/bin/qharness doctor --config configs/smoke.yaml --require-data
    ./.venv/bin/qharness model-smoke --config configs/smoke.yaml
    ./.venv/bin/qharness run --config configs/smoke.yaml

    # v0.2 自主研究 smoke：搜索期 2023Q1，隐藏 OOS 2023Q2
    ./.venv/bin/qharness doctor --config configs/agentic-smoke.yaml --require-data
    ./.venv/bin/qharness run --config configs/agentic-smoke.yaml

    # 串行后台启动三个真实长程 Agent Loop
    ./.venv/bin/qharness start-suite \
      --suite experiments/agentic-real-3/suite.yaml

    ./.venv/bin/qharness suite-status \
      --suite-run-dir runs/suites/<suite-run-id>

论文兼容参数使用：

    ./.venv/bin/qharness run --config configs/paper-t3.yaml

paper-t3.yaml 使用论文语义和 pinned code，但作者未发布原始 data snapshot hash，因此 paper_result=false；输出应称为 paper-compatible reproduction，不能称为逐字节论文复现。

## 验证

    ./.venv/bin/ruff check src tests
    ./.venv/bin/pytest
    ./.venv/bin/pytest --cov=quant_harness --cov-report=term-missing

[实现 Checklist](CHECKLIST.md) · [最终 Review](docs/IMPLEMENTATION_REVIEW.md)
