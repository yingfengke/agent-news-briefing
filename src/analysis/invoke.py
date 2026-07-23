"""invoke.py - 模型调用与重试编排（主模型 + 兜底模型）。"""

import json
import time
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style
from src.core.models import NewsItem
from src.core.logger import get_logger
from src.analysis.context import (
    _balance_sources, _prescreen_items, _filter_history_duplicates,
    _truncate_context, _MAX_OUTPUT_TOKENS,
)
from src.analysis.json_parse import _safe_parse_json, _json_parse_stats
from src.analysis.twitter_filter import _filter_twitter_items

log = get_logger("ai")

def call_ai_analysis(items: list[NewsItem], max_retries: int = 1):
    """
    将过滤后的干净新闻发给大模型。

    max_retries=1：超时一次后重试大概率也超时，不浪费第二次的金钱与时间，
    直接切兜底模型（配置见 FALLBACK_MODEL_NAME）。

    返回:
      (style_name, parsed_json)  成功
      (style_name, None)          全部失败
    """
    if not config.API_KEY:
        log.warning("未配置 API_KEY，跳过 AI 分析")
        return ("", None)

    style_name, system_prompt = get_random_style()
    log.info("")
    log.info("  -> 今日风格: [%s]", style_name)

    balanced = _balance_sources(items)
    zh_items = [it for it in balanced if it.lang == "zh"]
    en_items = [it for it in balanced if it.lang == "en"]
    items_for_ai = en_items + zh_items
    log.info("  -> 配额后: 英文 %d 条 + 中文 %d 条 = %d 条", len(en_items), len(zh_items), len(items_for_ai))

    # 规则预筛（零成本，在 AI 分析之前过滤低质量内容）
    items_for_ai = _prescreen_items(items_for_ai)

    # Twitter 用免费模型精选（不占用 V4-Flash 配额）
    twitter_items = [it for it in items_for_ai if "twitter" in it.source.lower()]
    non_twitter_items = [it for it in items_for_ai if "twitter" not in it.source.lower()]
    if twitter_items:
        twitter_items = _filter_twitter_items(twitter_items)
        items_for_ai = non_twitter_items + twitter_items
        log.info("  -> 合并后: %d 条（非Twitter %d + Twitter精选 %d）",
                 len(items_for_ai), len(non_twitter_items), len(twitter_items))

    items_for_ai = _filter_history_duplicates(items_for_ai)
    if not items_for_ai:
        log.warning("所有新闻均已被历史报道过滤，将继续使用 AI 判断")

    ctx = _truncate_context(items_for_ai, system_prompt)
    user_content = ctx["user_content"]
    log.info("  -> 最终输入: %d字摘要 x %d条 (预估 %d tokens, 系统 %d tokens)",
             ctx["content_limit"], ctx["item_count"], ctx["total_tokens"], ctx["system_tokens"])

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
    est_tokens = ctx["total_tokens"]

    # 主模型：连续重试
    parsed = _try_model(url, system_prompt, user_content,
                        config.MODEL_NAME, max_retries, est_tokens)
    if parsed is not None:
        return (style_name, parsed)

    # 兜底模型：主模型全部失败时使用，避免单模型过载导致整期 0 新闻
    fb = getattr(config, "FALLBACK_MODEL_NAME", "")
    if fb and fb != config.MODEL_NAME:
        log.warning("  主模型 %s 全部失败，改用兜底模型 %s", config.MODEL_NAME, fb)
        parsed = _try_model(url, system_prompt, user_content,
                            fb, max(1, max_retries - 1), est_tokens)
        if parsed is not None:
            return (style_name, parsed)

    return (style_name, None)



