"""安装路径、端口和三种 key 的检查。所有返回给用户的文字都是中文人话。"""
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from paths import is_separated, state_path

DEEPSEEK_BALANCE = "https://api.deepseek.com/user/balance"
SILICONFLOW_EMBED = "https://api.siliconflow.cn/v1/embeddings"
DOUBAO_TTS = "https://openspeech.bytedance.com/api/v3/tts/create"
DOUBAO_RESOURCE = "seed-audio-1.0"
DEFAULT_VOICE = "甜妹音：甜软轻盈的年轻成年女声，音调略高，语气活泼亲近，带一点俏皮和自然的撒娇感。咬字清楚，停顿轻巧，开心时尾音微微上扬；不尖锐、不刻意夹嗓，像熟悉的朋友轻声聊天。"


def default_install_path() -> str:
    return "D:\\DaFeiYu" if os.path.exists("D:\\") else "C:\\DaFeiYu"


def check_install_path(path: str, min_free_gb: float = 10) -> str | None:
    path = path or ""
    if not path:
        return "请选择安装位置"
    if not path.isascii() or any(c.isspace() for c in path):
        return "目录不能包含中文或空格，例如 D:\\DaFeiYu"
    if re.search(r'[\x00-\x1f\x7f% !&|<>^\"?*]', path):
        return "目录不能包含特殊符号，例如 D:\\DaFeiYu"
    p = Path(path)
    if not p.is_absolute() or not re.fullmatch(r"[A-Za-z]:", p.drive):
        return "请输入完整路径，例如 D:\\DaFeiYu"
    if any(part in (".", "..") or part.endswith((".", " ")) or ":" in part or
           re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
           for part in path.replace("/", "\\").split("\\")[1:] if part):
        return "目录名称无效，请使用简单的英文字母目录。"
    if unsafe_location(p):
        return "请选择独立的安装文件夹，不要选择磁盘根目录或系统、个人资料目录。"
    if has_link(p):
        return "安装目录不能是目录链接，请选择普通文件夹。"
    if p.exists():
        if not p.is_dir():
            return "该路径指向文件，请选择文件夹。"
        if any(p.iterdir()) and not recognized_install(p):
            return "目标目录已经有其他文件，请选择空文件夹。"
    probe = p
    while not probe.exists():
        if probe.parent == probe:
            return "目标磁盘不存在，请重新选择。"
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 1024**3
    if free_gb < min_free_gb:
        return f"磁盘可用空间为 {free_gb:.1f} GB，至少需要 {min_free_gb:g} GB，请选择其他磁盘。"
    return None


def has_link(path: Path) -> bool:
    """Check every ancestor, including dangling directory links."""
    return any(part.is_symlink() or getattr(part, "is_junction", lambda: False)()
               for part in (path, *path.parents))


def unsafe_location(path: Path) -> bool:
    path = path.absolute()
    protected = {Path(path.anchor), Path.home(), Path.home() / "Documents",
                 Path.home() / "Desktop", Path.home() / "Downloads"}
    system = [Path(os.environ[k]) for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")
              if os.environ.get(k)]
    if path in protected or any(path == p or path in p.parents for p in protected if p.anchor == path.anchor):
        return True
    return any(path == p or p in path.parents for p in system)


def recognized_install(root: Path) -> bool:
    """A random state.json must not turn someone else's folder into an install."""
    try:
        if is_separated(root):
            return all(not child.exists() or child.is_dir()
                       for child in (root / "program", root / "userdata"))
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
        return (isinstance(data, dict) and isinstance(data.get("done"), list)
                and isinstance(data.get("secrets"), dict)
                and (root / "app" / "main.py").is_file()
                and (root / "runtime" / "python" / "python.exe").is_file())
    except (OSError, ValueError, TypeError):
        return False


def _bindable(host: str, port: int) -> bool:
    # 只 bind 不 listen，不会触发防火墙弹窗
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def free_port(preferred: int) -> int:
    """Windows 上别人占着 0.0.0.0:p 时 127.0.0.1:p 仍能 bind，反之亦然，所以两个都试。"""
    port = preferred
    while port < 65535:
        if _bindable("127.0.0.1", port) and _bindable("0.0.0.0", port):
            return port
        port += 1
    raise RuntimeError("找不到空闲端口")


def _call(opener, url, *, headers=None, body=None, timeout=20):
    """发请求，返回 (status, dict)；网络不通时抛 URLError。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with opener(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {"raw": raw[:200].decode("utf-8", "replace")}


def check_deepseek(key: str, opener=urllib.request.urlopen) -> tuple[bool, str]:
    try:
        status, data = _call(opener, DEEPSEEK_BALANCE, headers={"Authorization": f"Bearer {key.strip()}"})
    except (urllib.error.URLError, OSError):
        return False, "连不上 DeepSeek，请检查网络连接。"
    if status in (401, 403):
        return False, "key 不对，请在 DeepSeek 开放平台核对或重新创建密钥。"
    if status != 200:
        return False, f"DeepSeek 返回了错误（{status}），请稍后重试"
    if not data.get("is_available"):
        return False, "DeepSeek 余额不足，请充值后重试。"
    infos = data.get("balance_infos") or [{}]
    return True, f"校验通过，余额 {infos[0].get('total_balance', '?')} 元"


def check_siliconflow(key: str, opener=urllib.request.urlopen) -> tuple[bool, str]:
    try:
        status, data = _call(opener, SILICONFLOW_EMBED, headers={"Authorization": f"Bearer {key.strip()}"},
                             body={"model": "BAAI/bge-m3", "input": "你好"})
    except (urllib.error.URLError, OSError):
        return False, "连不上硅基流动，请检查网络连接。"
    if status in (401, 403):
        return False, "key 不对，请在硅基流动控制台核对或重新创建密钥。"
    if status != 200 or not data.get("data"):
        return False, f"硅基流动返回了错误（{status}），请稍后重试"
    return True, "可以用"


def check_doubao(app_id: str, token: str, voice: str = DEFAULT_VOICE, text: str = "你好呀",
                 opener=urllib.request.urlopen) -> tuple[bool, str, str]:
    """用豆包念一句。成功时第三项是 mp3 的 base64；可能消耗额度或产生费用。"""
    headers = {
        "X-Api-App-Id": app_id.strip(),
        "X-Api-Access-Key": token.strip(),
        "X-Api-Resource-Id": DOUBAO_RESOURCE,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }
    prompt = f"{voice}，在QQ上给好朋友发语音，语气轻快自然，只说引号里的这句话，一字不差：“{text}”"
    body = {"model": DOUBAO_RESOURCE, "text_prompt": prompt,
            "audio_config": {"format": "mp3", "sample_rate": 24000, "enable_subtitle": True}}
    try:
        status, data = _call(opener, DOUBAO_TTS, headers=headers, body=body, timeout=60)
    except (urllib.error.URLError, OSError):
        return False, "连不上豆包语音，请检查网络连接。", ""
    blob = json.dumps(data, ensure_ascii=False)
    if "45000030" in blob or "not granted" in blob:
        return False, "语音服务尚未授权，请在火山引擎控制台检查模型权限、试用额度或服务开通状态。", ""
    if status in (401, 403):
        return False, "APP ID 或 Access Token 不对，请使用语音控制台凭证，而非火山方舟 API Key。", ""
    if status != 200 or not data.get("audio"):
        return False, f"豆包语音返回了错误（{status}），请稍后重试", ""
    return True, "可以用", data["audio"]
