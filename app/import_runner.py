"""Run the bundled third-party importer with this application's feature policy.

The vendor files remain unchanged. Voice connectivity/preview is an explicit UI
action; importing saved settings must never generate a paid sample again.
"""
import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path


def omit_build_meme_downloads(tree):
    """Omit the vendor's standalone meme section during build prewarming only.

    Keep the vendor source on disk intact. Fail if its structure changes, rather
    than accidentally suppressing a different installation step.
    """
    matches = 0
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or function.name != "main":
            continue
        for index, node in enumerate(function.body[:-1]):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == "step"
                    and node.value.args and isinstance(node.value.args[0], ast.Constant)
                    and str(node.value.args[0].value).startswith("下载表情包")):
                continue
            following = function.body[index + 1]
            expected = ast.parse('"meme_manager" in installed', mode="eval").body
            if not isinstance(following, ast.If) or ast.dump(following.test) != ast.dump(expected):
                raise ValueError("导入工具的表情包步骤已变化，无法安全跳过构建期下载。")
            function.body[index:index + 2] = ast.parse(
                'say("构建期不下载表情图片；用户安装时再获取。")').body
            matches += 1
    if matches != 1:
        raise ValueError("未找到唯一的表情包下载步骤，停止构建。")
    return ast.fix_missing_locations(tree)


def configure(module, answers: dict):
    # Use upstream HTTPS by default. The importer still honors an accelerator
    # explicitly configured in the user's meme plugin settings.
    module.GH_ACCELERATORS = [""]
    pack = json.loads((Path(module.PACK) / "settings/pack.json").read_text("utf-8-sig"))
    voice = answers.get("voice") == "3"
    memory = answers.get("memory") == "2"
    voice_ids = {value["id"] for value in pack["voice"].values()
                 if isinstance(value, dict) and "id" in value}
    skipped = []
    instances = []
    original_test = module.test_provider
    original_api = module.Api

    def test_provider(api, provider_id):
        if provider_id in voice_ids:
            skipped.append(provider_id)
            return True, "配置已保存；安装过程不生成试听。"
        return original_test(api, provider_id)

    class PolicyApi(original_api):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    module.Api = PolicyApi
    module.test_provider = test_provider
    original_say = module.say

    def say(message=""):
        if "试念" in message or "语音已打开，大约" in message:
            message = "  保存语音设置（不生成试听）"
        original_say(message)

    module.say = say

    def finish():
        if not instances:
            raise RuntimeError("导入工具没有建立后台连接。")
        api = instances[-1]
        response = api.call("GET", "/plugins")
        if not api.ok(response) or not isinstance(response.get("data"), list):
            raise RuntimeError("无法确认可选插件状态，请重试。")
        installed = {p.get("name") for p in response["data"] if isinstance(p, dict)}
        voice_ready = voice and dict(module.RESULTS).get("语音", False)
        for name, enabled in (("astrbot_plugin_dafeiyu_sing", voice_ready),
                              ("astrbot_plugin_livingmemory", memory)):
            # The vendor already checks memory provider connectivity. Do not
            # override its failure by re-enabling memory here.
            if name not in installed or (name.endswith("livingmemory") and enabled):
                continue
            result = api.call("PATCH", "/plugins/enabled", {"plugin_id": name, "enabled": enabled})
            module.RESULTS.append(("语音插件开关" if name.endswith("sing") else "记忆插件开关", api.ok(result)))
        if not memory:
            provider_id = pack["memory"]["siliconflow"]["id"]
            previous = module.provider_config(api, provider_id)
            if previous and previous.get("enable"):
                module.RESULTS.append(("关闭记忆模型", module.upsert_provider(api, {**previous, "enable": False})))

    return finish, skipped


def run(script: Path, answers_path: Path, result_path: Path, *, skip_memes=False) -> int:
    spec = importlib.util.spec_from_file_location("bundled_importer", script)
    module = importlib.util.module_from_spec(spec)
    fatal, skipped = None, []
    old_argv = sys.argv
    try:
        if skip_memes:
            tree = ast.parse(script.read_text("utf-8-sig"), filename=str(script))
            exec(compile(omit_build_meme_downloads(tree), str(script), "exec"), module.__dict__)
        else:
            spec.loader.exec_module(module)
        answers = json.loads(answers_path.read_text("utf-8"))
        if answers.get("voice") not in ("0", "3") or answers.get("memory") not in ("0", "2"):
            raise ValueError("不支持的可选服务设置。")
        finish, skipped = configure(module, answers)
        sys.argv = [str(script), "--answers", str(answers_path)]
        module.main()
        finish()
    except (Exception, SystemExit) as error:
        fatal = f"{type(error).__name__}: {error}"
    finally:
        sys.argv = old_argv
        results = [{"name": name, "ok": bool(ok)} for name, ok in getattr(module, "RESULTS", [])]
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps({"fatal": fatal, "results": results,
                                           "voice_test_skipped": skipped,
                                           "meme_downloads_skipped": bool(skip_memes)}, ensure_ascii=False), "utf-8")
    return 1 if fatal or any(not item["ok"] for item in results) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--skip-memes", action="store_true", help="仅构建预热使用，不下载表情图片")
    args = parser.parse_args()
    raise SystemExit(run(args.script, args.answers, args.result_json, skip_memes=args.skip_memes))
