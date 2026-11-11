/* Browser regression tests. Only the local mock server is contacted; no QQ or paid API calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const out = path.join(root, '.tmp', 'frontend-regression');
fs.mkdirSync(out, { recursive: true });
const packDir = path.join(root, 'vendor/dafeiyu-config-pack');
const pack = JSON.parse(fs.readFileSync(path.join(packDir, 'settings/pack.json'), 'utf8').replace(/^\uFEFF/, ''));
const profile = { name: '大肥鱼', persona: fs.readFileSync(path.join(packDir, 'persona/大肥鱼.md'), 'utf8').replace(/^\uFEFF/, ''),
  voice: pack.voice.doubao.persona, memes: Object.fromEntries(pack.meme_packs.map(m => [m.id, m.use !== false])) };
const info = { mode: 'install', root: null, default_path: 'D:\\DaFeiYu', owner_qq: '', saved_keys: [],
  features: { voice: false, memory: false }, resume: { keys: false, profile: false }, profile };
const fixture = { info, status: { astrbot: false, napcat: false, starting: false },
  progress: { steps: [{ key: 'extract', title: '解压', status: 'done' }, { key: 'configs', title: '设置', status: 'doing' }], waiting: 'keys' },
  login: { status: 'need_scan' }, failures: {}, delays: {}, calls: [] };
const pause = ms => new Promise(r => setTimeout(r, ms));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    let text = ''; for await (const part of req) text += part;
    const body = text ? JSON.parse(text) : undefined;
    fixture.calls.push({ path: req.url, body });
    let data = { ok: true };
    if (url.pathname === '/api/info') data = fixture.info;
    if (url.pathname === '/api/progress') data = fixture.progress;
    if (url.pathname === '/api/status') data = fixture.status;
    if (url.pathname === '/api/login') data = fixture.login;
    if (url.pathname === '/api/check') {
      if (body.value === 'old-good') await pause(250);
      data = { ok: body.value !== 'new-bad', message: body.value === 'new-bad' ? '新密钥无效' : '校验通过' };
    }
    if (url.pathname === '/api/path') fixture.info.root = 'D:\\DaFeiYu';
    if (url.pathname === '/api/keys') {
      fixture.info.features = body.features; fixture.info.owner_qq = body.owner_qq;
      fixture.info.saved_keys = ['deepseek']; fixture.info.resume.keys = true;
      if (body.features.voice) fixture.info.saved_keys.push('app_id', 'token');
      if (body.features.memory) fixture.info.saved_keys.push('siliconflow');
    }
    if (url.pathname === '/api/profile') { fixture.info.profile = body; fixture.info.resume.profile = true; }
    if (url.pathname === '/api/done') data = { ok: true, dashboard_url: 'http://127.0.0.1:6185', username: 'demo', password: 'fixture-password', info_file: 'D:\\DaFeiYu\\userdata\\我的信息.txt' };
    if (url.pathname === '/api/qr') { res.writeHead(200, { 'Content-Type': 'image/png' }); return res.end(fs.readFileSync(path.join(root, 'app/web/img/favicon.png'))); }
    data = fixture.failures[url.pathname] || data;
    const encoded = JSON.stringify(data);
    if (fixture.delays[url.pathname]) await pause(fixture.delays[url.pathname]);
    res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(encoded);
  }
  const target = path.join(root, 'app/web', url.pathname === '/' ? 'index.html' : url.pathname);
  if (!target.startsWith(path.join(root, 'app/web') + path.sep) || !fs.existsSync(target)) { res.writeHead(404); return res.end(); }
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
  res.writeHead(200, { 'Content-Type': types[path.extname(target)] || 'application/octet-stream' });
  const content = fs.readFileSync(target);
  res.end(path.extname(target) === '.html' ? content.toString().replace('{{TOKEN}}', 'test-only') : content);
});

let browser, ws, rpc;
async function main() {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const edge = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles, process.env.LOCALAPPDATA]
    .filter(Boolean).map(p => path.join(p, 'Microsoft/Edge/Application/msedge.exe')).find(fs.existsSync);
  assert(edge, 'Microsoft Edge is required for browser verification');
  const browserProfile = fs.mkdtempSync(path.join(out, 'profile-'));
  browser = spawn(edge, ['--headless=new', '--disable-gpu', '--no-first-run', '--remote-debugging-port=0',
    `--user-data-dir=${browserProfile}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  const endpoint = path.join(browserProfile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !fs.existsSync(endpoint); i++) await pause(100);
  assert(fs.existsSync(endpoint), 'Edge debug endpoint ready');
  const port = fs.readFileSync(endpoint, 'utf8').split('\n')[0];
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r, { once: true }));
  let id = 0; const pending = new Map(), errors = [];
  ws.addEventListener('message', event => {
    const m = JSON.parse(event.data);
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails);
    if (m.id) { const p = pending.get(m.id); if (!p) return; pending.delete(m.id); m.error ? p.reject(m.error) : p.resolve(m.result); }
  });
  rpc = (method, params = {}) => new Promise((resolve, reject) => { const n = ++id; pending.set(n, { resolve, reject }); ws.send(JSON.stringify({ id: n, method, params })); });
  const js = async expression => {
    const r = await rpc('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    assert(!r.exceptionDetails, JSON.stringify(r.exceptionDetails)); return r.result.value;
  };
  const waitFor = async (expression, label = expression) => { for (let i = 0; i < 60; i++) { if (await js(expression)) return; await pause(100); } throw Error(`Timeout: ${label}`); };
  let count = 0;
  const check = async (label, expression) => { assert(await js(expression), label); console.log('PASS', label); count++; };
  const shot = async name => { await pause(100); const r = await rpc('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }); fs.writeFileSync(path.join(out, name + '.png'), Buffer.from(r.data, 'base64')); };
  await rpc('Runtime.enable');
  await rpc('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
  await rpc('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
  await waitFor('typeof S!=="undefined" && !!$("#path")');
  await js('$("#go").click()'); await waitFor('!!$("#enable-voice")');
  await check('optional services initially disabled and hidden', '!$("#enable-voice").checked && !$("#enable-memory").checked && $("#voice-options").hidden && $("#memory-options").hidden');
  await shot('services-optional');
  await js('$("#owner_qq").value="12345678";$("#owner_qq").dispatchEvent(new Event("input"));$("#deepseek").value="old-good";$("#deepseek").oninput();$("#deepseek").onchange();$("#deepseek").value="new-bad";$("#deepseek").oninput();$("#deepseek").onchange()');
  await pause(400);
  await check('late validation cannot approve changed invalid credential', '$("#b-deepseek").textContent.includes("不对") && $("#go").disabled');
  await js('$("#deepseek").value="valid";$("#deepseek").oninput();$("#deepseek").onchange()'); await waitFor('!$("#go").disabled');
  await check('text chat can continue without optional credentials', '!$("#go").disabled && !S.voiceAccepted');
  await js('$("#enable-voice").click()');
  await check('voice enable requires consent', '!$("#voice-options").hidden && $("#go").disabled && $("#app_id").disabled');
  await js('$("#voice-review").click();$("#voice-cancel").click()');
  await check('cancel returns to locked overlay', '!!$("#voice-review") && $("#token").disabled');
  await js('$("#voice-review").click()'); await shot('services-voice-confirm');
  await js('$("#voice-confirm").click()');
  await check('confirmation unlocks voice', '!$("#token").disabled && !$("#voice-fields").inert');
  await js('$("#enable-voice").click();$("#go").click();$("#go").click()'); await waitFor('!!$("#persona")');
  assert.equal(fixture.calls.filter(c => c.path === '/api/keys').length, 1, 'no duplicate submit'); count++;
  assert.deepEqual(fixture.calls.find(c => c.path === '/api/keys').body.features, { voice: false, memory: false }); count++;
  await check('disabled profile keeps sweet voice without forcing paid setup', '!!$("#voice-settings") && !$("#listen") && S.info.profile.voice.includes("甜妹音")');
  await shot('profile-text-only');
  await js('$("#go").click()'); await waitFor('!!$("#tasks")');
  await check('installation page starts its own progress poll', '$("#install-count").textContent === "1 / 2"');
  fixture.failures['/api/progress'] = { ok: false, message: '模拟连接中断' };
  await waitFor('$("#msg").textContent.includes("模拟连接中断")');
  await check('progress failure preserves last valid tasks', '$("#tasks").children.length === 2');
  delete fixture.failures['/api/progress'];
  await js('clearTimers();S.mode="status";pageStatus()'); await waitFor('$("#stext").textContent === "服务已停止"');
  assert.equal(fixture.calls.filter(c => c.path === '/api/start').length, 0, 'status view never starts services'); count++;
  await shot('console-stopped');
  await js('$("#edit-keys").click()'); await check('saved credentials can be retained without verification', '!$("#go").disabled');
  await js('$("#back").click()'); await waitFor('!!$("#quit")');
  fixture.failures['/api/quit'] = { ok: false, message: '模拟停止失败' };
  await js('document.querySelector(".console-more").open=true;$("#quit").click()');
  await check('dialog disables background and starts inside dialog', '$("#app").inert && document.activeElement.closest(".modal")');
  await rpc('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab' });
  await rpc('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab' });
  await check('tab remains in modal', '!!document.activeElement.closest(".modal")');
  await js('$("#myes").click()'); await waitFor('$("#serr")?.textContent.includes("模拟停止失败")');
  await check('failed quit stays on console without success message', '!!$("#quit") && !$("#fin") && !$("#app").inert');
  fixture.failures['/api/switch_qq'] = { ok: false, message: '模拟换号失败' };
  await js('$("#switch-qq").click();$("#myes").click()'); await waitFor('$("#serr")?.textContent.includes("模拟换号失败")');
  assert.equal(fixture.calls.filter(c => c.path === '/api/start').length, 0, 'failed switch never starts'); count++;
  await js('$("#uninstall").click()');
  await check('uninstall preserves external QQ history and requires phrase', '$("#myes").disabled && document.querySelector(".mbody").textContent.includes("不会删除电脑 QQ 客户端的聊天记录")');
  await js('$("#mno").click()');
  fixture.failures['/api/apply'] = { ok: false, message: '模拟保存失败' };
  await js('applySettings()'); await waitFor('$("#msg")?.textContent.includes("模拟保存失败")');
  await check('failed apply offers retry and does not report completion', '!$("#retry").hidden && !!$("#tasks")');
  delete fixture.failures['/api/apply'];
  await js('$("#retry").click()'); await waitFor('$("#retry").hidden');
  await js('clearTimers();S.mode="install";pageDone()'); await waitFor('!!$("#export-info")');
  await check('done masks password and requires explicit export', '$("#done-password").type === "password" && !$("#export-msg").textContent');
  assert.equal(fixture.calls.filter(c => c.path === '/api/done?export=1').length, 0); count++;
  await js('document.querySelector(".done-account").open=true;$("#export-info").click()'); await waitFor('$("#export-msg").textContent.includes("userdata")');
  await shot('done-explicit-export');
  await js('S.info.features={voice:true,memory:true};S.info.saved_keys=["deepseek","app_id","token","siliconflow"];pageKeys()');
  await check('unchanged enabled voice stays locked but is reusable without paid check', '$("#token").disabled && !$("#go").disabled');
  await js('pageProfile()');
  await check('enabled profile still has voice fee overlay', '$("#voice").disabled && !!$("#voice-review")');
  await shot('profile-voice-locked');
  await rpc('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  for (const page of ['pagePath', 'pageKeys', 'pageProfile', 'pageStatus', 'pageRescan']) {
    await js(`${page}()`); await pause(100);
    await check(`${page} mobile has no horizontal overflow`, 'document.documentElement.scrollWidth <= innerWidth');
  }
  await shot('mobile-rescan');
  await js('clearTimers()');
  assert.equal(errors.length, 0, JSON.stringify(errors)); count++;
  console.log(`PASS ${count} browser checks; screenshots: ${out}`);
}
main().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  if (rpc && ws.readyState === WebSocket.OPEN) { try { await rpc('Browser.close'); } catch {} }
  ws?.close(); server.closeAllConnections(); server.close();
  if (browser && browser.exitCode === null) browser.kill();
});
