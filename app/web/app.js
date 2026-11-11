"use strict";
// 大肥鱼 QQ 助手 · Xean 版本。原生 JavaScript 界面。

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  const opt = { headers: { "X-Token": window.TOKEN }, signal: controller.signal };
  if (body !== undefined) {
    opt.method = "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  try {
    const r = await fetch(path, opt);
    const data = await r.json();
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("invalid response");
    if (!r.ok) return { ...data, ok: false, message: data.message || `请求失败（${r.status}），请重试。` };
    return data;
  } catch (e) {
    return { ok: false, message: e.name === "AbortError" ? "请求超时，请稍后重试。" : "无法连接本地服务，请确认应用仍在运行后重试。" };
  } finally {
    clearTimeout(timeout);
  }
}

async function heartbeat() { await api("/api/ping", {}); setTimeout(heartbeat, 3000); }
heartbeat();

const S = { page: 0, info: null, progress: null, timers: [], epoch: 0 };

function clearTimers() {
  S.timers.forEach(clearTimeout);
  S.timers = [];
}

function later(task, delay) {
  const epoch = S.epoch;
  S.timers.push(setTimeout(() => { if (epoch === S.epoch) task(); }, delay));
}

// Each rendered page owns its requests and polling. Late replies cannot change a new page.
async function pageRequest(path, body, epoch = S.epoch) {
  const r = await api(path, body);
  return epoch === S.epoch ? r : null;
}

function poll(task, delay = 1500) {
  const epoch = S.epoch;
  let timer;
  const tick = async () => {
    if (epoch !== S.epoch) return;
    try { await task(epoch); }
    catch { if (epoch === S.epoch) showError("暂时无法更新，请稍后重试。"); }
    if (epoch !== S.epoch) return;
    S.timers = S.timers.filter(id => id !== timer);
    timer = setTimeout(tick, delay);
    S.timers.push(timer);
  };
  tick();
}

function showError(message, id = "#msg") {
  const el = $(id);
  if (el) el.textContent = message || "操作失败，请重试。";
}

function features() {
  return { voice: !!S.info?.features?.voice, memory: !!S.info?.features?.memory };
}

async function reloadInfo(epoch = S.epoch) {
  const info = await pageRequest("/api/info", undefined, epoch);
  if (!info) return false;
  if (info.ok === false || !info.mode) { showError(info.message); return false; }
  S.info = info;
  return true;
}

function shell(page, title, sub, bodyHtml, footHtml) {
  clearTimers();
  S.epoch++;
  document.body.classList.add("ocean-page");
  if (page === 0) {
    $("#app").innerHTML = `
      <div class="ocean-shell">
        <header class="ocean-header"><div class="ocean-brand"><span class="ocean-mark">≈</span> 大肥鱼 QQ 助手</div><span class="brand-owner">作者：Xean</span></header>
        <ol class="ocean-steps" aria-label="安装步骤">${["安装位置", "连接服务", "个性设置", "安装程序", "扫码登录", "完成"].map((label, i) => `<li ${i === 0 ? 'class="current" aria-current="step"' : ""}><span>0${i + 1}</span>${label}</li>`).join("")}</ol>
        <main class="ocean-content">
          <section class="ocean-intro"><h1>在 QQ 里，<br>和<span>大肥鱼聊天。</span></h1><p>AI 聊天 · 语音互动 · 长期记忆</p>
            <div class="ocean-art"><img src="/img/dafeiyu-welcome-clean.png" alt="蓝发大肥鱼的可爱表情图"><span class="ocean-hello">大肥鱼来咯</span></div>
          </section>
          <section class="ocean-form" aria-labelledby="path-title"><h2 id="path-title">选择安装位置</h2>
            <div class="ocean-path-heading"><label class="ocean-path-label" for="path">安装位置</label><span id="path-hint">必须为纯英文目录，不含空格</span></div><div class="ocean-path-box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 7V5h7l2 3h9v12H3Z"/></svg><input id="path" type="text" value="${esc(S.info.default_path)}" spellcheck="false" autocomplete="off" aria-describedby="path-hint msg"></div>

            <p class="ocean-space">至少预留 10 GB 空间</p>
            <div class="ocean-warning"><span aria-hidden="true">!</span><p><b>请使用 QQ 小号</b><br>第三方登录存在账号受限或封号风险。</p></div>
            <details class="ocean-terms"><summary>内容授权与使用须知</summary><p>本项目自有部分采用 <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/" target="_blank" rel="noopener noreferrer">PolyForm Noncommercial 1.0.0</a>，仅授予协议允许的非商业使用权。第三方组件与素材按各自许可使用。</p><p>继续安装即表示你同意适用的许可条款，并知悉使用第三方 QQ 客户端的账号风险。</p></details>
            <div id="msg" class="msg bad" role="alert"></div><button class="ocean-go" id="go">开始安装 <span aria-hidden="true">↗</span></button>
          </section>
        </main>
      </div>`;
    return;
  }
  renderOceanStep(bodyHtml, footHtml, page, title, sub);
}

function renderOceanStep(bodyHtml, footHtml, page, title, sub) {
  $("#app").innerHTML = `
    <div class="ocean-shell ocean-keys ${page === 2 ? "ocean-profile" : page === 3 ? "ocean-install" : page === 4 ? "ocean-login" : page === 5 ? "ocean-done" : ""}">
      <header class="ocean-header"><div class="ocean-brand"><span class="ocean-mark">≈</span> 大肥鱼 QQ 助手</div><span class="brand-owner">作者：Xean</span></header>
      ${S.mode === "install" && page >= 0 ? `<ol class="ocean-steps" aria-label="安装步骤">${["安装位置", "连接服务", "个性设置", "安装程序", "扫码登录", "完成"].map((label, i) => `<li ${i === page ? 'class="current" aria-current="step"' : ""}><span>${i < page ? "✓" : "0" + (i + 1)}</span>${label}</li>`).join("")}</ol>` : `<div class="workspace-nav"><span>Xean 版本</span><span>本地控制台</span></div>`}
        <main class="connections">
        ${page === 5 ? "" : `<div class="connections-heading"><h1>${S.mode === "status" || page < 0 ? title : page === 4 ? "扫码登录 QQ 小号" : page === 3 ? "正在安装程序" : page === 2 ? "设置大肥鱼的个性" : "先连接聊天，再选择更多"}</h1><p>${S.mode === "status" || page < 0 ? sub : page === 4 ? "登录成功后，会自动进入下一步。" : page === 3 ? "安装完成后，将自动进入 QQ 扫码登录。" : page === 2 ? "已有默认设置，可以直接进入下一步。" : "聊天必填；语音和长期记忆可以稍后开启。密钥在本机保存。"}</p></div>`}
        ${bodyHtml}
        ${footHtml ? `<div class="connections-footer">${footHtml}</div>` : ""}
      </main>
    </div>`;
}

