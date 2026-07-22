#!/usr/bin/env python3
"""context.py - 上下文预组装：历史排重 / 规则预筛 / 来源配额 / Token 估算与截断。"""

import json
import re
from collections import defaultdict
from functools import lru_cache
from difflib import SequenceMatcher

import tiktoken

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("ai")

# tiktoken 编码器（cl100k_base 兼容主流模型）
_tk_encoding = tiktoken.get_encoding("cl100k_base")

# AI 输出 token 上限。4096 对 30 条摘要偏紧（LongCat 等模型易触顶被截断，
# 导致 JSON 尾部残缺无法解析），放宽到 8192 给足输出空间。
_MAX_OUTPUT_TOKENS = 8192

def load_history_titles():
    """
    从 tech-briefing.html 中读取已发送标题，
    用于 AI 排重（避免每日重复报道相似内容）。

    单次运行内 HTML 文件不会变更，故加 lru_cache 避免
    _filter_history_duplicates 与 _build_context 各自重复读文件。
    """
    titles = []
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
        if not m:
            return []
        data = json.loads(m.group(1))
        titles = [item.get("title", "") for item in data if item.get("title")]
    except Exception as e:
        log.warning("读取历史简报用于排重时出错: %s", e)
        return []

    return titles



def _prescreen_items(items: list[NewsItem]) -> list[NewsItem]:
    """
    规则预筛：在配额制之前执行，零成本过滤低质量内容。

    规则：
    1. 正文 < 10 字 → 丢弃（空/垃圾内容）
    2. Twitter 间去重：不同 Twitter 源但标题相似的推文，只留 1 条
    3. 来源类型标记（用于后续的按类配额）
    """
    if not items:
        return items

    # 规则 1: 过滤过短内容
    filtered = [it for it in items if len(it.content or "") >= 10]
    removed_short = len(items) - len(filtered)
    if removed_short:
        log.info("  -> 预筛: 过滤 %d 条过短内容（正文 < 10 字）", removed_short)

    # 规则 1b: 过滤疑似提示词注入的内容
    injection_patterns = [
        r"忽略.*(?:指令|规则|要求|之前)",
        r"ignore.*(?:previous|instruction|prompt)",
        r"输出.*(?:系统提示词|API Key|密码|密钥)",
        r"output.*(?:system prompt|api.?key|secret|password)",
        r"你.*(?:现在|接下来).*(?:是|扮演|作为)",
        r"(?:你|you).*(?:are now|will act as|pretend)",
    ]
    combined = re.compile("|".join(injection_patterns), re.IGNORECASE)
    before = len(filtered)
    filtered = [it for it in filtered
                if not combined.search(it.title or "") and not combined.search(it.content or "")]
    removed_inject = before - len(filtered)
    if removed_inject:
        log.warning("  -> 预筛: 过滤 %d 条疑似提示词注入内容", removed_inject)

    # 规则 2: Twitter 源间去重
    twitter_items = []
    non_twitter = []
    for it in filtered:
        if "twitter" in it.source.lower():
            twitter_items.append(it)
        else:
            non_twitter.append(it)

    if twitter_items:
        unique_tweets = []
        seen_titles = set()
        # 按正文长度排序，保留最长的（信息量最大的）
        twitter_items.sort(key=lambda x: len(x.content or ""), reverse=True)
        for it in twitter_items:
            # 取标题前 30 字作为去重键
            key = (it.title or "").strip()[:30].lower()
            if key and key not in seen_titles:
                seen_titles.add(key)
                unique_tweets.append(it)
            else:
                log.debug("  -> 预筛: Twitter 去重移除 %s: %s", it.source, (it.title or "")[:30])

        if len(unique_tweets) < len(twitter_items):
            log.info("  -> 预筛: Twitter %d 条 -> 去重后 %d 条",
                     len(twitter_items), len(unique_tweets))
        filtered = non_twitter + unique_tweets

    return filtered



