"""summarize.py - 正文与简讯的拆分，以及简讯压缩。

设计：模型输出多少条就保留多少条，不做丢弃式截断。
  1. 正文展示条数有上限（config.MAX_NEWS_ITEMS）；
  2. 超出上限的条目按「优先让出名额」规则挤出正文——「其他动态」分类
     先让位，由待展示区里分数更高的非其他动态条目替补；
  3. 未进正文的条目交给轻量模型压成一句话简讯，单独成区块展示。

轻量模型调用是 best-effort：超时、限流、返回格式错误一律降级为
「摘要截断」，绝不阻断简报生成。
"""
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src import config
from src.core.logger import get_logger
from src.core.http_utils import http_error_detail

log = get_logger("analysis.summarize")

OTHER_CATEGORY = "其他动态"
_BRIEF_MAX_CHARS = 40


def _score(item) -> float:
    try:
        return float(item.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def split_display_items(items: list[dict], limit: int | None = None):
    """把条目拆成「正文」与「简讯」两部分。

    正文按评分降序取前 limit 条；若正文中混入了「其他动态」，用待展示区
    里分数最高的非其他动态条目替换，直到正文不再含其他动态或待展示区
    没有可替换项。「其他动态」是被优先挤出正文的那一类。

    返回 (display, rest)，两者都按评分降序。
    """
    limit = config.MAX_NEWS_ITEMS if limit is None else limit
    ordered = sorted(items, key=_score, reverse=True)
    if len(ordered) <= limit:
        return ordered, []

    display = ordered[:limit]
    rest = ordered[limit:]

    idx = len(display) - 1
    while idx >= 0:
        if (display[idx].get("category") or "") != OTHER_CATEGORY:
            idx -= 1
            continue
        candidate = next((k for k, c in enumerate(rest)
                          if (c.get("category") or "") != OTHER_CATEGORY), None)
        if candidate is None:
            break
        display[idx], rest[candidate] = rest[candidate], display[idx]
        idx -= 1

    display.sort(key=_score, reverse=True)
    rest.sort(key=_score, reverse=True)
    return display, rest


def _fallback_brief(item: dict) -> str:
    """本地兜底简讯：取摘要首句，控制在 60 字内。"""
    text = (item.get("summary") or item.get("content") or "").strip()
    if not text:
        return ""
    first = re.split(r"[。！？\n]", text)[0].strip() or text
    return first[:60] + ("…" if len(first) > 60 else "")


def _build_prompt(items: list[dict]) -> str:
    lines = [
        "把下列每条新闻压缩成一句中文简讯，每条不超过 40 字。",
        "要求：只陈述事实（主体 + 动作 + 关键结论），不要评论、不要链接、不要编号。",
        "输出 JSON 数组，元素形如 {\"i\": 序号, \"b\": \"简讯\"}，不要输出其他内容。",
        "",
    ]
    for i, it in enumerate(items, 1):
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()[:180]
        lines.append(f"{i}. {title}｜{summary}")
    return "\n".join(lines)


def _call_model(prompt: str, model: str) -> list[str]:
    """调用轻量模型，返回按序排列的简讯列表；调用失败抛异常由上层兜底。"""
    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个新闻摘要压缩助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
    }).encode("utf-8")
    req = Request(url, data=payload, headers={
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
    })
    with urlopen(req, timeout=config.SUMMARY_TIMEOUT) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    content = (result["choices"][0]["message"].get("content") or "").strip()

    match = re.search(r"\[[\s\S]*\]", content)
    if not match:
        raise ValueError(f"简讯返回非 JSON 数组: {content[:80]}")
    parsed = json.loads(match.group(0))

    briefs = [""] * 100
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            i = int(entry.get("i"))
            b = str(entry.get("b") or "").strip()
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(briefs) and b:
            briefs[i - 1] = b[:_BRIEF_MAX_CHARS * 2]
    return briefs


def _try_compress(prompt: str, model: str, expected: int) -> list[str] | None:
    """尝试用一个模型压缩简讯；失败返回 None，由调用方决定下一档。"""
    try:
        briefs = _call_model(prompt, model)[:expected]
        filled = sum(1 for b in briefs if b)
        if filled == 0:
            log.warning("  %s 未返回有效简讯", model)
            return None
        log.info("  简讯压缩: %d 条 -> %d 条成功 (%s)", expected, filled, model)
        return briefs
    except (HTTPError, URLError, socket.timeout, TimeoutError, ValueError,
            KeyError, json.JSONDecodeError) as e:
        log.warning("  简讯压缩失败 (%s) [%s]", http_error_detail(e), model)
    except Exception as e:
        log.warning("  简讯压缩异常 (%s) [%s]", http_error_detail(e), model)
    return None


def build_briefs(items: list[dict], model: str | None = None,
                 max_items: int | None = None) -> list[dict]:
    """把未进正文的条目压缩为简讯列表。

    返回 [{"title", "brief", "link"}]；任何一步失败都退回本地截断摘要，
    保证调用方拿到的永远是可用数据。

    压缩模型按顺序尝试：配置的轻量模型 → 主模型。轻量模型多为免费额度，
    受限时整批会失败；此时用主模型兜一层，避免全部退化成 60 字截断。
    """
    if not items:
        return []

    cap = config.BRIEF_MAX_ITEMS if max_items is None else max_items
    selected = items[:cap]
    briefs: list[str] = []

    model_name = model or config.SUMMARY_MODEL_NAME
    if not config.API_KEY:
        log.warning("  未配置 API_KEY，%d 条简讯无法压缩（未发起模型调用），改用本地截断",
                    len(selected))
    elif not model_name:
        log.warning("  未配置简讯模型，%d 条简讯改用本地截断（未发起模型调用）", len(selected))
    else:
        prompt = _build_prompt(selected)
        candidates = [model_name, config.MODEL_NAME]
        tried = []
        log.info("  简讯压缩开始：%d 条 → 模型 %s", len(selected), model_name)
        for candidate in candidates:
            if not candidate or candidate in tried:
                continue
            tried.append(candidate)
            result = _try_compress(prompt, candidate, len(selected))
            if result is not None:
                briefs = result
                break
        if not briefs:
            log.warning("  简讯压缩全部失败，%d 条改用本地摘要截断", len(selected))

    result = []
    for i, it in enumerate(selected):
        brief = briefs[i] if i < len(briefs) else ""
        result.append({
            "title": (it.get("title") or "").strip(),
            "brief": brief or _fallback_brief(it),
            "link": (it.get("link") or it.get("url") or "").strip(),
        })
    return result