function oceanKeyFields(ph, enabled) {
  return `
    <div class="owner-row">
      <label class="field" id="f-owner_qq"><span>你的 QQ 号 <em class="badge" id="b-owner_qq"></em></span><input id="owner_qq" type="text" inputmode="numeric" autocomplete="off" placeholder="填写你自己的 QQ 大号" aria-describedby="owner-hint m-owner_qq"><div class="msg" id="m-owner_qq" aria-live="polite"></div></label>
      <p id="owner-hint">用于识别你。<br>不是给机器人登录的小号。</p>
    </div>
    <div class="service-grid">
      <section class="service-card"><div class="service-heading"><span class="service-number">01</span><div><h2>聊天 <small>必填</small></h2><p>DeepSeek</p></div></div>
        ${keyField("deepseek", "API Key", HELP.deepseek, "password", ph("deepseek", 'placeholder="粘贴 DeepSeek API Key"'))}
      </section>
      <section class="service-card"><div class="service-heading"><span class="service-number">02</span><div><h2>语音 <small>可选</small></h2><p>豆包语音</p></div></div>
        <label class="feature-switch"><input id="enable-voice" type="checkbox" ${enabled.voice ? "checked" : ""} aria-controls="voice-options"><span>开启语音</span></label>
        <p id="voice-off" class="feature-note" ${enabled.voice ? "hidden" : ""}>先用文字聊天，随时可以开启。</p>
        <div id="voice-options" class="voice-card" ${enabled.voice ? "" : "hidden"}><div id="voice-fields" class="voice-fields" inert>
        <label class="field" id="f-app_id"><span>APP ID <em class="badge" id="b-app_id"></em></span><input id="app_id" type="text" spellcheck="false" autocomplete="off" ${ph("app_id", 'placeholder="粘贴 APP ID"')}><div class="msg" id="m-app_id" aria-live="polite"></div></label>
        <label class="field" id="f-token"><span>Access Token</span><input id="token" type="password" autocomplete="off" ${ph("token", 'placeholder="粘贴 Access Token"')}><div class="msg" id="m-token" aria-live="polite"></div></label>
        <details class="help"><summary>如何获取？</summary>${HELP.doubao}</details></div>
        <div id="voice-gate" class="voice-gate" aria-live="polite"></div></div>
      </section>
      <section class="service-card"><div class="service-heading"><span class="service-number">03</span><div><h2>长期记忆 <small>可选</small></h2><p>硅基流动</p></div></div>
        <label class="feature-switch"><input id="enable-memory" type="checkbox" ${enabled.memory ? "checked" : ""} aria-controls="memory-options"><span>开启长期记忆</span></label>
        <p id="memory-off" class="feature-note" ${enabled.memory ? "hidden" : ""}>关闭后仍可正常聊天。</p>
        <div id="memory-options" ${enabled.memory ? "" : "hidden"}>${keyField("siliconflow", "API Key", HELP.siliconflow, "password", ph("siliconflow", 'placeholder="粘贴硅基流动 API Key"'))}<p class="feature-note">用于检索以前的聊天；向量化可能消耗额度。</p></div>
      </section>
    </div><div id="msg" class="msg bad" role="alert"></div>
    ${S.mode === "install" ? `<div id="mini" class="connections-progress">${miniProgress()}</div>` : ""}`;
}

function setupVoiceGate(onUnlock, profile = false) {
  const consentKey = profile ? "profileVoiceAccepted" : "voiceAccepted";
  const inputIds = profile ? ["voice", "listen"] : ["app_id", "token"];
  const fields = $("#voice-fields"), gate = $("#voice-gate");
  if (!fields || !gate) return;
  const unlock = (focus = false) => {
    S[consentKey] = true;
    fields.inert = false;
    inputIds.forEach(id => ($("#" + id).disabled = false));
    gate.hidden = true;
    onUnlock();
    if (focus) $("#" + inputIds[0]).focus();
  };
  if (S[consentKey]) return unlock();
  inputIds.forEach(id => ($("#" + id).disabled = true));
  const render = (confirm = false, focus = false) => {
    gate.innerHTML = `<span class="voice-lock" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg></span>
      <h3>${confirm ? "您确认吗？" : "语音服务可能产生额外费用"}</h3>
      <p>${confirm ? (profile ? "确认后可编辑音色并试听。生成试听可能消耗额度或产生费用。" : "确认后解锁。填写凭证会自动试音校验，可能消耗额度或产生费用。") : "语音由豆包提供，校验、试听与生成语音均可能消耗额度或产生费用。"}</p>
      <div class="voice-gate-actions">${confirm ? '<button id="voice-cancel" type="button">取消</button><button id="voice-confirm" type="button" class="primary">确认解锁</button>' : '<button id="voice-review" type="button" class="primary">解锁语音</button>'}</div>`;
    if (confirm) {
      $("#voice-cancel").onclick = () => render(false, true);
      $("#voice-confirm").onclick = () => unlock(true);
      if (focus) $("#voice-cancel").focus();
    } else {
      $("#voice-review").onclick = () => render(true, true);
      if (focus) $("#voice-review").focus();
    }
  };
  render();
}

