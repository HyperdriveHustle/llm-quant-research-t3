# Data Isolation

本目录只存放本项目的数据。禁止读取仓库内其他量化数据目录。Strict T3 复用 AlphaBench 的 Qlib/CSI300 数据语义，但数据固定在本项目，而不是用户级 ~/.qlib。

- raw：固定 community release 2026-07-29 的 archive、publisher manifest 和解压数据。
- snapshots：实验使用的不可变快照；每个 TaskManifest 只引用 snapshot hash。

下载器验证 archive size 与 SHA256，拒绝截断文件和不安全 tar member。Strict profile 不建立自定义清洗或 feature pipeline。

Search、validation 和 test 使用权限隔离，而不只是不同文件名。Search FFO 只能读取 search period；Verify FFO 读取 validation/test，使用独立 cache，并不得把指标写回 Agent Runtime。

论文主文称 T3 使用 2020–2025 CSI300 日频 OHLCV，但没有提供数据快照 hash。当前数据覆盖 2000-01-04 至 2026-07-29；项目只能声称 paper-compatible data pipeline，不能声称 bitwise-identical reproduction。
