"""Installation layout and copy-first migration; never erase legacy user data."""
import json
import os
import shutil
import uuid
from pathlib import Path

SCHEMA = 2
MARKER = "layout.json"
LEGAL_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "LICENSE_SCOPE.md")


def assert_owned_path(path: Path, root: Path) -> None:
    """Reject an escaping path or a link at any point before touching user files."""
    root, path = Path(root).absolute(), Path(path).absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError("操作路径不在安装目录内。")
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("目录含链接，已停止操作以保护外部数据。")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("操作路径不在安装目录内。")


def assert_plain_tree(path: Path) -> None:
    """Walk without following links, including Windows junctions."""
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("目录含链接，已停止操作以保护外部数据。")
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(current) / name
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise ValueError("目录含链接，已停止操作以保护外部数据。")


def is_separated(root: Path) -> bool:
    marker = Path(root) / MARKER
    if not marker.exists():
        return False
    data = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("product") != "dafeiyu-qq-assistant":
        raise ValueError("安装目录版本无法识别，请使用匹配的安装程序。")
    return True


def state_path(root: Path) -> Path:
    root = Path(root)
    return root / "userdata" / "state.json" if is_separated(root) else root / "state.json"


class Layout:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.separated = is_separated(root)
        self.program = self.root / "program" if self.separated else self.root
        self.data = self.root / "userdata" if self.separated else self.root
        self.runtime = self.program / "runtime" / "python"
        self.python = self.runtime / "python.exe"
        self.pythonw = self.runtime / "pythonw.exe"
        self.astrbot = self.program / "astrbot"
        self.astrbot_root = self.data / "astrbot" if self.separated else self.astrbot
        self.astrbot_data = self.astrbot_root / "data"
        self.napcat = self.program / "napcat"
        self.napcat_work = self.data / "napcat" if self.separated else self.root / "napcat-data"
        self.pack_defaults = self.program / "pack"
        self.pack = self.data / "pack" if self.separated else self.root / "pack"
        self.app = self.program / "app"
        self.logs = self.data / "logs"
        self.import_work = self.data / ".import"
        self.info_file = self.data / "我的信息.txt"
        self.state_file = self.data / "state.json"


def _write_marker(root: Path, **extra) -> None:
    tmp = root / f".layout-{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps({"schema": SCHEMA, "product": "dafeiyu-qq-assistant", **extra},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / MARKER)


def initialize_layout(root: Path) -> Layout:
    root = Path(root)
    # A valid product marker does not authorize following an existing junction.
    for candidate in (root / MARKER, root / "program", root / "userdata"):
        assert_owned_path(candidate, root)
    root.mkdir(parents=True, exist_ok=True)
    if not is_separated(root):
        if (root / "state.json").exists():
            raise ValueError("检测到旧安装，请先迁移数据。")
        _write_marker(root)
    layout = Layout(root)
    layout.program.mkdir(exist_ok=True)
    layout.data.mkdir(exist_ok=True)
    return layout


def _copy(source: Path, target: Path, *, ignore=None) -> None:
    if not source.exists():
        return
    assert_plain_tree(source)
    if source.is_dir():
        shutil.copytree(source, target, ignore=ignore)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare_layout(root: Path) -> Layout:
    """Prepare a new install or migrate a stopped legacy install without deleting originals."""
    root = Path(root)
    if is_separated(root):
        layout = initialize_layout(root)
        assert_plain_tree(layout.program)
        assert_plain_tree(layout.data)
        return layout
    if not (root / "state.json").exists():
        return initialize_layout(root)

    # Imports are local to avoid a paths/services/store import cycle.
    import services
    old_state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    if any(services.is_running(pid) for pid in old_state.get("pids", {}).values()):
        raise RuntimeError("旧版服务仍在运行，请先在旧版控制台停止服务，再重新打开安装程序。")
    if (root / "program").exists() or (root / "userdata").exists():
        raise RuntimeError("检测到未完成的目录迁移，请保留原文件并检查 program、userdata 目录。")

    stage = root / f".migration-{uuid.uuid4().hex}"
    program, data = stage / "program", stage / "userdata"
    program.mkdir(parents=True)
    data.mkdir()
    for name in ("runtime", "napcat", "app", "pack"):
        _copy(root / name, program / name)
    astrbot = root / "astrbot"
    _copy(astrbot, program / "astrbot", ignore=lambda current, names:
          ["data"] if Path(current) == astrbot else ["__pycache__"])
    for source, target in ((astrbot / "data", data / "astrbot/data"),
                           (root / "napcat-data", data / "napcat"),
                           (root / "pack", data / "pack"),
                           (root / "logs", data / "logs"),
                           (root / "我的信息.txt", data / "我的信息.txt")):
        _copy(source, target)
    old_state["pids"] = {}
    old_state.pop("processes", None)
    # Absolute paths inside old plugin settings are updated during the next import.
    old_state["done"] = [step for step in old_state.get("done", [])
                         if step not in {"configs", "astrbot", "napcat", "import", "shortcut", "login"}]
    (data / "state.json").write_text(json.dumps(old_state, ensure_ascii=False, indent=2), encoding="utf-8")
    moved = []
    try:
        for name in ("program", "userdata"):
            os.replace(stage / name, root / name)
            moved.append(name)
        _write_marker(root, migrated_from=1, legacy_files_retained=True)
    except Exception:
        for name in reversed(moved):
            os.replace(root / name, stage / name)
        raise
    # Empty staging directory only; original files remain available for recovery.
    stage.rmdir()
    return Layout(root)
