"""维护者用：组装并打出 dist/大肥鱼 QQ 助手.exe。需要联网、Windows，中间文件全在 .tmp/build/。

python build/build.py [--skip-download] [--out dist]
"""
import argparse
import hashlib
import json
import os
import ast
import struct
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path, PurePosixPath

PYTHON = "3.12.10"
ASTRBOT = "4.29.3"
NAPCAT = "v4.18.41"
PYPI = "https://mirrors.aliyun.com/pypi/simple/"
URLS = {
    "python.zip": f"https://www.python.org/ftp/python/{PYTHON}/python-{PYTHON}-embed-amd64.zip",
    "get-pip.py": "https://bootstrap.pypa.io/get-pip.py",
    "7zr.exe": "https://www.7-zip.org/a/7zr.exe",
    "lzma.7z": "https://www.7-zip.org/a/lzma2501.7z",
}

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
WORK = ROOT / ".tmp" / "build"
DOWNLOADS = ROOT / "downloads"
sys.path.insert(0, str(ROOT / "app"))
from paths import LEGAL_FILES, assert_owned_path, assert_plain_tree  # noqa: E402


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_work_tree(path: Path, boundary: Path | None = None) -> None:
    """Only remove a checked child of the build workspace, never follow links."""
    boundary = Path(boundary or WORK).absolute()
    path = Path(path).absolute()
    if boundary == Path(boundary.anchor):
        raise ValueError("构建清理边界不能是磁盘根目录。")
    assert_owned_path(path, boundary)
    assert_plain_tree(path)
    if path.exists():
        shutil.rmtree(path)


def input_specs(dl: Path) -> list[dict]:
    specs = [{"path": dl / name, "source": url} for name, url in URLS.items()]
    specs += [
        {"path": DOWNLOADS / "astrbot-src.zip", "source": f"https://github.com/AstrBotDevs/AstrBot/releases/tag/v{ASTRBOT}"},
        {"path": DOWNLOADS / "astrbot.zip", "source": f"https://github.com/AstrBotDevs/AstrBot/releases/tag/v{ASTRBOT}"},
        {"path": DOWNLOADS / "napcat-node.zip", "source": f"https://github.com/NapNeko/NapCatQQ/releases/tag/{NAPCAT}"},
    ]
    return specs


def _check_input_file(path: Path) -> None:
    """Check format/required contents, not publisher authenticity or provenance."""
    if any(part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in (path, *path.parents)):
        raise ValueError("输入文件或目录不能是链接")
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            entries = archive_entries(archive)
            if bad := archive.testzip():
                raise ValueError(f"ZIP 校验失败：{bad}")
            names = {name.lower() for info, name in entries if not info.is_dir()}
        required = {
            "python.zip": {"python.exe", "pythonw.exe", "python312.dll", "python312._pth", "python312.zip", "license.txt"},
            "astrbot-src.zip": {"main.py", "requirements.txt", "license"},
            "astrbot.zip": {"index.html"},
            "napcat-node.zip": {"node.exe", "index.js"},
        }[path.name]
        if missing := required - names:
            raise ValueError("压缩包缺少必要文件：" + ", ".join(sorted(missing)))
    elif path.name == "7zr.exe":
        with path.open("rb") as stream:
            header = stream.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("不是有效的 Windows PE 程序")
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            if stream.read(4) != b"PE\0\0":
                raise ValueError("Windows PE 文件头缺失")
    elif path.name == "lzma.7z":
        with path.open("rb") as stream:
            header = stream.read(32)
        if len(header) != 32 or header[:6] != b"7z\xbc\xaf\x27\x1c":
            raise ValueError("不是有效的 7z 文件")
        if zlib.crc32(header[12:32]) != struct.unpack_from("<I", header, 8)[0]:
            raise ValueError("7z 文件头校验失败")
        offset, size = struct.unpack_from("<QQ", header, 12)
        if 32 + offset + size > path.stat().st_size:
            raise ValueError("7z 文件不完整")
    elif path.name == "get-pip.py":
        source = path.read_text("utf-8-sig")
        if not source.strip():
            raise ValueError("安装脚本为空")
        ast.parse(source, filename=path.name)  # Parse only; never execute during preflight.


