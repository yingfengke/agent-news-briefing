"""check_models.py - 逐个探测配置中的模型是否可用。

用途：区分「key 失效」「模型下线/改名」「免费模型受限」「限流」这几种失败，
避免只能从 "HTTP Error 400: Bad Request" 里猜。

用法：
  本地  python -m src.tools.check_models
  CI    手动触发 .github/workflows/model-health.yml

只发最小请求（chat 16 token / embedding 单条文本），不会产生实质费用。
"""
import json
import time
from urllib.request import Request, urlopen

from src import config
from src.core.http_utils import http_error_detail


def _post(url: str, payload: dict, api_key: str, timeout: int = 45) -> dict:
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _chat_endpoint(model: str):
    """主模型走 DeepSeek 官方，其余走通用网关；返回 (地址, 密钥, 附加参数)。"""
    if model == config.MODEL_NAME and config.MODEL_API_KEY:
        return (f"{config.MODEL_BASE_URL.rstrip('/')}/chat/completions",
                config.MODEL_API_KEY,
                {"thinking": {"type": "disabled"}})
    return (f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions",
            config.API_KEY, {})


def probe_chat(model: str) -> tuple[bool, str]:
    """探活一个 chat 模型。"""
    url, api_key, extra = _chat_endpoint(model)
    started = time.time()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：可用"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    body.update(extra)
    try:
        result = _post(url, body, api_key)
        text = (result["choices"][0]["message"].get("content") or "").strip()
        return True, f"{time.time() - started:5.1f}s 返回 {text[:24]!r}"
    except Exception as exc:
        return False, f"{time.time() - started:5.1f}s {http_error_detail(exc)}"


def probe_embedding(model: str) -> tuple[bool, str]:
    """探活 embedding 模型，并报告向量维度。"""
    started = time.time()
    try:
        result = _post(f"{config.API_BASE_URL.rstrip('/')}/v1/embeddings", {
            "model": model,
            "input": ["模型可用性探测"],
        }, config.API_KEY)
        vector = result["data"][0]["embedding"]
        return True, f"{time.time() - started:5.1f}s 维度 {len(vector)}"
    except Exception as exc:
        return False, f"{time.time() - started:5.1f}s {http_error_detail(exc)}"


def _print_row(kind: str, role: str, model: str, ok: bool, detail: str) -> None:
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {kind:9s} {role:12s} {model:32s} {detail}")


def main() -> int:
    if not config.API_KEY:
        print("未配置 API_KEY，无法探测")
        return 2

    print(f"主模型: {config.MODEL_NAME} @ "
          f"{config.MODEL_BASE_URL if config.MODEL_API_KEY else config.API_BASE_URL}")
    print(f"主模型密钥: {'已配置（独立）' if config.MODEL_API_KEY else '未配置，回落通用 API_KEY'}")
    print(f"通用网关: {config.API_BASE_URL}")
    print(f"通用密钥: {'已配置' if config.API_KEY else '未配置'}（长度 {len(config.API_KEY)}）")
    print("-" * 100)

    chat_models = [
        ("主模型", config.MODEL_NAME),
        ("简讯压缩", config.SUMMARY_MODEL_NAME),
        ("Twitter 精选", config.TWITTER_FILTER_MODEL_NAME),
    ]
    fallback = getattr(config, "FALLBACK_MODEL_NAME", "")
    if fallback:
        chat_models.insert(1, ("兜底模型", fallback))
    else:
        print("[SKIP] chat      兜底模型       未配置（默认已关闭）")
    embedding_models = [("语义去重", config.EMBEDDING_MODEL)]

    failures = 0
    seen: dict[str, bool] = {}

    for role, model in chat_models:
        ok, detail = probe_chat(model)
        _print_row("chat", role, model, ok, detail)
        if not ok:
            failures += 1
        seen[model] = ok

    for role, model in embedding_models:
        ok, detail = probe_embedding(model)
        _print_row("embedding", role, model, ok, detail)
        if not ok:
            failures += 1
        seen[model] = ok

    print("-" * 100)
    if failures:
        print(f"结论：{failures} 个模型不可用。若全部为免费模型而付费模型正常，"
              "请检查账号实名状态、免费模型政策或额度限制。")
    else:
        print("结论：全部模型可用")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