/** 居中弹窗确认。opts: {title, body, ok, danger, need}（need 填了就要照着抄一遍才能点确认）*/
function confirmBox(opts) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal";
    wrap.innerHTML = `<div class="card" role="dialog" aria-modal="true" aria-labelledby="mt">
      <h2 id="mt">${opts.title}</h2>
      <div class="mbody">${opts.body}</div>
      ${opts.need ? `<label class="field"><span>想继续，请在下面抄一遍「${esc(opts.need)}」</span>
        <input id="mneed" type="text" autocomplete="off" spellcheck="false"></label>` : ""}
      <div class="mfoot"><button id="mno">取消</button>
        <button id="myes" class="${opts.danger ? "danger" : "primary"}" ${opts.need ? "disabled" : ""}>${esc(opts.ok || "确定")}</button></div>
    </div>`;
    document.body.appendChild(wrap);
    const previous = document.activeElement;
    const app = $("#app"), wasInert = app.inert;
    app.inert = true;
    let closed = false;
    const close = (v) => {
      if (closed) return;
      closed = true;
      wrap.remove(); app.inert = wasInert;
      document.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
      if (e.key !== "Tab") return;
      const items = [...wrap.querySelectorAll("button:not(:disabled), input:not(:disabled)")];
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    wrap.onclick = (e) => e.target === wrap && close(false);
    $("#mno", wrap).onclick = () => close(false);
    $("#myes", wrap).onclick = () => close(true);
    if (opts.need) {
      const inp = $("#mneed", wrap);
      inp.oninput = () => ($("#myes", wrap).disabled = inp.value.trim() !== opts.need);
      inp.focus();
    } else $("#myes", wrap).focus();
  });
}

function miniProgress() {
  const p = S.progress;
  if (!Array.isArray(p?.steps) || !p.steps.length) return `<div class="minibar">后台准备中…<div class="bar"><i style="width:3%"></i></div></div>`;
  const done = p.steps.filter((s) => s.status === "done").length;
  const cur = p.steps.find((s) => s.status === "doing" || s.status === "error");
  const label = cur ? (cur.status === "error" ? "后台出错了，到第 4 步看看" : (p.waiting ? "等你填完这页" : cur.title + "…")) : "后台准备好了";
  return `<div class="minibar">后台：${esc(label)}<div class="bar"><i style="width:${Math.max(3, (done / p.steps.length) * 100)}%"></i></div></div>`;
}

function pollProgress() {
  poll(async epoch => {
    const p = await pageRequest("/api/progress", undefined, epoch);
    if (!p) return;
    if (p.ok === false || !Array.isArray(p.steps)) {
      const mini = $("#mini");
      if (mini) mini.textContent = p.message || "暂时无法读取进度，正在重试…";
      showError(p.message || "暂时无法读取进度，正在重试…");
      return;
    }
    S.progress = p;
    if (S.page === 3 && $("#msg")) $("#msg").textContent = "";
    const el = $("#mini");
    if (el) el.innerHTML = miniProgress();
    if (S.page === 3) renderTasks();
  });
}

// ---------------- 第 1 页：位置 ----------------
function pagePath() {
  S.page = 0;
  shell(0, "选择安装位置", "", "", "");
  const epoch = S.epoch;
  let saving = false;
  const go = async () => {
    if (saving) return;
    saving = true;
    $("#go").disabled = true;
    const r = await pageRequest("/api/path", { path: $("#path").value }, epoch);
    if (!r) return;
    saving = false;
    $("#go").disabled = false;
    if (!r.ok) {
      $("#msg").className = "msg bad";
      $("#msg").textContent = r.message;
      return;
    }
    if (!(await reloadInfo(epoch))) return;
    const resume = S.info.resume || r.resume;
    if (resume?.keys && resume?.profile) pageTasks();
    else if (resume?.keys) pageProfile();
    else pageKeys();
  };
  $("#go").onclick = go;
  $("#path").onkeydown = (e) => e.key === "Enter" && go();
}

// ---------------- 第 2 页：key ----------------
const HELP = {
  deepseek: `<ol><li>登录 <a href="https://platform.deepseek.com/" target="_blank" rel="noopener noreferrer">DeepSeek 开放平台</a>。</li><li>在 API Keys 页面创建密钥，并粘贴到此处。</li></ol>调用可能产生费用，请查看平台余额与计费说明。`,
  doubao: `<ol><li>登录 <a href="https://console.volcengine.com/speech/app" target="_blank" rel="noopener noreferrer">火山引擎语音控制台</a>。</li><li>为应用配置豆包音频生成模型 1.0，并查看可用额度与计费规则。</li><li>复制 APP ID 和 Access Token。请勿填入火山方舟 API Key 或 Secret Key。</li></ol>校验和试听会生成音频，可能消耗额度或产生费用。`,
  siliconflow: `<ol><li>登录 <a href="https://cloud.siliconflow.cn/" target="_blank" rel="noopener noreferrer">硅基流动控制台</a>。</li><li>创建 API 密钥并粘贴到此处。</li></ol>使用 BAAI/bge-m3 生成记忆检索向量。价格以平台当时说明为准；需向量化的文字会发送到服务端。`,
};

function keyField(id, label, help, type = "password", extra = "") {
  return `<label class="field" id="f-${id}">
    <span>${label} <em class="badge" id="b-${id}"></em></span>
    <input id="${id}" type="${type}" spellcheck="false" autocomplete="off" ${extra}>
    <div class="msg" id="m-${id}" aria-live="polite"></div>
  </label>
  <details class="help"><summary>如何获取？</summary>${help}</details>`;
}

function setBadge(id, state, msg) {
  const b = $("#b-" + id), m = $("#m-" + id), f = $("#f-" + id);
  if (!b) return;
  b.className = "badge " + state;
  b.textContent = { ok: "✓ 可以用", bad: "✗ 不对", wait: "检查中…", "": "" }[state];
  m.className = "msg " + (state === "bad" ? "bad" : state === "ok" ? "ok" : "");
  m.textContent = msg || "";
  f.classList.toggle("bad", state === "bad");
}