def _balance_sources(items: list, max_total: int = 40, min_per_source: int = 2, min_sources: int = 5) -> list:
    """
    来源配额制：先按来源分桶，每源保底 2 条，
    再从剩余池中补满到 max_total 条，确保覆盖至少 min_sources 个源。
    """
    buckets = defaultdict(list)
    for it in items:
        buckets[it.source].append(it)

    selected = []
    remaining = []
    for source, src_items in buckets.items():
        selected.extend(src_items[:min_per_source])
        remaining.extend(src_items[min_per_source:])

    remaining.sort(key=lambda x: len(x.content or ""), reverse=True)

    needed = max_total - len(selected)
    if needed > 0 and remaining:
        selected.extend(remaining[:needed])

    source_count = len(set(it.source for it in selected))
    log.info("  -> 配额后: %d 条（覆盖 %d 个来源）", len(selected), source_count)
    return selected


# ============================================================
# Token 估算 & 上下文截断
# ============================================================


def _estimate_tokens(text: str, safety_buffer: float = 0.9) -> int:
    """
    使用 tiktoken 精确估算 token 数。
    safety_buffer: 0.9 表示预留 10% buffer 应对词表差异，防止 400 错误。
    """
    if not text:
        return 0
    try:
        raw_count = len(_tk_encoding.encode(text))
        return int(raw_count / safety_buffer)
    except Exception:
        return int(len(text) * 0.6)



def _filter_history_duplicates(items: list[NewsItem]) -> list[NewsItem]:
    """
    基于历史简报标题，过滤掉内容高度重复的新闻。
    """
    history_titles = load_history_titles()
    if not history_titles:
        return items

    def _normalize(title: str) -> str:
        return re.sub(r'[\s：:，,、()（）\[\]【】|/／\-—\'\"「」『』]', '', title).lower()

    def _keywords(title: str) -> set:
        parts = re.split(r'[\s：:，,、()（）\[\]【】|/／\-—\'\"「」『』]', title.lower())
        return set(w.strip() for w in parts if len(w.strip()) > 2)

    norm_history = [_normalize(t) for t in history_titles[:30]]
    kw_history = [_keywords(t) for t in history_titles[:30]]

    kept = []
    removed = 0
    for it in items:
        norm_current = _normalize(it.title)
        kw_current = _keywords(it.title)

        is_dup = False
        for i in range(len(norm_history)):
            if len(norm_history[i]) > 5 and len(norm_current) > 5:
                ratio = SequenceMatcher(None, norm_history[i], norm_current).ratio()
                if ratio > 0.50:
                    is_dup = True
                    break

            if kw_history[i] and kw_current:
                overlap = len(kw_current & kw_history[i])
                min_size = min(len(kw_current), len(kw_history[i]))
                if min_size > 0 and overlap / min_size > 0.5:
                    is_dup = True
                    break
                for ck in kw_current:
                    for hk in kw_history[i]:
                        if len(ck) > 3 and len(hk) > 3 and (ck in hk or hk in ck):
                            is_dup = True
                            break
                    if is_dup:
                        break

        if is_dup:
            removed += 1
        else:
            kept.append(it)

    if removed:
        log.info("  -> 历史排重: 过滤 %d 条已报道过的新闻", removed)
    return kept



