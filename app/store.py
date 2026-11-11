"""安装状态（state.json）、key 加密保存、日志脱敏。"""
import base64
import copy
import ctypes
import json
import os
import threading
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import Iterable

from backend_lock import FileLock
from paths import state_path


_SAVE_LOCK = threading.RLock()
_MISSING = object()


class StateConflictError(RuntimeError):
    """本次修改与另一个后台修改了同一字段，拒绝静默覆盖。"""


def _merge(base, local, remote, path="state"):
    if local == base:
        return copy.deepcopy(remote) if remote is not _MISSING else _MISSING
    if remote == base or local == remote:
        return copy.deepcopy(local) if local is not _MISSING else _MISSING
    if isinstance(local, dict) and isinstance(remote, dict) and (isinstance(base, dict) or base is _MISSING):
        original = base if isinstance(base, dict) else {}
        result = {}
        for key in original.keys() | local.keys() | remote.keys():
            value = _merge(original.get(key, _MISSING), local.get(key, _MISSING),
                           remote.get(key, _MISSING), f"{path}.{key}")
            if value is not _MISSING:
                result[key] = value
        return result
    raise StateConflictError(f"状态已由另一个操作更新（{path}），请刷新后重试。")


def _read_state(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("安装状态必须是 JSON 对象")
    data.setdefault("done", [])
    data.setdefault("secrets", {})
    return data


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _crypt(fn, data: bytes) -> bytes:
    src, out = _blob(data), _Blob()
    # CRYPTPROTECT_UI_FORBIDDEN = 1：永远不弹窗
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    """用 Windows DPAPI 加密（只有当前 Windows 用户能解开）。"""
    return base64.b64encode(_crypt(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))).decode()


def unprotect(blob: str) -> str:
    return _crypt(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(blob)).decode("utf-8")


def redact(text: str, secrets: Iterable[str]) -> str:
    for s in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        text = text.replace(s, "***")
    return text


def app_home(home: Path | None = None) -> Path:
    """记「上次装在哪」的地方：%LOCALAPPDATA%\\DaFeiYu（一键包本身每次从临时目录运行）。"""
    return Path(home) if home else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DaFeiYu"


def remember_install(root: Path, home: Path | None = None) -> None:
    h = app_home(home)
    h.mkdir(parents=True, exist_ok=True)
    (h / "install.json").write_text(json.dumps({"root": str(root)}), encoding="utf-8")


def last_install(home: Path | None = None) -> str | None:
    try:
        return json.loads((app_home(home) / "install.json").read_text(encoding="utf-8")).get("root")
    except (OSError, ValueError):
        return None


class State:
    def __init__(self, root: Path, data: dict):
        self.root = Path(root)
        self.data = data
        self._baseline = copy.deepcopy(data)

    @classmethod
    def load(cls, root: Path) -> "State":
        path = state_path(Path(root))
        # 原子替换使只读加载无需创建目录或锁文件，也允许 resolve_mode 纯只读。
        with _SAVE_LOCK:
            data = _read_state(path)
        return cls(root, data)

    def save(self) -> None:
        path = state_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _SAVE_LOCK, FileLock(path.with_name(".state.lock")):
            local = copy.deepcopy(self.data)
            merged = _merge(self._baseline, local, _read_state(path))
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix="state.", suffix=".tmp", delete=False) as f:
                tmp = Path(f.name)
                json.dump(merged, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            try:
                for attempt in range(20):
                    try:
                        os.replace(tmp, path)
                        break
                    except PermissionError:  # 杀毒软件或读的人短暂占着文件
                        if attempt == 19:
                            raise
                        time.sleep(0.05)
            finally:
                tmp.unlink(missing_ok=True)
            # 保存期间的线程内修改仍属于下次要保存的增量。
            live = _merge(local, copy.deepcopy(self.data), merged)
            self.data.clear()
            self.data.update(live)
            self._baseline = copy.deepcopy(merged)

    def set_secret(self, name: str, value: str) -> None:
        self.data["secrets"][name] = protect(value)

    def get_secret(self, name: str) -> str:
        blob = self.data["secrets"].get(name)
        return unprotect(blob) if blob else ""

    def secret_values(self) -> list[str]:
        # list() 先拷一份键：安装线程在这里脱敏日志时，接口线程可能正往里存新的 key
        return [self.get_secret(n) for n in list(self.data["secrets"])]

    def reload_pids(self) -> dict:
        """重新从磁盘读 pids。

        安装向导和状态页是两个进程，各自起着服务、各自往 state.json 里写 pids。只信自己内存里
        那份的话，另一个窗口刚起的进程在这边看着像没起，页面就会显示「她下线了」。
        """
        try:
            with _SAVE_LOCK:
                data = State.load(self.root).data
                for key in ("pids", "processes"):
                    self.data[key] = copy.deepcopy(data.get(key, {}))
                    if key in data:
                        self._baseline[key] = copy.deepcopy(data[key])
                    else:
                        self._baseline.pop(key, None)
        except (OSError, ValueError):
            pass
        return self.data.get("pids", {})

    def mark_done(self, step: str) -> None:
        if step not in self.data["done"]:
            self.data["done"].append(step)
        self.save()

    def is_done(self, step: str) -> bool:
        return step in self.data["done"]
