# Harness 架构

## 1. 设计原则

Harness 是论文环境的薄封装，不重写 AlphaBench 的因子引擎或指标。v0.2 职责是：

1. 锁定并启动官方 AlphaBench/Qlib/FFO；
2. 适配 GLM-5.3；
3. 固化配置、数据和输出；
4. 隔离 Agent Runtime 与 Verifier Runtime；
5. 记录可审计 trajectory；
6. 运行论文指标；
7. 在 extension profile 中执行模型自主 action loop 与隐藏 OOS 验证。

可扩展性来自稳定接口，不来自首版增加更多功能。

## 2. 运行边界

    ┌──────────────── Agent Runtime ────────────────┐
    │ GLM Adapter → PaperRunner / AgenticRunner → Search FFO │
    │                         ↓                       │
    │              search-period Qlib snapshot       │
    │              search-only cache/credential      │
    └───────────────────┬─────────────────────────────┘
                        │
                Frozen Artifact Channel
                        │
                        ▼
    ┌─────────────── Verifier Runtime ───────────────┐
    │ Deterministic Verifier → Verify FFO             │
    │                          ↓                      │
    │          paper period or val/test snapshot      │
    │          verifier-only cache/credential         │
    └─────────────────────────────────────────────────┘

Verifier 不运行 GLM，不接受研究动作。Agent 不持有 verifier endpoint、数据路径或凭据。

## 3. 必要组件

### UpstreamRuntime

管理只读 AlphaBench full SHA、Qlib version、依赖锁和本地 patch。Strict profile 直接调用官方 T3 entrypoint 与 FFO，不复制算法。

### GLMModelAdapter

唯一模型接口：

    generate(messages, temperature, max_tokens) -> ModelResponse

如果 GLM API 兼容 OpenAI Chat Completions，只映射 base_url、API key 和 model name；否则做协议转换。Adapter 不修改论文 prompt 内容，只处理请求/响应格式、重试错误和 token 统计。

### SearchRunner

接口：

    run(task_config, model_adapter, trajectory_sink) -> FrozenSubmission

Paper 实现是 `PaperRunner`；v0.2 实现是 `AgenticSearchRunner`。后者不复写 Qlib、Alpha158 或 FFO，只把 loop control 交给模型。

### FactorEvaluator

稳定抽象：

    check(expression) -> CheckResult
    evaluate(expression, period) -> FactorResult
    evaluate_batch(expressions, period) -> list[FactorResult]

Strict 实现只是 AlphaBench FFO client adapter。Harness 不重新计算 IC、RankIC 或 ICIR。

### ArtifactFreezer

冻结：

    expression
    name/direction
    seed/parent references
    algorithm/config
        upstream/data/config/Harness-source/ledger hashes
    search metrics
    trajectory hash

冻结后生成 immutable submission hash。Verifier 只接受具有有效 hash 的 artifact。

### Verifier

接口：

    verify(frozen_submission, verifier_config) -> VerifierReport

Verifier 重新调用自己的 Verify FFO，不能信任 Agent 提交的指标。Paper profile 可在论文时期复算论文分数；controlled extension 才读取 validation/test。

### TrajectorySink

同时保存官方原生输出和规范化事件流。写入是 append-only；Agent 不能删除或覆盖失败记录。

## 4. Hack 防护硬约束

Agent 与 Verifier 即使使用同一只读 code image，也不得共享：

- 进程、容器或 OS user；
- HTTP endpoint；
- data path 权限；
- SQLite/pickle cache；
- config 和环境变量；
- service credential；
- 可写 artifact 目录；
- 模型上下文。

Artifact channel 只允许预定义 JSON schema，不接受任意路径、代码、URL 或命令。Verifier 在无外网、无 GLM key、只读数据环境运行。

Verifier 结果单向写入报告目录，不返回当前 episode。若根据 verifier 结果修改 prompt、公式、算法或预算，该数据不再具有 final-test 身份。

## 5. 数据与 Cache

项目内保持三类路径：

    data/raw/qlib/             官方下载
    data/snapshots/            冻结数据版本
    runs/<run-id>/search-cache Agent 搜索 cache
    runs/<run-id>/verify-cache Verifier cache

Search 与 Verify cache key 都必须包含：

    normalized expression
    market/universe
    period
    label
    forward_n
    data snapshot hash
    evaluator version

即使相同表达式已经在 search cache 中存在，Verifier 也从自己的 cache/engine 重新解析或读取 verifier-only cache。

## 6. Profile

### paper_compatible_reproduction（默认）

- 官方 CoE/ToT/EA 控制 loop；
- Qlib/FFO；
- Alpha158；
- CSI300 daily OHLCV；
- 论文过滤和指标；
- Agent 只做论文要求的候选生成/变异/交叉；
- 不启用自定义 tools、hidden split 或 token budget controller。

### controlled_research（关闭）

- 保持同一数据语义、seed、DSL 和 evaluator；
- 独立 search/validation/test；
- validation/test 不可见；
- 用于过拟合分析。

### agentic_goal_loop（v0.2 已实现）

- 只替换 SearchRunner；
- 模型自主选择 propose / evaluate / refine / pivot / stop；
- ToolGateway 只接受注册 ID、Qlib 公式和预注册 search window alias；
- Alpha158 seeds、Qlib/FFO、FrozenSubmission 与独立 Verifier 保持复用；
- `no_discovery` 与 `submit` 都是合法终态。

### long_horizon_checkpoints（v0.2 基础能力已实现）

- 研究配置可以把 `emergency_model_turns` 设为 `null`，不设置实验性 model-call/token 总预算；
- 因子评价仍有安全上限，达到上限后模型只能执行 stop；
- 在预注册 evaluator-call 阈值首次到达或越过时保存 best-so-far、累计 token、分支宽度/深度与状态 hash；
- 隐藏 OOS 只在 Agent 终止并冻结后运行，结果不回流当前 episode。

## 7. 目录和依赖隔离

    third_party/        pinned AlphaBench
    data/               project-local Qlib data
    configs/            immutable run configs
    src/                adapters and harness only
    tests/              contract/conformance tests
    runs/               runtime output
    trajectories/       normalized event streams
    artifacts/          frozen submissions/reports

首版 src 不允许 import 本仓库其他项目。所有外部依赖由本项目独立锁定。