def _try_model(url: str, system_prompt: str, user_content: str,
               model_name: str, max_retries: int, est_tokens: int):
    """
    对单个模型发起最多 max_retries 次对话调用。
    成功返回解析后的 dict，全部失败返回 None。
    """
    for attempt in range(1, max_retries + 1):
        log.info("")
        log.info("  -> 调用 AI 分析 (%s) 第 %d/%d 次 ...", model_name, attempt, max_retries)

        payload = json.dumps({
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": _MAX_OUTPUT_TOKENS,
        }).encode("utf-8")

        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        content = ""  # 失败时用于诊断原始响应，避免下一次故障靠猜
        try:
            with urlopen(req, timeout=360) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
            if "choices" not in result or len(result["choices"]) == 0:
                raise ValueError(f"API 返回异常: {str(result)[:200]}")

            content = (result["choices"][0]["message"].get("content") or "")
            log.info("模型返回响应 (%d 字符)", len(content))

            # Token 监控：记录实际消耗 vs 预估
            actual_usage = result.get("usage", {})
            actual_prompt = actual_usage.get("prompt_tokens", 0)
            actual_completion = actual_usage.get("completion_tokens", 0)
            if actual_prompt > 0:
                dev = abs(est_tokens - actual_prompt) / actual_prompt
                status = "正常" if dev < 0.15 else "偏差过大"
                log.info("  Token 监控: %s | 预估=%d | 实际=%d | 输出=%d | 偏差=%.1f%%",
                         status, est_tokens, actual_prompt, actual_completion, dev * 100)
            else:
                log.info("  Token 监控: API 未返回 usage 数据（截断检测将失效，依赖解析兜底）")

            # 截断检测：输出触顶 max_tokens 说明 JSON 大概率被硬切，尾部残缺
            if actual_completion >= _MAX_OUTPUT_TOKENS:
                log.warning("  输出触顶 %d tokens，JSON 可能被截断，将尝试截断抢救",
                            _MAX_OUTPUT_TOKENS)

            # 空响应显式识别：部分模型限流/过载会返回 200 但空 content
            if not content.strip():
                raise ValueError("模型返回空内容（可能限流/过载）")

            parsed = _safe_parse_json(content)
            if not parsed:
                raise ValueError("AI 返回内容无法解析为 JSON")

            news_count = len(parsed.get("news", []))
            log.info("  -> AI 筛选: %d 条新闻", news_count)
            stats = _json_parse_stats
            if stats["total"] > 0:
                direct_pct = stats["direct_ok"] / stats["total"] * 100
                comma_pct = stats["fallback_comma"] / stats["total"] * 100
                quote_pct = stats["fallback_quotes"] / stats["total"] * 100
                salvage_pct = stats["fallback_salvage"] / stats["total"] * 100
                fail_pct = stats["failed"] / stats["total"] * 100
                log.info("  JSON 质量: 直接通过 %.0f%% | 逗号修复 %.0f%% | 引号修复 %.0f%% | 截断抢救 %.0f%% | 失败 %.0f%%",
                         direct_pct, comma_pct, quote_pct, salvage_pct, fail_pct)
                if fail_pct > 5:
                    log.warning("JSON 解析失败率 %.0f%% 超过 5%% 阈值，建议检查 Prompt 效果", fail_pct)
            return parsed

        except Exception as e:
            # 异常分类：超时/限流/格式错 在日志里一眼区分，不再混为一谈
            if isinstance(e, HTTPError):
                exc_kind = f"HTTP错误 {e.code}"
            elif isinstance(e, (URLError, socket.timeout, TimeoutError)):
                exc_kind = "超时/网络"
            else:
                exc_kind = "其他异常"
            # 原始响应诊断：把模型到底回了什么打出来，
            # 这样下一次再出截断/空响应/拒答，不用误打误撞也能从日志定位
            if content:
                tail = content.rstrip()[-80:]
                head = content.lstrip()[:120]
                ends_ok = content.rstrip().endswith(("}", "]"))
                log.error("   失败诊断 [%s]: 原始响应 %d 字符 | 结尾闭合=%s",
                          exc_kind, len(content), ends_ok)
                log.error("     首120字: %s", head)
                log.error("     尾 80字: %s", tail)
            else:
                log.error("   失败诊断 [%s]: 无响应内容（请求阶段即失败，非模型输出问题）", exc_kind)
            if attempt < max_retries:
                log.warning("第%d次失败 (%s)，5秒后重试...", attempt, str(e)[:60])
                time.sleep(5)
            else:
                log.error("全部 %d 次重试均失败: %s", max_retries, str(e)[:80])
                return None
    return None
