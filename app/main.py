"""大肥鱼 QQ 助手入口。

安装：pythonw app\\main.py            （自解压后从临时目录运行）
状态：pythonw app\\main.py --status --root D:\\DaFeiYu   （桌面快捷方式）
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
import installer  # noqa: E402
import services  # noqa: E402
from backend_lock import BackendLock, canonical_root, instance_url  # noqa: E402
from paths import state_path  # noqa: E402
from store import State, app_home, last_install  # noqa: E402

IDLE_EXIT_S = 20


def find_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.exists():
                return str(exe)
    return shutil.which("msedge")


def open_window(url: str, profile_dir: Path) -> None:
    edge = find_edge()
    if edge:
        # 独立的 Edge 配置目录：窗口没有地址栏，也不会和用户自己的 Edge 窗口混在一起
        subprocess.Popen([edge, f"--app={url}", "--window-size=1200,900", f"--user-data-dir={profile_dir}",
                          "--no-first-run", "--disable-features=Translate"])
    else:
        webbrowser.open(url)


def existing_instance(lock: Path) -> str | None:
    """兼容入口；锁的所有权由 BackendLock 验证。"""
    return instance_url(lock)


def installation_complete(root: Path) -> bool:
    if not state_path(root).exists():
        return False
    state = State.load(root)
    return bool(state.data.get("keys_ok") and state.data.get("profile")) and all(
        state.is_done(step.key) for step in installer.default_steps()) and installer.extracted_ok(root)


def resolve_mode(args, home: Path) -> tuple[str, Path | None]:
    """这次该开状态页还是安装向导。

    双击一键包时不带参数：装过就直接进状态页，别让人以为要重装一遍。桌面快捷方式带 --status。
    """
    if args.root:
        root = Path(args.root)
    else:
        last = last_install(home)
        root = Path(last) if last else None
    if root and state_path(root).exists():
        return ("status" if installation_complete(root) else "install"), root
    return "install", None


def window_files(mode: str, home: Path) -> tuple[Path, Path]:
    """安装页和状态页共享同一个浏览器配置；后台锁另按安装目录分配。"""
    return home / "wizard.lock", home / "edge"


def backend_busy(app) -> bool:
    for worker in (app.installer, getattr(app, "_starter", None)):
        if worker:
            progress = worker.progress()
            if progress["running"] and progress["waiting"] is None:
                return True
    if app.state is not None:
        return services.managed_services_running(app.state)
    return False


def start_initial_services(app) -> None:
    """只在后台首次启动时自动上线；重开窗口和返回状态页不改变服务状态。"""
    if app.mode == "status":
        app.handle_start({})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()

    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    mode, root = resolve_mode(args, home)
    _, edge_dir = window_files(mode, home)
    lease = BackendLock(root, home)
    # 另一个进程可能已持锁但尚未发布地址；等它就绪或退出后重新竞争。
    deadline = time.monotonic() + 15
    while not lease.try_acquire():
        if url := lease.existing_url():
            if not args.no_window:
                open_window(url, edge_dir)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("该安装目录的后台正在启动，请稍后重试。")
        time.sleep(0.1)

    leases = {canonical_root(root) if root else "bootstrap": lease}
    httpd = None
    serving = False
    try:
        app = server.App(mode, root=root)
        httpd = server.make_server(app, 0)
        port = httpd.server_address[1]

        def claim_backend(selected_root):
            key = canonical_root(selected_root)
            if key in leases:
                return
            selected = BackendLock(selected_root, home)
            if not selected.try_acquire():
                raise RuntimeError("该安装目录已有后台运行，请打开已有控制台后继续。")
            try:
                selected.publish(port, app.token)
            except Exception:
                selected.release()
                raise
            leases[key] = selected

        app.claim_backend = claim_backend
        lease.publish(port, app.token)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        serving = True
        start_initial_services(app)
        if not args.no_window:
            open_window(f"http://127.0.0.1:{port}/?token={app.token}", edge_dir)

        # 关闭界面只结束心跳；有服务或任务时后台继续拥有安装目录的锁。
        while True:
            time.sleep(2)
            if app.quitting:  # 点了「退出」或「卸载」，不用等心跳超时
                break
            if not backend_busy(app) and time.monotonic() - app.last_ping > IDLE_EXIT_S:
                break
    finally:
        if httpd is not None:
            if serving:
                httpd.shutdown()
            httpd.server_close()
        for held in leases.values():
            held.release()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # pythonw 没有控制台，崩在这里会静默消失；落到日志里才查得到
        import traceback
        h = app_home()
        h.mkdir(parents=True, exist_ok=True)
        with open(h / "wizard.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S 启动失败：\n") + traceback.format_exc() + "\n")
        raise
