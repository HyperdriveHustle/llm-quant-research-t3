# Configs

本目录保存不可变 run config。paper-t3.yaml 是论文兼容配置；smoke.yaml 只做低预算端到端测试，不属于论文结果。任何 Agentic、controlled OOS 或 long-horizon checkpoint 变化必须使用单独 variant_id。

配置不得包含 API key；只记录环境变量名，密钥通过运行时注入。
