"""仅卸载本安装目录；共享 QQ 数据、其他安装和浏览器配置均保留。"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import checks
import services
import shortcut
from store import app_home

SHORTCUT_NAME = "启动大肥鱼"

# 参数以 JSON/base64 传入，不拼接为 PowerShell 代码。删除前再次验证目录及标记。
_PS = r"""
$ErrorActionPreference = 'Stop'
$spec = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SPEC__')) | ConvertFrom-Json
function Assert-PlainTree([string]$path) {
  $entry = Get-Item -LiteralPath $path -Force
  if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Directory links are not removed' }
  if ($entry.PSIsContainer) {
    foreach ($child in Get-ChildItem -LiteralPath $path -Force) { Assert-PlainTree $child.FullName }
  }
}
try {
  $deadline = [DateTime]::UtcNow.AddMinutes(2)
  while ($true) {
    $parentProcess = Get-Process -Id $spec.pid -ErrorAction SilentlyContinue
    if (!$parentProcess -or $parentProcess.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -ne $spec.created) { break }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'Application did not exit; no files removed' }
    Start-Sleep -Milliseconds 300
  }
  $target = [IO.Path]::GetFullPath($spec.root)
  if ($target -ne $spec.root -or $target -eq [IO.Path]::GetPathRoot($target)) { throw 'Invalid root' }
  $ancestor = $target
  while ($ancestor) {
    if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked root' }
    $ancestor = [IO.Path]::GetDirectoryName($ancestor)
  }
  if ((Get-FileHash -LiteralPath $spec.marker -Algorithm SHA256).Hash -ne $spec.marker_hash) { throw 'Installation marker changed' }
  Assert-PlainTree $target
  for ($attempt = 0; $attempt -lt 10; $attempt++) {
    try {
      Assert-PlainTree $target
      Remove-Item -LiteralPath $target -Recurse -Force
      break
    } catch {
      if (!(Test-Path -LiteralPath $target)) { break }
      if ($attempt -eq 9) { throw }
      Start-Sleep -Milliseconds 500
    }
  }
  if (Test-Path -LiteralPath $spec.remember) {
    $record = Get-Content -LiteralPath $spec.remember -Raw | ConvertFrom-Json
    if ($record.root -and [IO.Path]::GetFullPath($record.root) -eq $target) {
      Remove-Item -LiteralPath $spec.remember -Force
    }
  }
  Remove-Item -LiteralPath $spec.script -Force -ErrorAction SilentlyContinue
} catch {
  $_.Exception.Message | Set-Content -LiteralPath ($spec.script + '.error.txt') -Encoding UTF8
  exit 1
}
"""


def validate_root(root: Path) -> Path:
    root = Path(root).absolute()
    if checks.unsafe_location(root) or checks.has_link(root) or not checks.recognized_install(root):
        raise ValueError("无法确认这是本项目的安装目录，已停止卸载。")
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            child = Path(current) / name
            if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                raise ValueError("安装目录含文件或目录链接，请先移除链接后再卸载。")
    return root.resolve()


def leftovers(root: Path, state, home: Path | None = None) -> list[Path]:
    """卸载边界固定为经验证的安装根目录，不包括共享 QQ 和后台缓存。"""
    return [validate_root(root)]


def _remove_owned_shortcut(root: Path, desktop: Path | None) -> None:
    """同名快捷方式可能已属于另一个安装，只删除目标匹配的那份。"""
    link = shortcut.desktop_dir(desktop) / f"{SHORTCUT_NAME}.lnk"
    if not link.exists():
        return
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DF_LINK);"
              "if ([IO.Path]::GetFullPath($s.TargetPath) -eq [IO.Path]::GetFullPath($env:DF_TARGET)) "
              "{ Remove-Item -LiteralPath $env:DF_LINK -Force }")
    env = dict(os.environ, DF_LINK=str(link), DF_TARGET=str(services.Layout(root).pythonw))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                   capture_output=True, timeout=30, creationflags=services.CREATE_NO_WINDOW, check=True)


def uninstall(root: Path, state, home: Path | None = None, desktop: Path | None = None) -> Path:
    """验证边界、停服务，再由隐藏的系统 PowerShell 等后台退出后删除安装目录。"""
    root = validate_root(root)
    services.stop_all(state)
    identity = services.process_identity(os.getpid())
    if not identity:
        raise RuntimeError("无法确认当前进程，已停止卸载。")
    marker = root / "layout.json" if (root / "layout.json").exists() else root / "state.json"
    script = Path(tempfile.gettempdir()) / f"dafeiyu-uninstall-{uuid.uuid4().hex}.ps1"
    spec = {"root": str(root), "pid": os.getpid(), "created": str(identity["created"]),
            "marker": str(marker), "marker_hash": hashlib.sha256(marker.read_bytes()).hexdigest(),
            "remember": str(app_home(home) / "install.json"), "script": str(script)}
    encoded_spec = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
    text = _PS.replace("__SPEC__", encoded_spec)
    script.write_text(text, encoding="utf-8-sig")
    try:
        _remove_owned_shortcut(root, desktop)
    except (OSError, subprocess.SubprocessError):
        pass
    command = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                          "-EncodedCommand", command], cwd=script.parent, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=services.CREATE_NO_WINDOW | services.CREATE_NEW_PROCESS_GROUP)
    except Exception:
        script.unlink(missing_ok=True)
        raise
    return script