function pageKeys() {
  S.page = 1;
  const saved = (S.info.saved_keys || []);
  const enabled = features();
  const originallyEnabled = { ...enabled };
  S.voiceAccepted = false;
  const ph = (f, normal) => saved.includes(f) ? 'placeholder="已保存，不用改就留空"' : normal;
  shell(1, "连接服务", "已保存的密钥留空即可保留。语音与长期记忆可随时关闭。", oceanKeyFields(ph, enabled),
    `<button id="back">${S.mode === "status" ? "返回" : "上一步"}</button>
     <button class="primary" id="go" disabled>${S.mode === "status" ? "保存设置" : "下一步"}</button>`);
  const epoch = S.epoch;
  let saving = false;
  const blankOk = (f) => saved.includes(f) && !$("#" + f).value.trim();
  const state = { owner_qq: false, deepseek: false, doubao: false, siliconflow: false };
  const sequence = { deepseek: 0, doubao: 0, siliconflow: 0 };
  const refresh = () => {
    if (epoch !== S.epoch) return;
    const voiceReady = !enabled.voice || ((S.voiceAccepted || originallyEnabled.voice) &&
      (state.doubao || (blankOk("app_id") && blankOk("token"))));
    const memoryReady = !enabled.memory || state.siliconflow || blankOk("siliconflow");
    $("#go").disabled = saving || !state.owner_qq || !(state.deepseek || blankOk("deepseek")) || !voiceReady || !memoryReady;
    $("#back").disabled = saving;
  };
  const val = (id) => $("#" + id).value.trim();
  const checkQQ = () => {
    const ok = /^\d{5,12}$/.test(val("owner_qq"));
    state.owner_qq = ok;
    setBadge("owner_qq", val("owner_qq") ? (ok ? "ok" : "bad") : "", ok || !val("owner_qq") ? "" : "QQ 号只能是 5 到 12 位数字");
    refresh();
  };
  const check = async (field) => {
    if (saving || (field === "doubao" && (!enabled.voice || !S.voiceAccepted)) || (field === "siliconflow" && !enabled.memory)) return;
    const seq = ++sequence[field];
    const badgeId = field === "doubao" ? "app_id" : field;
    const body = field === "doubao" ? { field, app_id: val("app_id"), token: val("token"), voice_consent: true } : { field, value: val(field) };
    if (field === "doubao" ? (!(body.app_id || blankOk("app_id")) || !(body.token || blankOk("token")) || (!body.app_id && !body.token)) : !body.value) {
      state[field] = false;
      setBadge(badgeId, "", "");
      return refresh();
    }
    state[field] = false;
    refresh();
    setBadge(badgeId, "wait", field === "doubao" ? "正在校验语音服务…" : "");
    const r = await pageRequest("/api/check", body, epoch);
    if (!r || seq !== sequence[field]) return;
    state[field] = !!r.ok;
    setBadge(badgeId, r.ok ? "ok" : "bad", r.message);
    refresh();
  };
  $("#owner_qq").oninput = checkQQ;
  $("#owner_qq").value = S.info.owner_qq || "";
  if (S.info.owner_qq) checkQQ();
  ["deepseek", "siliconflow", "app_id", "token"].forEach(id => {
    const field = ["app_id", "token"].includes(id) ? "doubao" : id;
    $("#" + id).oninput = () => { sequence[field]++; state[field] = false; setBadge(field === "doubao" ? "app_id" : field, "", ""); refresh(); };
    $("#" + id).onchange = () => check(field);
  });
  setupVoiceGate(refresh);
  const toggle = () => {
    enabled.voice = $("#enable-voice").checked;
    enabled.memory = $("#enable-memory").checked;
    $("#voice-options").hidden = !enabled.voice;
    $("#voice-off").hidden = enabled.voice;
    $("#memory-options").hidden = !enabled.memory;
    $("#memory-off").hidden = enabled.memory;
    $("#siliconflow").disabled = !enabled.memory;
    refresh();
  };
  $("#enable-voice").onchange = () => {
    sequence.doubao++;
    state.doubao = false;
    // Re-enabling always starts a fresh explicit consent interaction.
    S.voiceAccepted = false;
    originallyEnabled.voice = false;
    $("#voice-gate").hidden = false;
    $("#voice-fields").inert = true;
    setupVoiceGate(refresh);
    toggle();
  };
  $("#enable-memory").onchange = () => { sequence.siliconflow++; state.siliconflow = false; toggle(); if (enabled.memory && val("siliconflow")) check("siliconflow"); };
  toggle();
  $("#back").onclick = S.mode === "status" ? pageStatus : pagePath;
  $("#go").onclick = async () => {
    refresh();
    if (saving || $("#go").disabled) return;
    saving = true;
    refresh();
    showError("");
    $("#msg").textContent = "";
    $("#go").innerHTML = '<span class="spin"></span> 确认中';
    const r = await pageRequest("/api/keys", { owner_qq: val("owner_qq"), deepseek: val("deepseek"), siliconflow: enabled.memory ? val("siliconflow") : "",
      app_id: enabled.voice ? val("app_id") : "", token: enabled.voice ? val("token") : "", features: { ...enabled }, voice_consent: enabled.voice && S.voiceAccepted }, epoch);
    if (!r) return;
    if (r.ok && await reloadInfo(epoch)) return S.mode === "status" ? applySettings() : pageProfile();
    if (epoch !== S.epoch) return;
    saving = false;
    $("#go").textContent = S.mode === "status" ? "保存设置" : "下一步";
    if (!r.ok) showError(r.message || (r.errors ? "请检查下面标出的项目。" : "保存失败，请重试。"));
    for (const [k, msg] of Object.entries(r.errors || {})) { state[k] = false; setBadge(k === "doubao" ? "app_id" : k, "bad", msg); }
    refresh();
  };
  if (S.mode === "install") pollProgress();
}

// ---------------- 第 3 页：个性化 ----------------
const MEME_NAMES = { "blue-fat-fish-meme-pack": "蓝色大肥鱼（157 张）", "deepseek-fanart-meme-pack": "DeepSeek 二创（174 张）" };

function oceanProfileFields(p, memes) {
  return `<div class="profile-grid">
    <section class="profile-panel"><h2>名字与性格</h2>
      <label class="field"><span>名字 <small>最多 20 个字</small></span><input id="name" type="text" maxlength="20" value="${esc(p.name)}"></label>
      <label class="field"><span>性格 <small>描述她的性格和说话方式</small></span><textarea id="persona" rows="9" aria-describedby="persona-hint">${esc(p.persona)}</textarea></label>
      <p id="persona-hint" class="profile-hint">保留 <code>{OWNER_QQ}</code>，用于识别你的 QQ 号。</p>
    </section>
    <div class="profile-options">
      ${features().voice ? `<section class="profile-panel voice-card"><div id="voice-fields" class="voice-fields" inert><h2>声音</h2>
        <label class="field"><span>音色描述</span><textarea id="voice" rows="3">${esc(p.voice)}</textarea></label>
        <div class="profile-listen"><span>试听可能消耗额度或产生费用</span><button id="listen" type="button">试听声音</button></div>
        <div class="msg" id="m-voice" role="status"></div><audio id="player" hidden></audio></div><div id="voice-gate" class="voice-gate" aria-live="polite"></div>
      </section>` : `<section class="profile-panel"><h2>声音</h2><p class="feature-note">语音尚未开启。现在可以先用文字聊天，默认甜妹音会保留。</p><button id="voice-settings" type="button">前往连接设置</button></section>`}
      <section class="profile-panel profile-memes"><h2>表情包 <small>至少选择一套</small></h2><div class="checks">${memes}</div></section>
    </div>
  </div><div id="msg" class="msg bad" role="alert"></div>${S.mode === "install" ? `<div id="mini" class="connections-progress">${miniProgress()}</div>` : ""}`;
}

