const { test } = require('node:test');
const { execFileSync } = require('node:child_process');
const path = require('node:path');

test('UI demo isolates paths and never invokes production lifecycle methods', () => {
  const script = String.raw`
import json
import tempfile
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch
from dev.fake_wizard import FakeApp, make_demo_server, STEP_TITLES
import services
import store
import uninstall

with tempfile.TemporaryDirectory(prefix="dafeiyu-demo-test-") as tmp:
    base = Path(tmp)
    external = base / "existing-install"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    sandbox = base / "sandbox"
    with patch.object(services, "start_astrbot", side_effect=AssertionError("real service")), \
         patch.object(services, "start_napcat", side_effect=AssertionError("real service")), \
         patch.object(services, "stop_all", side_effect=AssertionError("real stop")), \
         patch.object(services, "clear_qq_login", side_effect=AssertionError("real QQ mutation")), \
         patch.object(store.State, "load", side_effect=AssertionError("real state")), \
         patch.object(uninstall, "uninstall", side_effect=AssertionError("real uninstall")), \
         patch.object(FakeApp, "_start_tasks"):
        app = FakeApp(sandbox, "status")
        httpd = make_demo_server(app)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        def request(route, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}" + route,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"X-Token": app.token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        try:
            assert request("/api/info")["mode"] == "status"
            assert request("/api/status")["astrbot"] is True
            assert [key for key, _ in STEP_TITLES][2:6] == ["configs", "astrbot", "import", "napcat"]
            for route in ("stop", "start", "switch_qq", "quit", "uninstall", "apply", "retry", "refresh_qr"):
                assert request("/api/" + route, {})["ok"], route
            assert request("/api/path", {"path": str(external)})["ok"]
            assert app.root.is_relative_to(sandbox)
            assert sentinel.read_text(encoding="utf-8") == "keep"
            assert sorted(p.name for p in external.iterdir()) == ["keep.txt"]
            assert request("/api/keys", {"owner_qq": "12345678", "deepseek": "fake", "features": {"voice": False, "memory": False}})["ok"]
            assert request("/api/profile", app.profile)["ok"]
            assert not request("/api/preview_voice", {"voice_consent": True})["ok"]
            assert not request("/api/check", {"field": "doubao"})["ok"]
            assert "info_file" not in request("/api/done")
            exported = request("/api/done?export=1")
            assert Path(exported["info_file"]).is_relative_to(sandbox)
            assert "preview" in Path(exported["info_file"]).name
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
print("PASS isolated fake API routes, paths, exports and status mode")
`;
  process.stdout.write(execFileSync('python', ['-X', 'utf8', '-c', script], {
    cwd: path.resolve(__dirname, '../..'), encoding: 'utf8', windowsHide: true,
  }));
});
