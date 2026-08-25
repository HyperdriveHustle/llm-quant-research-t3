# 实验协议

本文件包含全部必要实验。默认只运行 Paper Core；Extension 默认关闭并单独报告。

长时实验的任务分组、量级和执行依赖见 [LONG_RUN_PLAN](LONG_RUN_PLAN.md)；机器可读矩阵见 [long-run-matrix.yaml](long-run-matrix.yaml)。

## 共同冻结项

每次实验都保存：

    paper revision hash
    AlphaBench full commit SHA
    Qlib version
    data snapshot hash
    factor library hash
    FFO config/hash
    model provider/version
    prompt hash
    algorithm config
    random seed

## P0：环境一致性

### 目标

证明项目内 Qlib/FFO 与锁定的官方运行时一致，避免把环境差异误判为模型差异。

### 输入

- 官方 Alpha158 seeds；
- 官方合法和非法公式样例；
- 论文过滤边界样例；
- 同一公式的重复评价。

### 检查

- 官方 seed 名称、表达式、数量和 subset 一致；
- VWAP 排除；
- 字段和 operator registry 一致；
- 合法/非法判断一致；
- IC、RankIC、ICIR 与直接运行上游结果一致；
- 30 秒和 NaN>1% 过滤按论文实现；
- 相同 snapshot/config 结果可重复。

### 通过条件

所有差异均在预注册数值容差内；任何无法解释的 seed、label、period 或 metric 差异阻断 P1。

## P1：Strict T3 论文复现

### 目标

在 GLM-5.3 上运行论文 T3，同时保持官方 CoE、ToT、EA 的 loop、seed、prompt、过滤和指标。

### 算法配置

以锁定 commit 的官方 config 为准。若采用 current example 参考值：

| Algorithm | 设置 |
|---|---|
| CoE | 10 rounds；kbar + price seeds |
| ToT | 3 rounds；6 candidates/node；kbar + price seeds |
| EA | mutation 0.4；crossover 0.6；10 generations；generate 30；population 30；rolling seeds |

模型 adapter 只替换 provider，不修改论文 prompt 语义。

### 主指标

- Search Cost；
- Success Rate；
- positive IC > 0.03；
- normalized IC gain；
- CoE/ToT Fraction of Successful Runs；
- EA Best Update Rate；
- Diversity；
- token usage。

同时保存 IC、RankIC、ICIR 和所有失败候选，但不改变论文主分数。

### 基线

- 原始 seed；
- 论文搜索算法；
- GLM-5.3 各算法。

不在 strict 主表加入随机公式、null world、Agentic 或自定义 RankIC 阈值。

### 输出

保持官方原生目录：

    config
    factor_seed_metrics
    LLM logs
    per-round/backtest records
    population snapshots
    final pool
    best factor

同时旁路生成规范化 trajectory，不改变官方控制流。

## P2：独立 Verifier 重算

### 目标

防止 Agent 伪造指标、污染 cache 或利用 verifier 接口。

### 协议

Agent Runtime 完成后只传递 FrozenSubmission。Verifier Runtime：

1. 校验 artifact/config/data/upstream hash；
2. 使用 Verify FFO 重新解析公式；
3. 使用独立数据权限和 cache 重算；
4. 输出论文指标和差异；
5. 不把结果返回 Agent。

Paper profile 的 P2 主要验证计算完整性，不声称 hidden OOS 泛化。

## X1：Controlled OOS（扩展，默认关闭）

### 目的

判断 T3 在同一搜索时期发现的因子是否过拟合。

### 唯一变化

将同一 Qlib snapshot 按时间划分为 search、validation、test。Agent 只看到 search metrics；validation 可 side-evaluate 但不返回；test 只在冻结后运行。

### 指标

    selection_gap = search_metric - test_metric

报告 validation/test IC、RankIC、ICIR、方向保持率和相对 seed 差值。查看 test 后做任何修改都需要新的 test snapshot。

该结果属于 controlled_research，不写入论文复现主表。

## X2：Agentic Goal Loop（扩展，默认关闭）

### 目的

只测试“把 loop 控制权交给 GLM-5.3”是否有效。

### 控制

与 P1 保持相同：

- data snapshot；
- Alpha158 seed subset；
- DSL/operator；
- FFO；
- model/version；
-候选评价次数；
-最终提交数；
-论文指标。

唯一主要差异是 SearchRunner：模型可以选择 propose、check、evaluate、refine、compare、pivot 或 stop。Agent 仍不能访问 validation/test。

### 判读

先比较论文 search metrics，再看 X1 Verifier。Search 提升而 OOS 不变，结论是更会适应 search evaluator，不是更会泛化。

## X3：Token Budget（扩展，默认关闭）

### 问题

在模型和 evaluator 调用次数固定时，增加累计 token 是否提高 OOS utility？

### 设计

预注册 B1 < B2 < B3 < B4。各 budget 固定：

- task、data、seed、prompt、model version；
- sampling 参数；
- evaluator 调用预算；
-提交数量；
-replicate 数；
-finalization allowance。

累计逻辑 token：

    B = sum(input_tokens + output_tokens)

主要 utility：

    U(B) = test signed RankIC(candidate)
           - test signed RankIC(best seed)

边际收益：

    MarginalGain_j =
      [median U(B_j) - median U(B_(j-1))]
      / [B_j - B_(j-1)] * 1000

报告配对中位差、bootstrap 区间、胜率、selection gap、每千 token 改进和 Budget–Utility 曲线。只提高 search、不提高 test，判定为预算驱动的 selection overfitting。

## 保留的 Trajectory

每个 P/X 实验都保留：

- 原始 LLM request/response 与 token；
- 生成、retry、过滤和评价结果；
- seed/parent/candidate 关系；
- 搜索算法的选择或淘汰；
- 冻结提交；
- 独立 verifier 结果引用。

详细 schema 见 [Trajectory](../docs/TRAJECTORY.md)。

## 报告边界

最终报告固定分区：

1. Paper Reproduction；
2. Upstream/数据差异；
3. Independent Verifier；
4. Extensions。

不得用 Extension 结果覆盖或重新解释 Paper Core 主指标。