function pageProfile() {
  S.page = 2;
  const p = S.profileDraft || S.info.profile;
  const memes = Object.entries(p.memes).map(([id, on]) =>
    `<label><input type="checkbox" data-meme="${esc(id)}" ${on ? "checked" : ""}> ${esc(MEME_NAMES[id] || id)}</label>`).join("");
  shell(2, "个性设置", "修改名字、性格和音色，保存后生效。", oceanProfileFields(p, memes),
    `<button id="back">${S.mode === "status" ? "返回" : "上一步"}</button><button class="primary" id="go">${S.mode === "status" ? "保存设置" : "下一步"}</button>`);

  const epoch = S.epoch;
  let saving = false, listening = false;
  S.profileVoiceAccepted = false;
  setupVoiceGate(() => {}, true);
  if ($("#listen")) $("#listen").onclick = async () => {
    if (!S.profileVoiceAccepted || listening) return;
    listening = true;
    $("#listen").disabled = true;
    $("#m-voice").className = "msg";
    $("#m-voice").textContent = "正在生成试听，可能消耗额度或产生费用…";
    const r = await pageRequest("/api/preview_voice", { voice: $("#voice").value, name: $("#name").value, voice_consent: true }, epoch);
    if (!r) return;
    listening = false;
    $("#listen").disabled = false;
    if (!r.ok) {
      $("#m-voice").className = "msg bad";
      $("#m-voice").textContent = r.message;
      return;
    }
    $("#m-voice").textContent = "";
    const a = $("#player");
    a.src = "data:audio/mpeg;base64," + r.audio_b64;
    a.controls = true;
    a.hidden = false;
    try { await a.play(); } catch { if (epoch === S.epoch) $("#m-voice").textContent = "试听已生成，请点击播放。"; }
  };
  const collect = () => {
    const memes = {};
    document.querySelectorAll("[data-meme]").forEach((c) => (memes[c.dataset.meme] = c.checked));
    return { name: $("#name").value.trim(), persona: $("#persona").value, voice: $("#voice")?.value.trim() || p.voice, memes };
  };
  $("#back").onclick = () => { S.profileDraft = collect(); S.mode === "status" ? pageStatus() : pageKeys(); };
  if ($("#voice-settings")) $("#voice-settings").onclick = () => { S.profileDraft = collect(); pageKeys(); };
  $("#go").onclick = async () => {
    if (saving) return;
    saving = true;
    $("#go").disabled = $("#back").disabled = true;
    $("#msg").textContent = "";
    const prof = collect();
    const r = await pageRequest("/api/profile", prof, epoch);
    if (!r) return;
    if (!r.ok || !(await reloadInfo(epoch))) {
      if (epoch !== S.epoch) return;
      saving = false;
      $("#go").disabled = $("#back").disabled = false;
      if (!r.ok) showError(r.message);
      return;
    }
    S.profileDraft = null;
    S.mode === "status" ? applySettings() : pageTasks();
  };
  if (S.mode === "install") pollProgress();
}

// ---------------- 第 4 页：安装进度 ----------------
const ICON = { done: "✓", error: "!", doing: "", todo: "" };

const INSTALL_TITLES = {extract:"解压程序文件", ports:"准备本地连接", configs:"保存连接设置", astrbot:"启动聊天服务", napcat:"启动 QQ 连接", import:"配置角色与插件", shortcut:"创建桌面快捷方式"};

function renderTasks() {
  const p = S.progress;
  const ul = $("#tasks");
  if (!ul || !Array.isArray(p?.steps)) return;
  const visibleSteps = p.steps.filter(s => s.key !== "login");
  const completed = visibleSteps.filter(s => s.status === "done").length;
  const failed = visibleSteps.find(s => s.status === "error");
  const current = visibleSteps.find(s => s.status === "doing");
  if ($("#install-count")) {
    $("#install-count").textContent = `${completed} / ${visibleSteps.length}`;
    $("#install-current").textContent = failed ? "有一步需要重试" : current ? (INSTALL_TITLES[current.key] || current.title) : completed === visibleSteps.length ? "安装已完成" : "等待准备";
    $("#install-track").value = completed;
    $("#install-track").max = visibleSteps.length || 1;
    $("#install-status").textContent = failed ? "查看右侧错误信息，然后点击重试。" : p.waiting ? "等待所需设置，请稍候。" : "请保持网络连接，程序会自动继续。";
  }
  ul.innerHTML = visibleSteps.map((s) => `
    <li class="${s.status}"><span class="ic">${ICON[s.status]}</span><div><div class="install-task-line"><span>${esc(S.mode === "install" ? (INSTALL_TITLES[s.key] || s.title) : s.title)}</span><small>${({done:"已完成", doing:"进行中", error:"未完成", todo:"等待中"})[s.status] || "等待中"}</small></div>
      ${s.status === "error" ? `<div class="t-msg" style="white-space:pre-wrap">${esc(s.message)}</div>` : ""}
      ${s.status === "doing" && s.key === "import" ? `<div class="t-wait">正在配置角色、表情包与已选服务</div>` : ""}
      ${s.status === "doing" && s.key === "extract" ? `<div class="t-wait">文件多，大概一两分钟</div>` : ""}
    </div></li>`).join("");
  const err = p.steps.some((s) => s.status === "error");
  $("#retry").hidden = !err;
  const login = p.steps.find((s) => s.key === "login");
  if (login && (login.status === "doing" || login.status === "done") && S.page === 3) pageQR();
}