def _build_context(items_for_ai: list[NewsItem], system_prompt: str,
                   content_limit: int = 80, max_items: int | None = None):
    preamble_lines = [
        "以下是今日抓取的科技新闻，请按你的系统指令处理：\n",
        "【摘要要求】每条摘要字数控制在 80-150 字之间，不要过短或过长。"
        "摘要中只写新闻内容本身，不要包含任何链接或URL。\n",
        "【链接要求】请在每条新闻的 JSON 输出中保留 url 字段，"
        "值为原文链接。\n",
        "【来源多样性要求】在筛选过程中，如果某条新闻不值得单独成条，"
        "可以合并到相关新闻的摘要中提及，确保最终简报覆盖尽可能多的来源和话题。\n",
        "【时间表述要求】每条新闻标题前已标注其发布日期（格式 YYYY-MM-DD），这是该条新闻的时间基准。"
        "摘要中若新闻原文含相对或模糊时间表述（如 昨天/前天/明天/后天/下周一/一周后/月初/月底/中旬/季度末 等），"
        "请【保留原文表述】，并在其后用括号附上以发布日期为基准换算的绝对日期（带年份），"
        "例如原文'明天将发布新模型'应写为'明天（2026年7月10日）将发布新模型'。"
        "换算要覆盖过去（昨天/前天/上周/几天前）、未来（今天/明天/后天/下周/一周后/两周内）、"
        "模糊区间（月初/月中/月底/上中下旬/季度初末/年初年底）各方向；"
        "跨月跨年须正确进位（如 2026-12-31 的'明天'→（2027年1月1日））；"
        "区间类可标为日期区间（如'七月中旬'→（2026年7月11日至20日））。"
        "若某条新闻缺少发布日期基准、或相对时间无法定位到具体日期，"
        "则【只保留原文、不添加括号】，切勿臆造日期。"
        "注意：括号里的绝对日期由 AI 按基准推算，可能存在计算错误、仅供参考；"
        "原始表述才是可靠依据，不要为了加括号而改动原文措辞。\n",
    ]
    preamble_text = "".join(preamble_lines)
    preamble_tokens = _estimate_tokens(preamble_text)

    max_items = max_items or len(items_for_ai)
    item_lines = []
    for i, item in enumerate(items_for_ai[:max_items], 1):
        content_short = (item.content or "无描述")[:content_limit]
        time_info = f" ({item.published_at[:10]})" if item.published_at else ""
        item_lines.append(f"{i}. [{item.source}]{time_info} {item.title}")
        item_lines.append(f"   简介: {content_short}")
        item_lines.append(f"   链接: {item.url}\n")
    items_text = "\n".join(item_lines)
    items_tokens = _estimate_tokens(items_text)
    actual_items = min(max_items, len(items_for_ai))

    history_titles = load_history_titles()
    history_text = ""
    if history_titles:
        history_text = ("\n---\n【已报道历史】过去几天已推送过的新闻标题"
                        "（遇到核心主题相似的请跳过）：\n" +
                        "\n".join(f"- {t}" for t in history_titles))
    history_tokens = _estimate_tokens(history_text)

    system_tokens = _estimate_tokens(system_prompt)
    user_content = preamble_text + items_text + history_text
    total_tokens = system_tokens + preamble_tokens + items_tokens + history_tokens

    return {
        "user_content": user_content,
        "total_tokens": total_tokens,
        "system_tokens": system_tokens,
        "item_count": actual_items,
        "content_limit": content_limit,
    }



def _truncate_context(items_for_ai: list[NewsItem], system_prompt: str,
                      max_context: int = 32000,
                      max_output: int = _MAX_OUTPUT_TOKENS,
                      safety_margin: int = 800):
    """
    渐进式截断：先缩每条简介字数，再砍总条数，保证最终一定收敛在预算内。
    """
    token_budget = max_context - max_output - safety_margin

    content_limit = 80
    max_items = len(items_for_ai)

    # 简介字数档位（逐步收紧）
    content_steps = [80, 60, 50, 40, 30]
    item_floor = 12  # 条数硬下限，避免砍到空

    for cl in content_steps:
        content_limit = cl
        ctx = _build_context(items_for_ai, system_prompt,
                             content_limit=content_limit, max_items=max_items)
        if ctx["total_tokens"] <= token_budget:
            return ctx
        log.info("  -> 上下文超限 (%d > %d)，content 缩短至 %d 字",
                 ctx["total_tokens"], token_budget, cl)

    # 简介已到下限仍超限：继续砍条数到 item_floor
    for mi in range(max_items - 1, item_floor - 1, -1):
        ctx = _build_context(items_for_ai, system_prompt,
                             content_limit=content_limit, max_items=mi)
        if ctx["total_tokens"] <= token_budget:
            log.info("  -> 上下文仍超限，总条数缩至 %d", mi)
            return ctx

    log.warning("已达最大截断仍超限 (%d > %d)，继续发送", ctx["total_tokens"], token_budget)
    return ctx


# ============================================================
# 分析编排（JSON 解析 / 翻译 / Twitter 精选见对应子模块）
# ============================================================
