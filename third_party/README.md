# Third-party Isolation

本地 Paper Runtime 锁定为 3a880599358fc81d8b3e0ec89419a7912a5dc694，位于被 Git 忽略的 AlphaBench-paper worktree。不得 import 用户机器上的其他 AlphaBench clone。

必须记录：

- upstream repository；
- full commit SHA；
- license；
- local patch list；
- Python/Qlib 依赖锁；
- 对应论文 revision。

上游当前 pyproject 声明 MIT，但仓库历史中未找到 LICENSE 文件，因此这里只做本地执行，不复制分发上游源码。Strict T3 禁用论文后新增的 Assay backend，使用锁定版本的 Qlib/FFO。

可重复 overlay 位于 ../patches；它只处理凭据、项目内数据路径、loopback、macOS spawn 与 Search FFO 路由，不改变搜索算法和指标。