function pageTasks() {
  S.page = 3;
  shell(3, "正在安装程序", "安装完成后自动进入扫码登录。", `
    <div class="install-grid"><section class="install-summary"><span class="install-caption">安装进度</span><strong id="install-count">0 / 7</strong><span class="install-caption">已完成步骤</span><progress id="install-track" value="0" max="7" aria-label="已完成的安装步骤"></progress><h2 id="install-current" aria-live="polite">正在准备</h2><p id="install-status">请保持网络连接，程序会自动继续。</p></section><section aria-label="安装任务"><ul class="tasks" id="tasks"></ul></section></div><div id="msg" class="msg bad" role="alert"></div>`,
    `<span class="install-resume">安装中断后，可重新打开继续。</span><button class="primary" id="retry" hidden>重试未完成步骤</button>`);
  $("#retry").onclick = async () => {
    const btn = $("#retry");
    btn.disabled = true;
    const r = await pageRequest("/api/retry", {});
    if (!r) return;
    btn.disabled = false;
    if (!r.ok) return showError(r.message);
    btn.hidden = true;
  };
  renderTasks();
  if (S.page === 3) pollProgress();
}

// ---------------- 第 5 页：扫码 ----------------
const LOGIN_TEXT = {
  starting: ["正在获取二维码…", "wait"],
  need_scan: ["等待手机扫码", "wait"],
  scanned: ["已扫码，请在手机上确认", "wait"],
  online: ["登录成功", "on"],
  offline: ["连接已断开，正在重连…", "off"],
  error: ["二维码不可用，请刷新", "off"],
};

function qrBlock() {
  return `
    <div class="login-grid">
      <section class="login-guide"><span class="login-label">手机端操作</span><h2>三步，连接大肥鱼</h2>
        <ol class="login-instructions"><li><span>1</span><div><b>切换到 QQ 小号</b><p>打开手机 QQ，确认当前登录的是小号。</p></div></li><li><span>2</span><div><b>打开扫一扫</b><p>扫描右侧二维码。</p></div></li><li><span>3</span><div><b>在手机上确认登录</b><p>确认后，等待页面自动跳转。</p></div></li></ol>
        <p class="login-risk">请勿使用常用账号。第三方登录存在账号受限或封号风险。</p>
      </section>
      <section class="login-scan" aria-label="登录二维码"><div class="qr">
        <div class="frame"><img id="qr" alt="使用手机 QQ 扫描登录小号" hidden><span id="qrwait" class="spin"></span></div>
        <div class="status-big"><span class="dot wait" id="dot"></span><span id="qrstate" role="status">正在获取二维码…</span></div>
        <button id="reqr" type="button">刷新二维码</button>
        <div class="msg" id="qrmsg" role="status">二维码未出现或已失效，可点击刷新。</div>
      </div></section>
    </div>`;

}

function bindRefreshQR() {
  const btn = $("#reqr");
  if (!btn) return;
  btn.onclick = async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    const r = await pageRequest("/api/refresh_qr", {});
    if (!r) return;
    $("#qrmsg").textContent = r.message || "";
    later(() => { btn.disabled = false; }, 3000);
  };
}

function pollLogin(onOnline, active = () => true) {
  poll(async epoch => {
    if (!active()) return;
    const r = await pageRequest("/api/login", undefined, epoch);
    if (!r || !$("#qrstate")) return;
    if (r.ok === false) {
      $("#qrmsg").textContent = r.message;
      $("#qrstate").textContent = "暂时无法读取登录状态";
      return;
    }
    const [text, dot] = LOGIN_TEXT[r.status] || LOGIN_TEXT.starting;
    if (!$("#qrstate")) return;
    $("#qrstate").textContent = text;
    $("#dot").className = "dot " + dot;
    // NapCat 说「已登录」时换码没用，得点按钮重启它，所以要把原因显示出来
    if (r.error && $("#qrmsg")) $("#qrmsg").textContent = r.error + "（请点击刷新二维码）";
    const show = r.status === "need_scan" || r.status === "scanned";
    if (show) {
      const img = $("#qr");
      const fresh = new Image();
      fresh.onload = () => { if (!img.isConnected || epoch !== S.epoch) return; img.src = fresh.src; img.hidden = false; $("#qrwait").hidden = true; };
      fresh.onerror = () => { if (!img.isConnected || epoch !== S.epoch) return; img.hidden = true; $("#qrwait").hidden = true; $("#qrmsg").textContent = "二维码加载失败，请刷新重试。"; };
      fresh.src = `/api/qr?token=${encodeURIComponent(window.TOKEN)}&t=${Date.now()}`;
    } else {
      $("#qr").hidden = true;
      $("#qrwait").hidden = r.status === "online";
    }
    if (r.status === "online") onOnline();
  }, 3000);
}

function pageQR() {
  S.page = 4;
  shell(4, "扫码登录小号", "使用手机 QQ 小号扫码，并在手机上确认。", qrBlock(), "");
  bindRefreshQR();
  let done = false;
  pollLogin(() => {
    if (done) return;
    done = true;
    clearTimers();
    later(pageDone, 800);
  });
}

// 状态页里的重新扫码：登录好了就回主页，不像安装时往下走
function pageRescan() {
  clearTimers();
  S.page = -1;
  shell(-1, "扫码登录小号", "使用手机 QQ 小号扫码，并在手机上确认。", qrBlock(),
    `<button id="back">返回</button><span></span>`);
  $("#back").onclick = pageStatus;
  bindRefreshQR();
  let done = false;
  pollLogin(() => {
    if (done) return;
    done = true;
    clearTimers();
    later(pageStatus, 800);
  });
}

