"use strict";

const state = {
  index: null,
  sequence: null,
  payload: null,
  filter: "all",
  tab: "interaction",
  loading: false,
};

const $ = (id) => document.getElementById(id);
const elements = {
  list: $("event-list"),
  count: $("event-count"),
  refresh: $("refresh-state"),
  runTitle: $("run-title"),
  runSubtitle: $("run-subtitle"),
  stats: $("stats"),
  eventTitle: $("event-title"),
  eventSubtitle: $("event-subtitle"),
  eventBadge: $("event-badge"),
  stage: $("stage"),
  previous: $("previous-event"),
  next: $("next-event"),
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function formatTime(epoch) {
  if (!epoch) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(Number(epoch) * 1000));
}

function pretty(value) {
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch (_error) {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

function eventVisible(event) {
  if (state.filter === "all") return true;
  if (state.filter === "model") return Boolean(event.has_model_call);
  if (state.filter === "evaluate") return event.event_type === "evaluate";
  if (state.filter === "error") {
    return ["invalid_action", "model_output_incomplete", "forced_stop"].includes(event.event_type);
  }
  return true;
}

function visibleEvents() {
  return (state.index?.events || []).filter(eventVisible);
}

function renderIndex() {
  const index = state.index;
  elements.runTitle.textContent = index.run_id;
  elements.runSubtitle.textContent = index.ledger_path;
  elements.count.textContent = `${visibleEvents().length} / ${index.event_count} 个事件`;
  elements.list.replaceChildren();
  for (const event of visibleEvents()) {
    const button = node("button", "event-item" + (event.sequence === state.sequence ? " active" : ""));
    button.type = "button";
    button.dataset.sequence = event.sequence;
    const top = node("div", "event-item-top");
    top.append(node("span", "sequence", `#${event.sequence}`));
    top.append(node("span", `kind kind-${event.event_type}`, event.event_type));
    const title = event.action || event.event_type;
    const middle = node("strong", "event-item-title", title);
    const bottom = node("div", "event-item-bottom");
    bottom.append(node("span", "", formatTime(event.timestamp)));
    const usage = event.logical_tokens ? `${formatNumber(event.logical_tokens)} tok` : "";
    bottom.append(node("span", "", usage));
    button.append(top, middle, bottom);
    button.addEventListener("click", () => selectEvent(event.sequence));
    elements.list.appendChild(button);
  }
  renderStats();
  renderNavigation();
}

function renderStats() {
  const index = state.index;
  const rows = [
    ["状态", index.terminal_event || "running"],
    ["事件", index.event_count],
    ["模型调用", index.model_calls],
    ["Tokens", formatNumber(index.logical_tokens)],
    ["因子评价", index.factor_evaluations],
    ["Invalid", index.invalid_actions],
    ["Incomplete", index.incomplete_outputs],
  ];
  elements.stats.replaceChildren(...rows.map(([label, value]) => {
    const chip = node("div", "stat");
    chip.append(node("span", "stat-label", label), node("strong", "", value));
    return chip;
  }));
}

async function selectEvent(sequence) {
  state.sequence = Number(sequence);
  renderIndex();
  elements.stage.innerHTML = '<div class="empty">正在读取事件…</div>';
  try {
    const response = await fetch(`/api/event?sequence=${encodeURIComponent(sequence)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.payload = await response.json();
    renderEvent();
  } catch (error) {
    elements.stage.replaceChildren(node("div", "error", `读取失败：${error.message}`));
  }
}

function renderEvent() {
  const payload = state.payload;
  const event = payload.event;
  const action = payload.model_action?.action || event.event_type;
  elements.eventTitle.textContent = action;
  elements.eventSubtitle.textContent = `sequence ${event.sequence} · state v${event.state_version} · ${formatTime(event.timestamp)}`;
  elements.eventBadge.textContent = event.event_type;
  elements.eventBadge.className = `event-badge kind-${event.event_type}`;
  if (state.tab === "raw") renderRaw(payload);
  else if (state.tab === "state") renderState(payload);
  else renderInteraction(payload);
  renderNavigation();
}

function panel(title, subtitle, content, options = {}) {
  const section = node("section", "panel " + (options.className || ""));
  const header = node("div", "panel-header");
  const heading = node("div");
  heading.append(node("h3", "", title), node("p", "", subtitle));
  header.appendChild(heading);
  section.append(header, content);
  return section;
}

function codeBlock(value, className = "") {
  const pre = node("pre", `code-block ${className}`);
  const code = node("code", "", pretty(value));
  pre.appendChild(code);
  return pre;
}

function detailsBlock(summary, value, open = false) {
  const details = node("details", "details-block");
  details.open = open;
  details.append(node("summary", "", summary), codeBlock(value));
  return details;
}

function renderInteraction(payload) {
  const container = node("div", "interaction");
  if (payload.messages.length) {
    const system = payload.messages.find((message) => message.role === "system");
    const user = payload.messages.find((message) => message.role === "user");
    const assistant = payload.messages.find((message) => message.role === "assistant");
    const input = node("div", "panel-body stack");
    input.append(detailsBlock("System instructions", system?.content || "—"));
    input.append(detailsBlock("Projected ResearchState", user?.content || "—", false));
    container.appendChild(panel("模型输入", "instructions + 单轮状态投影", input));

    const responseBody = node("div", "panel-body stack");
    responseBody.append(codeBlock(assistant?.content || "", "response-code"));
    if (payload.model_call) responseBody.append(detailsBlock("调用元数据", compactModelMetadata(payload.model_call)));
    container.appendChild(panel("模型输出", "原始 response text", responseBody, { className: "assistant-panel" }));
  } else {
    container.appendChild(panel("系统事件", "该事件没有关联的模型调用", codeBlock(payload.event)));
  }

  const actionBody = node("div", "panel-body stack");
  actionBody.append(codeBlock(payload.model_action || payload.event.payload?.raw_model_output || "—"));
  container.appendChild(panel("解析后的 Action", "通过 schema 后写入 ledger 的动作", actionBody));

  const harnessBody = node("div", "panel-body stack");
  if (payload.errors.length) harnessBody.append(errorList(payload.errors));
  if (payload.experiments.length) harnessBody.append(experimentTable(payload.experiments));
  harnessBody.append(detailsBlock("完整 Harness observation", payload.harness_observation || {}));
  container.appendChild(panel("Harness 返回", "校验、工具执行、指标与状态变化", harnessBody, { className: "harness-panel" }));
  elements.stage.replaceChildren(container);
}

function renderState(payload) {
  const user = payload.messages.find((message) => message.role === "user");
  const content = user ? user.content : { message: "该事件没有模型 State 输入" };
  elements.stage.replaceChildren(panel("Projected ResearchState", "本轮模型实际看到的单一 user input", codeBlock(content)));
}

function renderRaw(payload) {
  elements.stage.replaceChildren(panel("原始事件数据", "敏感字段已在 server 端过滤", codeBlock(payload)));
}

function compactModelMetadata(call) {
  const keys = [
    "model", "api_mode", "response_id", "input_tokens", "output_tokens",
    "elapsed_seconds", "attempt", "status", "incomplete_reason",
    "requested_max_output_tokens", "thinking_type", "structured_output",
    "output_item_types", "content_block_types", "_file",
  ];
  return Object.fromEntries(keys.filter((key) => key in call).map((key) => [key, call[key]]));
}

function errorList(errors) {
  const box = node("div", "error-list");
  for (const error of errors) {
    const item = node("div", "error-item");
    item.append(node("strong", "", error.code || "ERROR"), node("span", "", error.message || pretty(error)));
    box.appendChild(item);
  }
  return box;
}

function experimentTable(experiments) {
  const wrap = node("div", "table-wrap");
  const table = node("table", "metric-table");
  const head = node("thead");
  const headRow = node("tr");
  ["Factor", "Window", "IC", "RankIC", "ICIR", "状态"].forEach((label) => headRow.appendChild(node("th", "", label)));
  head.appendChild(headRow);
  const body = node("tbody");
  for (const experiment of experiments) {
    const row = node("tr");
    const metrics = experiment.metrics || {};
    [
      experiment.factor_id,
      experiment.window_alias,
      metric(metrics.ic),
      metric(metrics.rank_ic),
      metric(metrics.icir),
      experiment.success ? "success" : "failed",
    ].forEach((value) => row.appendChild(node("td", "", value)));
    body.appendChild(row);
  }
  table.append(head, body);
  wrap.appendChild(table);
  return wrap;
}

function metric(value) {
  return value === undefined || value === null ? "—" : Number(value).toFixed(5);
}

function renderNavigation() {
  const events = visibleEvents();
  const index = events.findIndex((event) => event.sequence === state.sequence);
  elements.previous.disabled = index <= 0;
  elements.next.disabled = index < 0 || index >= events.length - 1;
}

function move(delta) {
  const events = visibleEvents();
  const index = events.findIndex((event) => event.sequence === state.sequence);
  const target = events[index + delta];
  if (target) selectEvent(target.sequence);
}

async function loadIndex({ selectLatest = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  try {
    const response = await fetch("/api/index", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const previousCount = state.index?.event_count || 0;
    state.index = await response.json();
    const events = visibleEvents();
    if (state.sequence === null && events.length) state.sequence = events.at(-1).sequence;
    if (selectLatest && state.index.event_count > previousCount && events.length) state.sequence = events.at(-1).sequence;
    renderIndex();
    if (state.sequence !== null) await selectEvent(state.sequence);
    elements.refresh.textContent = `已刷新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  } catch (error) {
    elements.refresh.textContent = `刷新失败：${error.message}`;
  } finally {
    state.loading = false;
  }
}

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
    const events = visibleEvents();
    if (!events.some((event) => event.sequence === state.sequence)) state.sequence = events.at(-1)?.sequence || null;
    renderIndex();
    if (state.sequence !== null) selectEvent(state.sequence);
  });
});

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    document.querySelectorAll("[data-tab]").forEach((item) => item.classList.toggle("active", item === button));
    if (state.payload) renderEvent();
  });
});

$("refresh-button").addEventListener("click", () => loadIndex({ selectLatest: true }));
elements.previous.addEventListener("click", () => move(-1));
elements.next.addEventListener("click", () => move(1));
window.addEventListener("keydown", (event) => {
  if (event.altKey && event.key === "ArrowUp") move(-1);
  if (event.altKey && event.key === "ArrowDown") move(1);
});

loadIndex({ selectLatest: true });
window.setInterval(() => loadIndex({ selectLatest: false }), 5000);
