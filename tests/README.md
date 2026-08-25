# Tests

测试只覆盖 Harness 边界：

- 项目内数据路径和 snapshot hash；
- 官方 seed/config 是否按锁定 commit 加载；
- FFO adapter 与官方直接调用结果一致；
- FrozenSubmission hash；
- Agent/Verifier endpoint、cache 和权限隔离；
- trajectory 与官方原生日志一致。

不为 Qlib/FFO 重写一套平行指标实现。