// ---------------- 第 6 页：完成 ----------------
async function pageDone() {
  S.page = 5;
  clearTimers();
  const epoch = ++S.epoch;
  const d = await pageRequest("/api/done", undefined, epoch);
  if (!d) return;
  const name = S.info.profile?.name || "大肥鱼";
  if (!d.dashboard_url || !d.username || !d.password) {
    shell(5, "登录已完成", "", `<div class="done-result"><h1>登录已完成</h1><p>后台信息暂时无法读取，请重试。</p><button id="done-retry" class="primary">重新获取</button></div>`, "");
    $("#done-retry").onclick = pageDone;
    return;
  }
  shell(5, `${esc(name)}已上线`, "", `
    <section class="done-result"><span class="done-check" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m8 16 5 5 11-11"/></svg></span><span class="done-label">安装完成</span><h1>${esc(name)}已上线</h1><p>用你的 QQ 大号，给刚登录的小号发一句「在吗」。</p></section>
    <div class="done-tips"><section><span class="done-tip-number">01</span><div><h2>去 QQ 开始聊天</h2><p>这个窗口可以关闭，不影响她继续在线。</p></div></section><section><span class="done-tip-number">02</span><div><h2>下次如何启动</h2><p>双击桌面的「启动大肥鱼」。<br>电脑睡眠或关机后，她会离线。</p></div></section></div>
    <details class="done-account"><summary>查看后台登录信息</summary><div class="done-account-body"><dl><dt>后台地址</dt><dd>${esc(d.dashboard_url)}</dd><dt>账号</dt><dd>${esc(d.username)}</dd><dt>密码</dt><dd class="done-password"><input id="done-password" type="password" readonly value="${esc(d.password)}" aria-label="后台密码"><button id="toggle-password" type="button" aria-controls="done-password" aria-pressed="false">显示</button></dd></dl><p>账号密码仅在本页显示。需要时可导出明文文件，请妥善保管。</p><button id="export-info" type="button">导出登录信息</button><p id="export-msg" class="msg" role="status"></p></div></details>
    <p id="close-hint" class="msg" role="status"></p>`,
    `<a class="done-dashboard" href="${esc(d.dashboard_url)}" target="_blank" rel="noopener noreferrer">打开管理后台 <span aria-hidden="true">↗</span></a><button class="primary" id="fin">完成并关闭</button>`);
  $("#toggle-password").onclick = () => {
    const input = $("#done-password"), show = input.type === "password";
    input.type = show ? "text" : "password";
    $("#toggle-password").textContent = show ? "隐藏" : "显示";
    $("#toggle-password").setAttribute("aria-pressed", String(show));
  };
  $("#fin").onclick = () => {
    window.close();
    if ($("#close-hint")) $("#close-hint").textContent = "如果窗口未自动关闭，可以手动关闭此页。";
  };
  $("#export-info").onclick = async () => {
    const btn = $("#export-info");
    if (btn.disabled) return;
    btn.disabled = true;
    const r = await pageRequest("/api/done?export=1");
    if (!r) return;
    btn.disabled = false;
    $("#export-msg").textContent = r.ok === false ? r.message : `已保存到 ${r.info_file || "安装目录的 userdata/我的信息.txt"}。`;
  };
}

// ---------------- 状态页（桌面快捷方式打开的） ----------------
async function pageStatus() {
  clearTimers();
  S.page = -1;
  const name = S.info.profile?.name || "大肥鱼";
  shell(-1, "运行状态", "管理连接、角色与服务设置。", `
    <section class="console-hero"><div><span class="console-label">当前角色</span><h2>${esc(name)}</h2><div class="status-big"><span class="dot" id="sdot"></span><span id="stext" role="status">正在读取状态…</span></div></div><div class="acts"><button class="primary" id="up" disabled>启动服务</button><button id="down" disabled>停止服务</button></div></section>
    <div id="serr" class="msg bad" role="alert"></div><div id="sqr" hidden>${qrBlock()}</div>
    <div class="console-settings"><section><h2>角色设置</h2><p>名字、性格、音色与表情包</p><button id="edit-prof">编辑角色</button></section><section><h2>连接服务</h2><p>QQ 大号与各项 API 凭证</p><button id="edit-keys">管理连接</button></section><section><h2>登录账号</h2><p>退出当前小号并重新扫码</p><button id="switch-qq">更换 QQ 小号</button></section></div>
    <details class="console-more"><summary>退出与卸载</summary><p>停止服务会保留数据；卸载会删除安装文件与本项目的数据。</p><div class="acts"><button id="quit">停止并退出</button><button class="danger-ghost" id="uninstall">卸载应用</button></div></details>`, "");
  const epoch = S.epoch;
  let busy = false, reading = false;
  const controls = () => ["up", "down", "switch-qq", "quit", "uninstall", "edit-keys", "edit-prof"].map(id => $("#" + id));
  const action = async (path) => {
    if (busy) return null;
    busy = true;
    controls().forEach(btn => { btn.disabled = true; });
    $("#serr").textContent = "";
    const r = await pageRequest(path, {}, epoch);
    if (!r) return null;
    busy = false;
    controls().forEach(btn => { btn.disabled = false; });
    if (!r.ok) { showError(r.message, "#serr"); return null; }
    return r;
  };
  $("#up").onclick = async () => { if (await action("/api/start")) tick(epoch); };
  $("#down").onclick = async () => { if (await action("/api/stop")) tick(epoch); };
  $("#edit-keys").onclick = () => { clearTimers(); pageKeys(); };
  $("#edit-prof").onclick = () => { clearTimers(); pageProfile(); };
  $("#switch-qq").onclick = async () => {
    const yes = await confirmBox({
      title: "更换 QQ 小号",
      body: `<p>当前小号将<b>退出登录</b>，随后显示新的登录二维码。</p>
        <div class="note">将清除本项目保存的小号登录状态。角色设置、聊天记录和表情包保留；不会操作其他 QQ 账号。</div>`,
      ok: "退出登录",
    });
    if (!yes || epoch !== S.epoch) return;
    if (!(await action("/api/switch_qq"))) return;
    if (!(await action("/api/start"))) return;
    pageRescan();
  };
  $("#quit").onclick = async () => {
    const yes = await confirmBox({
      title: "停止并退出",
      body: `<p>将停止聊天与 QQ 连接服务，并退出控制台。</p>
        <div class="note">数据会保留。下次双击桌面的「启动大肥鱼」即可启动。</div>`,
      ok: "停止并退出",
    });
    if (!yes || epoch !== S.epoch || !(await action("/api/quit"))) return;
    shell(-1, "服务已停止", "聊天与 QQ 连接服务已停止。", `
      <div class="note">双击桌面的「启动大肥鱼」可再次启动。现在可以关闭窗口。</div>`,
      `<span></span><button class="primary" id="fin">关闭窗口</button>`);
    $("#fin").onclick = () => window.close();
  };
  $("#uninstall").onclick = async () => {
    const yes = await confirmBox({
      title: "卸载应用",
      danger: true,
      need: "卸载",
      body: `<p>将删除以下内容，<b>此操作不可撤销</b>：</p>
        <ul class="bullets">
          <li>安装目录 <code>${esc(S.info.root || "")}</code> 里的全部文件</li>
          <li>本项目的聊天记忆、表情包及 API 凭证</li>
          <li>桌面上的「启动大肥鱼」图标</li>
          <li>本项目保存的小号登录状态</li>
        </ul>
        <div class="note">不会删除电脑 QQ 客户端的聊天记录。若只是暂时不用，请取消并选择「停止并退出」。</div>`,
      ok: "确认卸载",
    });
    if (!yes || epoch !== S.epoch) return;
    const r = await action("/api/uninstall");
    if (!r) return;
    shell(-1, "已开始卸载", "请等待文件清理完成。", `
      <div class="note">卸载程序将在窗口关闭后清理文件。<br>
      如需再次使用，请重新运行安装程序。</div>`,
      `<span></span><button class="primary" id="fin">关闭窗口</button>`);
    $("#fin").onclick = () => window.close();
  };
  let qrPolling = false;
  const tick = async (requestEpoch) => {
    if (reading || busy) return;
    reading = true;
    const s = await pageRequest("/api/status", undefined, requestEpoch);
    reading = false;
    if (!s || busy || !$("#stext")) return;
    if (s.ok === false) {
      $("#stext").textContent = "暂时无法读取状态";
      $("#sdot").className = "dot off";
      $("#up").disabled = $("#down").disabled = true;
      showError(s.message, "#serr");
      return;
    }
    const running = s.astrbot && s.napcat;
    let text, dot;
    if (s.starting) [text, dot] = ["正在启动服务…", "wait"];
    else if (!running) [text, dot] = ["服务已停止", "off"];
    else if (s.login === "online") [text, dot] = [`在线${s.qq ? "（小号 " + s.qq + "）" : ""}`, "on"];
    else if (s.login === "need_scan" || s.login === "scanned" || s.login === "error") [text, dot] = ["需要扫码登录", "wait"];
    else [text, dot] = ["正在连接 QQ…", "wait"];
    $("#stext").textContent = text;
    $("#sdot").className = "dot " + dot;
    if (s.error) $("#serr").textContent = s.error;
    $("#up").disabled = running || s.starting;
    $("#down").disabled = !s.astrbot && !s.napcat;
    const needQR = running && ["need_scan", "scanned", "error"].includes(s.login);
    $("#sqr").hidden = !needQR;
    if (needQR && !qrPolling) {
      qrPolling = true;
      bindRefreshQR();
      pollLogin(() => {}, () => !$("#sqr").hidden);
    }
  };
  poll(tick, 3000);
}

