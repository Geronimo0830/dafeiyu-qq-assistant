"""按安装目录互斥的后台锁；锁文件永不删除，避免删除后出现两把锁。"""
import hashlib
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path


class FileLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def acquire(self, timeout: float = 0) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(self.path, "a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file = stream
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    return False
                time.sleep(0.025)

    def release(self) -> None:
        stream, self._file = self._file, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self):
        if not self.acquire(timeout=10):
            raise TimeoutError(f"无法获得文件锁：{self.path}")
        return self

    def __exit__(self, *_exc):
        self.release()


def canonical_root(root: Path) -> str:
    return os.path.normcase(str(Path(root).resolve()))


def instance_url(path: Path, opener=urllib.request.urlopen) -> str | None:
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        port = int(info["port"])
        if not 0 < port < 65536 or not isinstance(info["token"], str):
            return None
        base = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(base + "/api/ping", data=b"{}", method="POST",
                                     headers={"X-Token": info["token"]})
        with opener(req, timeout=2):
            return f"{base}/?token={info['token']}"
    except (OSError, ValueError, KeyError, TypeError):
        return None


class BackendLock:
    def __init__(self, root: Path | None, home: Path | None = None):
        # 延迟导入：State 同样使用 FileLock。
        from store import app_home
        key = canonical_root(root) if root is not None else "bootstrap"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        directory = app_home(home) / "backends"
        self.path = directory / (digest + ".lock")
        self.metadata = directory / (digest + ".json")
        self.lock = FileLock(self.path)

    def try_acquire(self) -> bool:
        return self.lock.acquire()

    def publish(self, port: int, token: str) -> None:
        if self.lock._file is None:
            raise RuntimeError("发布后台地址前必须持有后台锁")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                         prefix=self.metadata.stem + ".", suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            json.dump({"port": port, "token": token, "pid": os.getpid()}, f)
        try:
            os.replace(tmp, self.metadata)
        finally:
            tmp.unlink(missing_ok=True)

    def existing_url(self) -> str | None:
        return instance_url(self.metadata)

    def release(self) -> None:
        if self.lock._file is not None:
            try:
                self.metadata.unlink(missing_ok=True)
            finally:
                self.lock.release()
