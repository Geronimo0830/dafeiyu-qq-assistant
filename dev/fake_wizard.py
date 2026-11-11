"""Isolated UI demo: no real services, paid APIs, installers, shortcuts, or uninstall.

python dev/fake_wizard.py [--status] [--port 8765]
Use dummy credentials. Every written file stays under a fresh temporary directory.
"""
import argparse
import copy
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import personalize  # noqa: E402
import server  # noqa: E402

STEP_TITLES = [("extract", "解压程序文件"), ("ports", "准备本地连接"),
               ("configs", "保存连接设置"), ("astrbot", "启动聊天服务"),
               ("import", "配置角色与插件"), ("napcat", "启动 QQ 连接"),
               ("shortcut", "创建桌面快捷方式"), ("login", "等待 QQ 扫码登录")]


class FakeApp:
    """The demo owns only memory and its sandbox; it never calls the production App."""
    def __init__(self, sandbox: Path, mode="install"):
        self.sandbox = Path(sandbox).resolve()
        self.sandbox.mkdir(parents=True, exist_ok=True)
        self.mode, self.token = mode, secrets.token_urlsafe(16)
        self.root = self.sandbox / "DaFeiYu" if mode == "status" else None
        self.state = None
        self.quitting = False
        self.last_ping = time.monotonic()
        self.profile = personalize.default_profile(ROOT / "vendor" / "dafeiyu-config-pack")
        self.features = {"voice": False, "memory": False}
        self.owner_qq = "123456789" if mode == "status" else ""
        self.saved = {"deepseek"} if mode == "status" else set()
        self.ready = {"keys": mode == "status", "profile": mode == "status"}
        self.online = mode == "status"
        self.login_since = time.monotonic() - 10 if self.online else None
        self.lock = threading.RLock()
        self.thread = None
        self.waiting = None
        self.tasks = [{"key": key, "title": title, "status": "done" if self.online else "todo", "message": ""}
                      for key, title in STEP_TITLES]
        self.layout = SimpleNamespace(napcat_work=self.sandbox / "napcat-preview")
        qr = self.layout.napcat_work / "cache" / "qrcode.png"
        qr.parent.mkdir(parents=True, exist_ok=True)
        qr.write_bytes((ROOT / "app/web/img/favicon.png").read_bytes())
        if self.root:
            self.root.mkdir(exist_ok=True)

    def log_error(self, message):
        log = self.sandbox / "demo.log"
        # Demo logs never copy API request values or credentials.
        log.write_text("UI demo request failed.\n", encoding="utf-8")
        return log

    def handle_info(self, _q):
        return {"mode": self.mode, "default_path": "D:\\DaFeiYu", "root": str(self.root) if self.root else None,
                "profile": copy.deepcopy(self.profile), "owner_qq": self.owner_qq,
                "features": dict(self.features), "resume": dict(self.ready), "saved_keys": sorted(self.saved)}

    def handle_path(self, body):
        chosen = str(body.get("path", ""))
        if not chosen.isascii() or " " in chosen or len(chosen) < 4 or chosen[1:3] != ":\\":
            return {"ok": False, "message": "目录不能包含中文或空格，例如 D:\\DaFeiYu"}
        # The typed path is display input only. It is never opened or written.
        self.root = self.sandbox / "DaFeiYu"
        self.root.mkdir(exist_ok=True)
        self._start_tasks()
        return {"ok": True, "resume": dict(self.ready)}

    def handle_check(self, body):
        if body.get("field") == "doubao" and body.get("voice_consent") is not True:
            return {"ok": False, "message": "请先确认语音费用提示。"}
        time.sleep(0.2)
        bad = any("bad" in str(body.get(key, "")) for key in ("value", "app_id", "token"))
        return {"ok": not bad, "message": "模拟校验失败" if bad else "模拟校验通过（未请求外部服务）"}

    def handle_keys(self, body):
        self.features = {key: body.get("features", {}).get(key) is True for key in ("voice", "memory")}
        self.owner_qq = str(body.get("owner_qq", ""))
        for key in ("deepseek", "app_id", "token", "siliconflow"):
            if body.get(key):
                self.saved.add(key)
        self.ready["keys"] = True
        return {"ok": True}

    def handle_preview_voice(self, body):
        return {"ok": False, "message": "预览模式不调用语音服务。", "audio_b64": ""}

    def handle_profile(self, body):
        if err := personalize.validate_profile(body, voice_enabled=self.features["voice"]):
            return {"ok": False, "message": err}
        self.profile = copy.deepcopy(body)
        self.ready["profile"] = True
        return {"ok": True}

    def _start_tasks(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._run_tasks, daemon=True)
            self.thread.start()

    def _run_tasks(self):
        for task in self.tasks:
            if task["status"] == "done":
                continue
            task["status"] = "doing"
            required = {"configs": "keys", "import": "profile"}.get(task["key"])
            while required and not self.ready[required]:
                self.waiting = required
                time.sleep(0.1)
            self.waiting = None
            if task["key"] == "login":
                self.login_since = time.monotonic()
                time.sleep(8)
                self.online = True
            else:
                time.sleep(0.6)
            task["status"] = "done"

    def handle_progress(self, _q):
        with self.lock:
            return {"steps": copy.deepcopy(self.tasks), "running": bool(self.thread and self.thread.is_alive()),
                    "waiting": self.waiting, "finished": all(t["status"] == "done" for t in self.tasks)}

    def handle_retry(self, _body):
        self._start_tasks()
        return {"ok": True}

    def handle_login(self, _q):
        if self.login_since is None:
            status = "starting"
        else:
            dt = time.monotonic() - self.login_since
            status = "need_scan" if dt < 5 else "scanned" if dt < 8 else "online"
        return {"status": status, "error": ""}

    def handle_refresh_qr(self, _body):
        self.login_since = time.monotonic()
        return {"ok": True, "message": "预览二维码已刷新（不是实际 QQ 登录码）。"}

    def handle_done(self, query):
        data = {"dashboard_url": "http://127.0.0.1:6185", "username": "preview", "password": "preview-only",
                "qq": "100001", "ok": True}
        if (query.get("export") or [""])[0] == "1":
            target = self.sandbox / "preview-login.txt"
            target.write_text("Preview only: no real credentials.\n", encoding="utf-8")
            data["info_file"] = str(target)
        return data

    def handle_status(self, _q):
        return {"astrbot": self.online, "napcat": self.online, "starting": False,
                "login": self.handle_login({})["status"], "error": "", "qq": "100001"}

    def handle_start(self, _body):
        self.online = True
        return {"ok": True}

    def handle_stop(self, _body):
        self.online = False
        return {"ok": True}

    def handle_switch_qq(self, _body):
        self.online = False
        self.login_since = time.monotonic()
        return {"ok": True}

    def handle_uninstall(self, _body):
        self.online = False
        return {"ok": True, "message": "模拟卸载，未删除任何文件。"}

    def handle_quit(self, body):
        return self.handle_stop(body)

    def handle_apply(self, _body):
        for task in self.tasks:
            if task["key"] in ("configs", "astrbot", "import", "napcat"):
                task["status"] = "todo"
        self._start_tasks()
        return {"ok": True}

    def handle_ping(self, _body):
        self.last_ping = time.monotonic()
        return {"ok": True}


def make_demo_server(app, port=0):
    # Rebind dispatch, preserving production HTTP authentication/static serving.
    # Every handler is implemented above: no production lifecycle method is called.
    server.App.GET = {route: getattr(FakeApp, fn.__name__) for route, fn in server.App.GET.items()}
    server.App.POST = {route: getattr(FakeApp, fn.__name__) for route, fn in server.App.POST.items()}
    return server.make_server(app, port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    sandbox = Path(tempfile.mkdtemp(prefix="dafeiyu-ui-demo-"))
    app = FakeApp(sandbox, "status" if args.status else "install")
    httpd = make_demo_server(app, args.port)
    print(f"http://127.0.0.1:{httpd.server_port}/?token={app.token}", flush=True)
    print(f"模拟模式：不会启动真实服务；临时文件：{sandbox}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
