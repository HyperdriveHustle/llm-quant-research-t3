# Quant Agent Session Viewer

本地、只读、无前端构建依赖的单任务轨迹查看器。界面参考 `life-os/60-tools/session-viewer`，数据源适配本项目的 Agent ledger 与 model-call logs。

## 启动

```bash
cd /Users/huxiaohui/workspace/code/vibe_coding/life-os/llm-quant-research-t3
python3 tools/session-viewer/server.py \
  --run-id run_glm53-real-agentic-3_20260826_211645_0afc7a_t1-trend
```

然后打开 [http://127.0.0.1:8876](http://127.0.0.1:8876)。

## 界面内容

- 左侧按 ledger sequence 浏览 bootstrap、action、evaluate、checkpoint、invalid 与 incomplete 事件；
- 模型输入按 `system instructions + Projected ResearchState` 原样显示；
- 展示模型原始 response text、token、耗时、完成状态和 content block 类型；
- 展示 schema 后的 action、Harness observation、错误与 IC/RankIC/ICIR；
- 正在运行的任务每 5 秒自动刷新；
- 所有敏感名称字段由 server 端过滤，服务默认仅绑定 `127.0.0.1`。

## 验证

```bash
python3 -m unittest discover -s tools/session-viewer/tests -v
node --check tools/session-viewer/static/app.js
```
