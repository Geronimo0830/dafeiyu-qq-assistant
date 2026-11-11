"""拉起 / 结束 AstrBot 和 NapCat，读 NapCat 的登录状态和二维码。"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from ctypes import wintypes
from paths import Layout, assert_owned_path, assert_plain_tree

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _spawn(name: str, argv: list[str], cwd: Path, env_extra: dict, layout: Layout, state) -> int:
    layout.logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **env_extra}
    # 子进程直接写日志文件：向导窗口关掉后它们还要接着跑，不能挂在向导的管道上
    with open(layout.logs / f"{name}.log", "ab") as log:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT,
                                creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
    state.reload_pids()  # 别把另一个窗口刚起的进程从 state.json 里冲掉
    state.data.setdefault("pids", {})[name] = proc.pid
    state.data.setdefault("processes", {})[name] = process_identity(proc.pid) or {}
    state.save()
    return proc.pid


def start_astrbot(layout: Layout, state) -> int:
    layout.astrbot_root.mkdir(parents=True, exist_ok=True)
    argv = [str(layout.python), str(layout.astrbot / "main.py")]
    dist = layout.astrbot / "data" / "dist"
    if dist.exists():
        argv += ["--webui-dir", str(dist)]
    return _spawn("astrbot", argv, layout.astrbot_root,
                  {"ASTRBOT_ROOT": str(layout.astrbot_root), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                  layout, state)


def start_napcat(layout: Layout, state, quick_qq: str | None) -> int:
    argv = [str(layout.napcat / "node.exe"), str(layout.napcat / "index.js")]
    if quick_qq:
        argv += ["-q", str(quick_qq)]
    return _spawn("napcat", argv, layout.napcat, {"NAPCAT_WORKDIR": str(layout.napcat_work)}, layout, state)


def is_running(pid: int | None) -> bool:
    if not pid:
        return False
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def process_identity(pid: int) -> dict | None:
    """A PID alone is not an identity: Windows reuses it after process exit."""
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                            ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = k32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        exe = ctypes.create_unicode_buffer(size.value)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.QueryFullProcessImageNameW(handle, 0, exe, ctypes.byref(size)):
            return None
        if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return {"exe": os.path.normcase(os.path.realpath(exe.value)),
                "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
    finally:
        k32.CloseHandle(handle)


def service_running(state, name: str) -> bool:
    pid = state.data.get("pids", {}).get(name)
    expected = state.data.get("processes", {}).get(name)
    return bool(pid and expected and is_running(pid) and process_identity(pid) == expected)


def managed_services_running(state) -> bool:
    state.reload_pids()
    return any(service_running(state, name) for name in ("astrbot", "napcat"))


def stop(state, name: str) -> None:
    state.reload_pids()  # 同上：先并上盘里的，只删自己要停的那个
    pid = state.data.get("pids", {}).get(name)
    if pid and is_running(pid):
        if not service_running(state, name):
            raise RuntimeError(f"无法确认 {name} 的进程归属，已停止操作以保护其他程序。请先手动关闭旧版服务。")
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                creationflags=CREATE_NO_WINDOW)
        if result.returncode != 0 and service_running(state, name):
            raise RuntimeError(f"{name} 未能停止，请检查权限后重试。")
    state.data.setdefault("pids", {}).pop(name, None)
    state.data.setdefault("processes", {}).pop(name, None)
    state.save()


def stop_all(state) -> None:
    state.reload_pids()
    for name in list(state.data.get("pids", {})):
        stop(state, name)


def tencent_roots(layout: Layout) -> list[Path]:
    """找用户的 QQ 数据目录（……\\Tencent Files）。

    默认在「我的文档」下，但 QQ 允许改到其他磁盘。改过的位置记在
    QQ 自己的 mmkv 里，不好读；NapCat 跑起来后日志里会写出完整路径，从那儿捞最省事。
    """
    roots = []
    docs = Path.home() / "Documents" / "Tencent Files"
    if docs.is_dir():
        roots.append(docs)
    log = layout.logs / "napcat.log"
    if log.exists():
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for m in re.finditer(r"([A-Za-z]:\\(?:[^\\\r\n\"',]+\\)*Tencent Files)\\", text):
            p = Path(m.group(1))
            if p.is_dir() and p not in roots:
                roots.append(p)
    return roots


def forget_qq_account(layout: Layout, qq: str, owner_qq: str = "") -> None:
    """Compatibility hook: shared QQ client directories are never owned by this app."""
    return


def clear_qq_login(layout: Layout, state) -> None:
    """清除本助手的账号选择和缓存；QQ 客户端自己的登录与聊天数据保留。"""
    assert_owned_path(layout.napcat_work, layout.root)
    assert_plain_tree(layout.napcat_work)
    stop(state, "napcat")
    state.data.pop("qq", None)
    state.save()
    shutil.rmtree(layout.napcat_work / "cache", ignore_errors=True)
    cfg = layout.napcat_work / "config"
    for path in list(cfg.glob("napcat_*.json")) + list(cfg.glob("onebot11_*.json")):
        path.unlink(missing_ok=True)
    # Starting without -q requests interactive login; do not erase external QQ history.


def wait_http(url: str, timeout_s: float, opener=urllib.request.urlopen, interval: float = 1.0) -> bool:
    """等到这个地址有 HTTP 响应（哪怕是 4xx）就算服务起来了。"""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with opener(url, timeout=5):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


class NapCatWeb:
    """NapCat WebUI 接口（只用登录相关的几个）。返回格式 {code: 0|-1, data, message}，HTTP 都是 200。"""

    def __init__(self, base_url: str, token: str, opener=urllib.request.urlopen):
        self.base = base_url.rstrip("/") + "/api"
        self.token = token
        self.opener = opener
        self.credential = None
        self.last_error = ""

    def _post(self, path: str, body: dict | None = None, auth: bool = True) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body or {}).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.credential}")
        with self.opener(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    def login(self) -> None:
        r = self._post("/auth/login", {"hash": hashlib.sha256((self.token + ".napcat").encode()).hexdigest()},
                       auth=False)
        if r.get("code") != 0:
            raise RuntimeError(f"NapCat WebUI 登录失败：{r.get('message')}")
        self.credential = r["data"]["Credential"]

    def call(self, path: str, body: dict | None = None):
        if not self.credential:
            self.login()
        r = self._post(path, body)
        if r.get("code") != 0 and "Unauthorized" in str(r.get("message")):
            # 凭证一小时过期，重新登录一次
            self.login()
            r = self._post(path, body)
        if r.get("code") != 0:
            raise RuntimeError(str(r.get("message")))
        return r.get("data")

    def status(self) -> str:
        """starting / need_scan / scanned / online / offline / error；出错原因留在 self.last_error"""
        try:
            d = self.call("/QQLogin/CheckLoginStatus") or {}
        except (urllib.error.URLError, OSError, RuntimeError, ValueError):
            return "starting"
        self.last_error = str(d.get("loginError") or "")
        if d.get("isLogin"):
            return "online"
        if d.get("isOffline"):
            return "offline"
        if d.get("loginPhase") == "qrcode_scanned":
            return "scanned"
        if d.get("qrcodeurl"):
            return "need_scan"
        if d.get("loginError"):
            return "error"
        return "starting"

    def refresh_qr(self) -> None:
        self.call("/QQLogin/RefreshQRcode")

    def login_uin(self) -> str | None:
        try:
            uin = (self.call("/QQLogin/GetQQLoginInfo") or {}).get("uin")
        except Exception:
            return None
        return str(uin) if uin else None


def qrcode_png(layout: Layout) -> bytes | None:
    path = layout.napcat_work / "cache" / "qrcode.png"
    return path.read_bytes() if path.exists() else None