def inspect_inputs(dl: Path) -> dict:
    rows = []
    for spec in input_specs(dl):
        path = spec["path"]
        item = {"file": path.name, "path": str(path.absolute()), "source": spec["source"]}
        try:
            if not path.is_file():
                raise FileNotFoundError("缺少文件")
            _check_input_file(path)
            item.update(status="ready", bytes=path.stat().st_size, sha256=file_sha256(path))
        except (OSError, ValueError, SyntaxError, zipfile.BadZipFile, RuntimeError) as error:
            item.update(status="missing" if isinstance(error, FileNotFoundError) else "invalid", error=str(error))
        rows.append(item)
    return {"format": 1, "ready": all(row["status"] == "ready" for row in rows),
            "versions": {"python": PYTHON, "astrbot": ASTRBOT, "napcat": NAPCAT},
            "verification": "format-and-required-files-only; sha256 is locally computed, not publisher verification",
            "inputs": rows}


def write_input_report(report: dict) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "input-manifest.json"
    assert_owned_path(path, WORK)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return path


def write_release_inputs(report: dict, destination: Path) -> None:
    """Publish provenance and hashes without the builder's absolute paths."""
    public = {**report, "inputs": [{k: v for k, v in row.items() if k != "path"}
                                   for row in report["inputs"]]}
    destination.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", "utf-8")