// 改完设置：原地等重启，不要把人甩回安装向导
async function applySettings() {
  clearTimers();
  S.page = -1;
  shell(-1, "正在保存设置", "正在更新配置并重新连接服务，请稍候。", `
    <ul class="tasks" id="tasks"></ul>
    <div class="note">完成后自动返回控制台；登录失效时需重新扫码。</div>
    <div id="msg" class="msg bad" role="alert"></div>`,
    `<span></span><button class="primary" id="retry" hidden>重试</button>`);
  const epoch = S.epoch;
  let started = false, busy = false;
  const start = async () => {
    if (busy) return false;
    busy = true;
    $("#retry").disabled = true;
    const r = await pageRequest(started ? "/api/retry" : "/api/apply", {}, epoch);
    if (!r) return false;
    busy = false;
    $("#retry").disabled = false;
    $("#retry").hidden = !!r.ok;
    if (!r.ok) { showError(r.message); return false; }
    started = true;
    $("#msg").textContent = "";
    return true;
  };
  $("#retry").onclick = start;
  await start();
  if (epoch !== S.epoch) return;
  poll(async requestEpoch => {
    if (!started || busy) return;
    const p = await pageRequest("/api/progress", undefined, requestEpoch);
    if (!p || !$("#tasks")) return;
    if (p.ok === false || !Array.isArray(p.steps)) return showError(p.message || "暂时无法读取进度，正在重试…");
    S.progress = p;
    $("#msg").textContent = "";
    renderApplying();
    if (S.progress.finished) return clearTimers(), pageStatus();
    // 改完 key 后登录可能失效。只有真的要扫码才跳过去：登录还在的话这一步瞬间就过了，
    // 光看 status === "doing" 会白闪一下二维码页
    const login = S.progress.steps.find((s) => s.key === "login");
    if (login && login.status === "doing") {
      const l = await pageRequest("/api/login", undefined, requestEpoch);
      if (l && ["need_scan", "scanned", "error"].includes(l.status)) pageRescan();
    }
  });
}

function renderApplying() {
  const p = S.progress;
  const ul = $("#tasks");
  if (!ul || !Array.isArray(p?.steps)) return;
  // 只列这次重跑的几步，解压之类早就做完的不用再刷一遍
  const keys = ["configs", "astrbot", "napcat", "import", "login"];
  ul.innerHTML = p.steps.filter((s) => keys.includes(s.key)).map((s) => `
    <li class="${s.status}"><span class="ic">${ICON[s.status]}</span><div>${esc(INSTALL_TITLES[s.key] || s.title)}
      ${s.status === "error" ? `<div class="t-msg" style="white-space:pre-wrap">${esc(s.message)}</div>` : ""}
    </div></li>`).join("");
  $("#retry").hidden = !p.steps.some((s) => s.status === "error");
}

// ---------------- 入口 ----------------
(async () => {
  S.info = await api("/api/info");
  if (!S.info || !S.info.mode) {
    shell(-1, "暂时无法打开", esc(S.info?.message || "无法连接本地服务，请重新启动应用。"), "", "");
    return;
  }
  S.mode = S.info.mode;
  if (S.mode === "status") pageStatus();
  else if (S.info.root && S.info.resume?.keys && S.info.resume?.profile) pageTasks();
  else if (S.info.root && S.info.resume?.keys) pageProfile();
  else if (S.info.root) pageKeys();
  else pagePath();
})();
