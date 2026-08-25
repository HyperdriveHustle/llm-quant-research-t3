# Source Isolation

后续代码在本目录独立实现。禁止 import 本仓库其他量化项目；外部依赖在本项目自己的依赖清单中锁定。

首版只实现薄 Harness：

- upstream_runtime：启动 pinned AlphaBench/Qlib/FFO；
- glm_adapter：协议适配，不改论文 prompt；
- paper_runner：调用官方 T3；
- artifact_freezer：冻结 config、factor 和 hashes；
- verifier：独立 runtime adapter；
- trajectory：旁路规范化官方日志。

DSL、搜索算法、IC/RankIC/ICIR 和因子库不在本项目重写。