def copy_legal_files(source: Path, destination: Path, *, source_tree: bool = False) -> None:
    for name in LEGAL_FILES:
        original = source / ("docs/许可说明.md" if source_tree and name == "LICENSE_SCOPE.md" else name)
        if not original.is_file() or not original.stat().st_size:
            raise ValueError(f"缺少许可文件：{original}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in LEGAL_FILES:
        original = source / ("docs/许可说明.md" if source_tree and name == "LICENSE_SCOPE.md" else name)
        shutil.copy2(original, destination / name)


def sfx_config_text() -> str:
    return (HERE / "sfx_config.txt").read_text(encoding="utf-8")


def apply_sfx_manifest(stub: Path) -> None:
    """Mark the SDK stub as an ordinary user process, avoiding UAC heuristics."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    begin = kernel.BeginUpdateResourceW
    begin.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    begin.restype = wintypes.HANDLE
    update = kernel.UpdateResourceW
    update.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    update.restype = wintypes.BOOL
    end = kernel.EndUpdateResourceW
    end.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    end.restype = wintypes.BOOL
    manifest = (HERE / "installer.manifest").read_bytes()
    handle = begin(str(stub), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        payload = ctypes.create_string_buffer(manifest)
        if not update(handle, 24, 1, 0, payload, len(manifest)):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        end(handle, True)
        raise
    if not end(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


def write_sfx(dl: Path, out: Path) -> Path:
    run([dl / "7zr.exe", "e", dl / "lzma.7z", f"-o{WORK}", "bin/7zSD.sfx", "-y"])
    stub = WORK / "7zSD.sfx"
    apply_sfx_manifest(stub)
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "大肥鱼 QQ 助手.exe"
    incomplete = exe.with_suffix(".exe.part")
    assert_owned_path(incomplete, out)
    with open(incomplete, "wb") as output:
        output.write(stub.read_bytes())
        output.write(sfx_config_text().encode("utf-8"))
        with open(WORK / "boot.7z", "rb") as archive:
            shutil.copyfileobj(archive, output)
    os.replace(incomplete, exe)
    return exe


def scan_for_secrets(root: Path, needles: list[str]) -> list[Path]:
    """返回含任一敏感串的 json 文件。"""
    needles = [n for n in needles if n]
    return sorted(p for p in Path(root).rglob("*.json")
                  if any(n in p.read_text(encoding="utf-8", errors="ignore") for n in needles))


def download(dl: Path, skip: bool) -> None:
    dl.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        if (dl / name).exists() or skip:
            continue
        print("下载", url)
        tmp = dl / (name + ".part")
        assert_owned_path(tmp, dl)
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            tmp.replace(dl / name)
        except OSError as error:
            print(f"下载未完成：{name}：{error}")
        finally:
            tmp.unlink(missing_ok=True)


def archive_entries(z: zipfile.ZipFile) -> list:
    entries = []
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (path.is_absolute() or any(p in (".", "..") or ":" in p or p.endswith((".", " "))
                                      for p in name.rstrip("/").split("/"))
                or "\x00" in name or stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError(f"不安全的压缩包路径：{info.filename}")
        entries.append((info, name))
    names = [n for _, n in entries if n.strip("/")]
    tops = {n.split("/", 1)[0] for n in names}
    strip = len(tops) == 1 and all("/" in n for n in names)
    targets = []
    seen = set()
    for info, name in entries:
        rel = name.split("/", 1)[1] if strip else name
        if not rel or info.is_dir():
            continue
        key = rel.casefold()
        if key in seen:
            raise ValueError(f"压缩包路径重复：{name}")
        seen.add(key)
        targets.append((info, rel))
    return targets


def unzip(src: Path, dest: Path) -> None:
    """先验证所有条目，再解压；拒绝越界路径和链接。"""
    with zipfile.ZipFile(src) as z:
        targets = [(info, dest / rel) for info, rel in archive_entries(z)]
        for _, out in targets:
            assert_owned_path(out, dest)
        for info, out in targets:
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as s, open(out, "wb") as d:
                shutil.copyfileobj(s, d)


def run(argv: list, **kw) -> None:
    print(">", " ".join(map(str, argv)))
    subprocess.run([str(a) for a in argv], check=True, **kw)


def stage_python(dl: Path, py_dir: Path) -> None:
    unzip(dl / "python.zip", py_dir)
    pth = next(py_dir.glob("python3*._pth"))
    lines = [l for l in pth.read_text(encoding="utf-8").splitlines() if l.strip() != "#import site"]
    # ._pth 模式下脚本所在目录不进 sys.path，AstrBot 的 main.py 要 import 同级模块
    pth.write_text("\n".join(lines + ["Lib\\site-packages", "..\\..\\astrbot", "import site"]) + "\n",
                   encoding="utf-8")
    # ._pth 也让 pip 的隔离构建环境找不到 setuptools；用户机器上 AstrBot 装插件依赖同样会撞上，所以写进 site 级 pip.ini
    # pip 对 no-* 选项的配置值是反的：false 才是「关掉隔离」
    (py_dir / "pip.ini").write_text("[global]\nno-build-isolation = false\n", encoding="utf-8")
    run([py_dir / "python.exe", dl / "get-pip.py", "-i", PYPI, "--no-warn-script-location", "setuptools", "wheel"])


def prepare_sources(stage: Path, dl: Path) -> None:
    from paths import initialize_layout
    layout = initialize_layout(stage)
    stage_python(dl, layout.python.parent)
    unzip(DOWNLOADS / "astrbot-src.zip", layout.astrbot)
    unzip(DOWNLOADS / "astrbot.zip", layout.astrbot / "data" / "dist")
    unzip(DOWNLOADS / "napcat-node.zip", layout.napcat)
    shutil.copytree(ROOT / "vendor" / "dafeiyu-config-pack", layout.pack_defaults)
    shutil.copytree(layout.pack_defaults, layout.pack)
    shutil.copytree(ROOT / "app", layout.app, ignore=shutil.ignore_patterns("__pycache__"))
    copy_legal_files(ROOT, stage, source_tree=True)
    copy_runtime_licenses(stage)


def copy_runtime_licenses(stage: Path) -> None:
    from paths import Layout
    source = HERE / "licenses"
    if not source.is_dir():
        raise ValueError("缺少第三方运行时许可目录 build/licenses。")
    assert_plain_tree(source)
    destination = Layout(stage).program / "licenses"
    assert_owned_path(destination, stage)
    assert_plain_tree(destination)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def install_requirements(stage: Path) -> None:
    from paths import Layout
    layout = Layout(stage)
    run([layout.python, "-m", "pip", "install", "-i", PYPI, "-r", layout.astrbot / "requirements.txt",
         "--no-warn-script-location"])


def assemble(stage: Path, dl: Path) -> None:
    prepare_sources(stage, dl)
    install_requirements(stage)


def _checkpoint(report: dict, phase: str) -> None:
    value = {"phase": phase, "inputs": {item["file"]: item["sha256"] for item in report["inputs"]}}
    temporary = WORK / "build-progress.tmp"
    temporary.write_text(json.dumps(value, indent=2), "utf-8")
    os.replace(temporary, WORK / "build-progress.json")


def write_dependency_manifest(stage: Path) -> None:
    """Record the packages actually installed, without embedding local file paths."""
    from paths import Layout
    layout = Layout(stage)
    target = layout.program / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    script = (
        "import importlib.metadata as m,json; out=[]\n"
        "for d in m.distributions():\n"
        " out.append({'name':d.metadata['Name'],'version':d.version,"
        "'license_expression':d.metadata.get('License-Expression',''),"
        "'license_classifiers':[v for v in d.metadata.get_all('Classifier',[]) if v.startswith('License ::')],"
        "'license_files':[str(p) for p in (d.files or []) if p.name.lower().startswith(('license','copying','notice'))],"
        "'project_urls':d.metadata.get_all('Project-URL',[])})\n"
        "print(json.dumps(sorted(out,key=lambda x:x['name'].lower()),ensure_ascii=False,indent=2))\n"
    )
    result = subprocess.run([str(layout.python), "-X", "utf8", "-c", script], check=True,
                            capture_output=True, text=True, encoding="utf-8")
    json.loads(result.stdout)  # Refuse an incomplete or unexpected report.
    (target / "python-dependencies.json").write_text(result.stdout, "utf-8")
    frozen = subprocess.run([str(layout.python), "-m", "pip", "freeze", "--all"], check=True,
                            capture_output=True, text=True, encoding="utf-8")
    (target / "python-requirements-lock.txt").write_text(frozen.stdout, "utf-8")


def build_stages(stage: Path, dl: Path, out: Path, report: dict, *, resume: bool = False) -> Path:
    """Resume only checkpoints produced with the same validated input files."""
    from paths import Layout
    checkpoint = WORK / "build-progress.json"
    phase = "new"
    if resume:
        if not checkpoint.is_file() or not stage.is_dir():
            raise ValueError("没有可继续的构建记录，请去掉 --resume 从头构建。")
        previous = json.loads(checkpoint.read_text("utf-8"))
        expected = {item["file"]: item["sha256"] for item in report["inputs"]}
        if previous.get("inputs") != expected or previous.get("phase") not in {"sources", "assembled", "clean"}:
            raise ValueError("构建输入已变化或记录无效，不能复用旧构建目录。")
        assert_owned_path(stage, WORK)
        assert_plain_tree(stage)
        phase = previous["phase"]
    if phase == "new":
        from store import State
        import services
        services.stop_all(State.load(WORK / "state"))
        remove_work_tree(stage)
        prepare_sources(stage, dl)
        _checkpoint(report, "sources")
        phase = "sources"
    else:
        # Our own app and license wording may change while dependencies stay valid.
        layout = Layout(stage)
        assert_owned_path(layout.app, stage)
        assert_plain_tree(layout.app)
        shutil.copytree(ROOT / "app", layout.app, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        copy_legal_files(ROOT, stage, source_tree=True)
        copy_runtime_licenses(stage)
    if phase == "sources":
        install_requirements(stage)
        _checkpoint(report, "assembled")
        phase = "assembled"
    needles = []
    if phase == "assembled":
        needles = prewarm(stage)
        write_dependency_manifest(stage)
    clean(stage, needles)
    _checkpoint(report, "clean")
    return package(stage, dl, out)


def prewarm(stage: Path) -> list[str]:
    """准备插件与依赖，不再分发表情图片。返回要扫的构建期敏感串。"""
    import configs
    import personalize
    import services
    from store import State
    layout = services.Layout(stage)
    state = State.load(WORK / "state")
    services.stop_all(state)  # Resume after an interrupted prewarm without duplicating its service.
    work = WORK / "import"
    ports, secrets = configs.pick_ports(), configs.new_secrets()
    configs.write_astrbot_config(layout.astrbot_data, ports=ports, secrets=secrets, deepseek_key="sk-build")
    services.start_astrbot(layout, state)
    try:
        url = f"http://127.0.0.1:{ports['dashboard']}"
        if not services.wait_http(url, 300):
            raise SystemExit("AstrBot 没起来，看 " + str(layout.logs))
        answers, result = work / "answers.json", work / "result.json"
        work.mkdir(parents=True, exist_ok=True)
        personalize.write_answers(answers, base_url=url, username=configs.DASHBOARD_USER,
                                  password=secrets["dashboard_password"], owner_qq="10000",
                                  secrets_dir=work / "s", sf_key="", app_id="build-app", token="build-token",
                                  features={"voice": True, "memory": False}, test_voice=False)
        run([layout.python, "-X", "utf8", layout.app / "import_runner.py",
             "--script", layout.pack / "tools" / "import_dafeiyu.py",
             "--answers", answers, "--result-json", result, "--skip-memes"])
        res = json.loads(result.read_text(encoding="utf-8"))
        bad = [x["name"] for x in res.get("results", []) if not x["ok"]]
        if res.get("fatal") or bad:
            raise SystemExit(f"导入工具失败：{res.get('fatal') or bad}")
    finally:
        try:
            services.stop(state, "astrbot")
        finally:
            remove_work_tree(work / "s")
    return ["sk-build", "build-app", "build-token", *secrets.values()]


def clean(stage: Path, needles: list[str]) -> None:
    from paths import Layout
    layout = Layout(stage)
    data = layout.astrbot_data
    (data / "cmd_config.json").unlink(missing_ok=True)
    # -wal/-shm 是 SQLite 的伴生文件，里头留着还没并回主库的页，同样是预热期的数据
    for p in list(data.glob("*.db")) + list(data.glob("*.db-wal")) + list(data.glob("*.db-shm")):
        p.unlink()
    for d in ("temp", "logs"):
        remove_work_tree(data / d, stage)
    # Prewarm-generated plugin state, backup paths, telemetry IDs, download
    # caches and empty databases belong to this build, not to new users.
    remove_work_tree(data / "plugin_data", stage)
    remove_work_tree(data / "knowledge_base", stage)
    meme_config = data / "config" / "meme_manager_config.json"
    if meme_config.is_file():
        value = json.loads(meme_config.read_text("utf-8-sig"))
        value.setdefault("community", {})["github_accelerator_url"] = ""
        meme_config.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    for p in list(stage.rglob("__pycache__")):
        remove_work_tree(p, stage)
    remove_work_tree(layout.logs, stage)
    remove_work_tree(layout.import_work, stage)
    layout.state_file.unlink(missing_ok=True)
    layout.info_file.unlink(missing_ok=True)
    leaks = scan_for_secrets(stage, needles)
    if leaks:
        raise SystemExit("stage 里还有敏感串：\n" + "\n".join(map(str, leaks)))


def package(stage: Path, dl: Path, out: Path) -> Path:
    from paths import Layout
    layout = Layout(stage)
    seven = dl / "7zr.exe"
    boot = WORK / "boot"
    if not (layout.program / "licenses").is_dir():
        raise ValueError("缺少第三方运行时许可目录。")
    for name in LEGAL_FILES:
        if not (stage / name).is_file() or not (stage / name).stat().st_size:
            raise ValueError(f"缺少许可文件：{stage / name}")
    remove_work_tree(boot)
    for p in (WORK / "payload.7z", WORK / "boot.7z"):
        assert_owned_path(p, WORK)
        p.unlink(missing_ok=True)
    run([seven, "a", WORK / "payload.7z", f"{stage}\\*", "-mx=7"])
    shutil.copytree(layout.runtime, boot / "runtime" / "python",
                    ignore=lambda d, names: ["site-packages"] if Path(d).name == "Lib" else [])
    shutil.copytree(layout.app, boot / "app")
    copy_legal_files(stage, boot)
    shutil.copytree(layout.program / "licenses", boot / "licenses")
    # 向导第 1 页就要读配置包算默认人设，boot 阶段还没解 payload，所以 pack 得带一份（只有 1 MB）
    shutil.copytree(layout.pack_defaults, boot / "pack")
    shutil.copy2(seven, boot / "7zr.exe")
    shutil.move(str(WORK / "payload.7z"), boot / "payload.7z")
    run([seven, "a", WORK / "boot.7z", f"{boot}\\*", "-mx=1"])
    return write_sfx(dl, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--resume", action="store_true", help="复用相同输入的构建记录，只重试未完成阶段")
    ap.add_argument("--check-inputs", action="store_true", help="只检查本地构建输入，不联网、不启动服务")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()
    dl, stage = WORK / "dl", WORK / "stage"
    if not args.check_inputs:
        download(dl, args.skip_download)
    report = inspect_inputs(dl)
    report_path = write_input_report(report)
    for item in report["inputs"]:
        print(f"[{item['status']}] {item['path']}" + (f"：{item['error']}" if "error" in item else ""))
    print(f"输入记录：{report_path}（格式检查与本地 SHA-256，不等于官方真实性验证）")
    if not report["ready"]:
        raise SystemExit("构建输入缺失或无效，未清理旧构建目录。")
    if args.check_inputs:
        return
    exe = build_stages(stage, dl, Path(args.out), report, resume=args.resume)
    digest = file_sha256(exe)
    (exe.parent / (exe.name + ".sha256")).write_text(f"{digest}  {exe.name}\n", "utf-8")
    write_release_inputs(report, exe.parent / "input-manifest.json")
    print(f"{exe}  {exe.stat().st_size / 1024 / 1024:.1f} MB  sha256={digest}")


if __name__ == "__main__":
    main()
