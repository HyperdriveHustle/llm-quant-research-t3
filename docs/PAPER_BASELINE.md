# AlphaBench T3 论文基线

本文件是首版实现的唯一行为基线。凡未在论文或锁定的官方 commit 中定义的能力，默认关闭并标记为 extension。

## 1. 权威来源与复现等级

优先级从高到低：

1. [ICLR 2026 论文 PDF](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)；
2. 锁定 full SHA 的 [AlphaBench 官方仓库](https://github.com/CityU-MLO/AlphaBench)；
3. 锁定版本的 Microsoft Qlib；
4. 本项目 adapter。

项目区分三种结论：

- paper-spec reproduction：任务语义、seed、算法和指标与论文一致；
- upstream-code reproduction：运行结果对应一个明确官方 commit；
- bitwise data reproduction：数据文件也与作者快照逐字节一致。

论文没有公开所用 Qlib 数据快照 hash，因此首版可以做到前两项；未取得作者快照前，不宣称 bitwise reproduction。

## 2. 首版固定设置

| 维度 | 论文/官方设置 | 首版决定 |
|---|---|---|
| Task | T3 Factor Searching | 保持 |
| Engine | Qlib + FFO | 保持；禁用 Assay |
| Market | CSI300 | 保持 |
| Frequency | Daily | 保持 |
| Fields | open/high/low/close/volume | 保持 |
| Paper data range | 2020–2025 | 保持语义；精确端点随 paper profile 锁定 |
| Seed library | Alpha158 | 保持 |
| Default seed window | 5 | 保持 |
| VWAP | 因数据限制排除 | 保持排除 |
| Formula language | Qlib-style DSL | 保持 |
| Search algorithms | CoE、ToT、EA | 保持 |
| Primary search signal | positive IC | 保持 |
| Effective threshold | IC > 0.03 | 保持 |

论文主文明确说明 T3 使用 Alpha158 初始池和 2020–2025 年 CSI300 成分股日频 OHLCV。[论文 §4, p.5](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)

## 3. Alpha158 Seed

论文 Appendix A.2 将 Alpha158 分成：

- 9 个 KBar 基础因子；
- 5 个 price-related 基础因子；
- 29 个 rolling time-series 基础因子；
- 42 个基础因子经 5、10、20、30、60 日窗口展开为 158 个。

论文搜索初始池使用最小窗口 5，并排除 VWAP。Pinned paper commit 中 CoE/ToT 使用 kbar + price，EA 示例使用 kbar + rolling；本实现按该 commit 的实际 loader 配置，不复制一套手写因子定义。[论文 Appendix A.2, pp.16–17](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)

## 4. 数据与 Label

Qlib 官方包内置样例只到 2020-09-25，数据审计已将其拒绝并删除。实现采用 Qlib 官方 README 当前推荐的 community release，固定为 2026-07-29：

    data/raw/qlib/releases/2026-07-29/cn_data/

不得读取用户级 ~/.qlib 或任何其他项目数据。下载后记录：

    source URL
    download time
    Qlib version
    AlphaBench full commit SHA
    per-file SHA256
    aggregate snapshot hash

发布 manifest 的 archive size 与 SHA256 在解压前强制验证；项目 snapshot manifest 记录 61,258 个文件和聚合内容 hash：

    data/snapshots/qlib-cn-manifest.json

Label 不自行实现。Pinned paper FFO 使用：

    label = close_return

该 commit 将 close_return 映射为 Ref($close, -1)/$close - 1；current FFO 的 forward_n=1 是相同的 next-day 语义。所有 run 记录 label、upstream commit 和 Qlib version。

### 必要数据审计

这些检查只验证复用是否正确，不修改论文数据：

| 检查 | 目的 | 阻断条件 |
|---|---|---|
| Grain | 确认唯一键为 date × instrument | 重复键或混合频率 |
| Coverage | 核对 2020–2025 可用日期、股票数和字段 | 大段缺期或字段缺失 |
| OHLC validity | high/low/open/close 基本关系与 volume 非负 | 大规模非法值 |
| Calendar | 核对交易日、时区和跨年边界 | label 跨错交易日 |
| Constituents | 核对 CSI300 成分是否带历史生效区间 | 仅使用当前成分回看历史 |
| Adjustment | 记录复权口径和 corporate actions | 同一代码不同运行口径变化 |
| Label alignment | 用少量样例核对 FFO forward_n=1 | 因子日与收益日错位 |
| Snapshot stability | 重复下载和 hash 对照 | 未声明的历史回写 |

当前审计已确认 calendar 覆盖 2000-01-04 至 2026-07-29，CSI300 文件含历史 membership ranges，抽样 50 个历史成分均具备 OHLCV 文件。逐值 OHLC 合法性与作者原始 adjustment 对照仍因缺少作者 snapshot 而无法完成。

## 5. 公式过滤

首版复用论文过滤规则：

- JSON/schema 合法；
- 只使用允许字段；
- 只使用 Qlib reference 中的函数；
- 参数数量正确；
- rolling window 为正整数；
- 括号平衡；
- 除法加 epsilon；
- 禁止未知函数；
- 计算时间满足论文限制；
- NaN 比例满足论文限制。

论文 Appendix A.5 说明：在 CSI300 两周样例上计算超过 30 秒的因子被过滤；两周 rolling window 中 NaN 超过 1% 的因子被过滤。[论文 Appendix A.5, pp.19–20](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)

## 6. 搜索算法设置

当前官方 example config 给出：

| Algorithm | 设置 |
|---|---|
| CoE | 10 rounds |
| ToT | 3 rounds；每个节点 6 candidates |
| EA | mutation 0.4；crossover 0.6；10 generations；每代 30；population 30 |
| Model sampling | pinned paper commit config temperature 1.0 |

本实现锁定 full SHA 3a880599358fc81d8b3e0ec89419a7912a5dc694，并以该 commit 的 config/search.yaml 和搜索器实现为准；current main 只用于差异审计。

## 7. 论文指标

Strict T3 主报告只使用论文定义：

- Search Cost：得到一个合法 search step 的重试次数，范围 1–5；
- Success Rate：通过 filtering stage 的因子数 / 生成候选数；
- Effective factor：positive IC > 0.03；
- Normalized IC Gain；
- CoE/ToT Fraction of Successful Runs；
- EA Best Update Rate；
- Diversity；
- Token usage。

IC、RankIC、ICIR 作为基础数值保留，但不使用自创 composite score 替换论文主指标。[论文 Appendix C.3, pp.32–33](https://www.cs.cityu.edu.hk/~cliu644/HomePage/doc/AlphaBench/AlphaBench_PDF.pdf)

## 8. 论文与 current main 的差异

不能把当前 main 无条件当作论文版本：

- Assay backend 在 2026-07-04 后加入；
- current FFO default period 为 2023-01-01 至 2024-01-01；
- current searcher 增加 search/validation/test 和 side validation；
- 论文主文概括 T3 使用 2020–2025 CSI300；
- 仓库没有 release/tag 明确声明论文结果对应 commit。
- current FFO 默认时期、current Backtester 默认时期与论文主文时期并不相同；
- current example 文档描述的 seed subset 与 current pipeline 实际 loader 需要在锁定 commit 后以运行产物核对，不能只信注释。

因此每个 run 必须选择：

    profile = paper_compatible_reproduction
    upstream_full_sha = 3a880599358fc81d8b3e0ec89419a7912a5dc694
    data_release_tag = 2026-07-29
    data_snapshot_hash = 0ab5ab8b...

由于作者 snapshot hash 未公开，config 强制 paper_result=false。任何 unresolved 项保留为 unresolved，不自行补成“论文设置”。

对严格复现影响最大的风险是：

| 风险 | 严重度 | 当前结论 |
|---|---|---|
| 缺少论文数据 snapshot hash | High | 能复用管线，不能保证逐字节相同 |
| 未标记论文 commit | High | 必须先锁定并记录 full SHA |
| 日期默认值不一致 | High | 禁止依赖隐式默认值 |
| Label 路径可能混淆 | High | 只调用锁定 FFO，不手写 label |
| 历史成分/PIT 未实测 | High | 数据审计通过前不下泛化结论 |
| 数据再分发许可未确认 | Medium | 数据不提交 Git，不对外打包 |

## 9. 默认关闭的扩展

以下不是论文原始 T3，首版默认关闭：

- 模型自主控制整个 Agent Loop；
- hidden OOS split；
- token-budget scaling；
- null world；
- 主动 ablation、pivot、stop；
- 自定义 RankIC 提升阈值；
- 多重检验修正；
- process-level trajectory score。

扩展可以复用同一数据和 evaluator，但必须使用不同 variant_id，不能写入 strict_t3 主表。
