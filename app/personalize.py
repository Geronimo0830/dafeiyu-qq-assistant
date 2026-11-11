"""第 3 页的个性化：写进配置包副本；再生成导入工具要的回答文件。"""
import json
from pathlib import Path

DEFAULT_NAME = "大肥鱼"
PERSONA = Path("persona") / "大肥鱼.md"
PACK_JSON = Path("settings") / "pack.json"


def enabled_features(data: dict | None = None) -> dict[str, bool]:
    """旧版已配置的安装保留能力，新安装默认不启用付费可选服务。"""
    data = data or {}
    saved = data.get("features")
    if isinstance(saved, dict):
        return {name: saved.get(name) is True for name in ("voice", "memory")}
    legacy = bool(data.get("keys_ok"))
    return {"voice": legacy, "memory": legacy}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def default_profile(pack_dir: Path) -> dict:
    pack = _read_json(pack_dir / PACK_JSON)
    return {
        "name": DEFAULT_NAME,
        "persona": (pack_dir / PERSONA).read_text(encoding="utf-8-sig"),
        "voice": pack["voice"]["doubao"]["persona"],
        "memes": {m["id"]: m.get("use", True) for m in pack["meme_packs"]},
    }


def fix_plugin_imports(astrbot_data: Path) -> None:
    """补上游插件漏打包的文件。

    astrbot_plugin_group_chat_plus 1.2.3 的 private_chat 子包写着 from ._session_guard import …，
    但发行包里那个目录只有 private_chat_session_guard.py（内容和 utils/_session_guard.py 一样），
    于是整个插件每次启动都加载失败。补一个转手文件就行，不改人家的代码。
    """
    utils = Path(astrbot_data) / "plugins" / "astrbot_plugin_group_chat_plus" / "private_chat" / "private_chat_utils"
    src, shim = utils / "private_chat_session_guard.py", utils / "_session_guard.py"
    if src.exists() and not shim.exists():
        shim.write_text("from .private_chat_session_guard import *  # 上游少打包了这个文件，见 fix_plugin_imports\n",
                        encoding="utf-8")


def validate_profile(profile: dict, *, voice_enabled: bool = True) -> str | None:
    if not isinstance(profile, dict):
        return "角色设置格式不正确。"
    for key in ("name", "persona", "voice"):
        if profile.get(key) is not None and not isinstance(profile[key], str):
            return "角色名字、性格和声音描述必须是文字。"
    if not str(profile.get("name") or "").strip():
        return "请输入角色名字。"
    if len(str(profile.get("name")).strip()) > 20:
        return "名字不能超过 20 个字。"
    if not str(profile.get("persona") or "").strip():
        return "性格描述不能是空的"
    if voice_enabled and not str(profile.get("voice") or "").strip():
        return "声音描述不能是空的"
    memes = profile.get("memes")
    if not isinstance(memes, dict) or any(type(v) is not bool for v in memes.values()):
        return "表情包设置格式不正确。"
    if not any(memes.values()):
        return "表情包至少留一套"
    return None


def apply_profile(pack_dir: Path, profile: dict, *, features: dict | None = None) -> None:
    voice_enabled = features is None or features.get("voice") is True
    if err := validate_profile(profile, voice_enabled=voice_enabled):
        raise ValueError(err)
    name = profile["name"].strip()
    voice = str(profile.get("voice") or "").strip()
    persona = profile["persona"].strip()
    memes = profile["memes"]

    persona = persona.replace(DEFAULT_NAME, name)
    if "{OWNER_QQ}" not in persona:
        # 导入工具靠这个占位写入主人 QQ；用户删了就补回来，不然她认不出主人
        persona += "\n\n主人的 QQ 号是 {OWNER_QQ}。消息里的 User ID 是这个号，才是主人本人。"
    (pack_dir / PERSONA).write_text(persona + "\n", encoding="utf-8")

    pack = _read_json(pack_dir / PACK_JSON)
    if voice:
        pack["voice"]["doubao"]["persona"] = voice
    first = True
    for m in pack["meme_packs"]:
        m["use"] = bool(memes.get(m["id"], False))
        # 主套必须是开着的那一套（导入工具把 default 那套设为默认规则的第一套）
        m["default"] = m["use"] and first
        first = first and not m["use"]
    (pack_dir / PACK_JSON).write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")


def write_answers(path: Path, *, base_url: str, username: str, password: str, owner_qq: str,
                  secrets_dir: Path, sf_key: str, app_id: str, token: str,
                  features: dict | None = None, test_voice: bool = False) -> None:
    """密码和 key 写成单独的小文件（导入工具的 *_file 用法），回答文件本身不含明文。调用方用完删 secrets_dir。"""
    secrets_dir.mkdir(parents=True, exist_ok=True)
    features = enabled_features({"features": features or {}})
    files = {}
    values = [("password", password)]
    if features["memory"]:
        values.append(("siliconflow_key", sf_key))
    if features["voice"]:
        values.append(("volc_access_token", token))
    for name, value in values:
        f = secrets_dir / f"{name}.txt"
        f.write_text(value, encoding="utf-8")
        files[f"{name}_file"] = str(f)
    answers = {"base_url": base_url, "username": username, "owner_qq": owner_qq,
               "memory": "2" if features["memory"] else "0",
               "voice": "3" if features["voice"] else "0", "test_voice": test_voice is True, **files}
    if features["voice"]:
        answers["volc_app_id"] = app_id
    path.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
