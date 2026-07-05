#!/usr/bin/env python3
"""
ai_analyzer.py — AI 分析、来源配额、Token 估算与上下文截断
"""

import json
import os
import re
import time
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style
from src.models import NewsItem
from src.logger import get_logger

import tiktoken

log = get_logger("ai")

# tiktoken 编码器（cl100k_base 兼容主流模型）
import tiktoken
_tk_encoding = tiktoken.get_encoding("cl100k_base")


# ============================================================
# Markdown 链接清洗（用于邮件安全嵌入）
# ============================================================

def load_history_titles():
    """
    从 tech-briefing.html 和 .aihot_history.json 中读取已发送标题，
    用于 AI 排重（避免每日重复报道相似内容）。
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

    # 追加 AIHOT 补推历史（避免第二天重复选到同一内容）
    try:
        if os.path.exists(config.AIHOT_HISTORY_FILE):
            with open(config.AIHOT_HISTORY_FILE, "r", encoding="utf-8") as f:
                aihot_data = json.load(f)
            aihot_titles = aihot_data.get("items", [])
            titles.extend(aihot_titles)
            log.info("  AIHOT 补推历史: %d 条", len(aihot_titles))
    except Exception as e:
        log.warning("读取 AIHOT 补推历史失败: %s", e)

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
                      max_output: int = 4096,
                      safety_margin: int = 800):
    """
    渐进式截断。
    """
    token_budget = max_context - max_output - safety_margin

    content_limit = 80
    max_items = len(items_for_ai)

    for step in range(10):
        ctx = _build_context(items_for_ai, system_prompt,
                             content_limit=content_limit, max_items=max_items)
        if ctx["total_tokens"] <= token_budget:
            return ctx

        if content_limit > 50:
            old = content_limit
            content_limit = 50
            log.info("  -> 上下文超限 (%d > %d)，content 缩短 %d->%d 字",
                      ctx["total_tokens"], token_budget, old, content_limit)
            continue
        if max_items > 25:
            max_items = 25
            log.info("  -> 上下文仍超限，总条数缩至 %d", max_items)
            continue
        if max_items > 20:
            max_items = 20
            log.info("  -> 上下文仍超限，总条数缩至 %d", max_items)
            continue

        log.warning("已达最大截断仍超限 (%d > %d)，继续发送", ctx["total_tokens"], token_budget)
        break

    return _build_context(items_for_ai, system_prompt,
                          content_limit=content_limit, max_items=max_items)


# JSON 解析质量监控
_json_parse_stats = {"total": 0, "direct_ok": 0, "fallback_comma": 0, "fallback_quotes": 0, "failed": 0}


def _safe_parse_json(text: str) -> dict:
    """
    健壮的 JSON 解析，兜底处理 AI 输出的各种不规范格式。
    """
    _json_parse_stats["total"] += 1
    text = text.strip()
    if not text:
        _json_parse_stats["failed"] += 1
        return {}

    if text.startswith("```"):
        end_md = text.find("```", 3)
        if end_md != -1:
            text = text[3:end_md]
        else:
            text = text[3:]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        text = m.group(1)

    try:
        result = json.loads(text)
        _json_parse_stats["direct_ok"] += 1
        return result
    except json.JSONDecodeError:
        pass

    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)

    try:
        result = json.loads(text)
        _json_parse_stats["fallback_comma"] += 1
        return result
    except json.JSONDecodeError:
        pass

    text = re.sub(r"'([^']+)'(\s*[:,\]}])", lambda m: chr(34) + m.group(1) + chr(34) + m.group(2), text)

    try:
        result = json.loads(text)
        _json_parse_stats["fallback_quotes"] += 1
        return result
    except json.JSONDecodeError:
        _json_parse_stats["failed"] += 1
        return {}


def _translate_english_titles(items: list[dict]) -> list[dict]:
    """
    兜底：将纯英文标题翻译成中文（保留技术术语原文）。
    """
    need = []
    for i, it in enumerate(items):
        title = it.get("title", "")
        if not title:
            continue
        cn = sum(1 for c in title if '\u4e00' <= c <= '\u9fff')
        if cn == 0:
            need.append((i, title))
    if not need:
        return items
    log.info("")
    log.info("  翻译兜底: %d 条纯英文标题，正在翻译...", len(need))
    lines = "\n".join(f"{j+1}. {t}" for j, (_, t) in enumerate(need))
    prompt = f"将以下英文标题翻译成自然中文，技术名词（GPT-5O、Agent、RAG、MoE等）保留英文：\n{lines}"
    payload = json.dumps({"model": config.MODEL_NAME, "messages": [
        {"role": "system", "content": "你专业翻译技术标题。"},
        {"role": "user", "content": prompt},
    ], "temperature": 0.1}).encode("utf-8")
    try:
        url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
        text = result["choices"][0]["message"]["content"]
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            parts = line.split(".", 1)
            if len(parts) != 2:
                continue
            try:
                idx = int(parts[0].strip()) - 1
                translated = parts[1].strip()
                if 0 <= idx < len(need):
                    oi = need[idx][0]
                    old = items[oi]["title"]
                    items[oi]["title"] = translated
                    log.info("    %s... -> %s", old[:35], translated[:35])
            except (ValueError, IndexError):
                continue
        log.info("  翻译兜底完成 %d 条", len(need))
    except Exception as e:
        log.warning("  翻译兜底失败: %s", str(e)[:60])
    return items


def get_parse_stats():
    """返回 JSON 解析质量统计数据"""
    return dict(_json_parse_stats)


def reset_parse_stats():
    """重置 JSON 解析质量计数器"""
    _json_parse_stats["total"] = 0
    _json_parse_stats["direct_ok"] = 0
    _json_parse_stats["fallback_comma"] = 0
    _json_parse_stats["fallback_quotes"] = 0
    _json_parse_stats["failed"] = 0


def _filter_twitter_items(twitter_items: list[NewsItem], model: str = "THUDM/GLM-Z1-9B-0414",
                          max_chars: int = 10000) -> list[NewsItem]:
    """
    用免费模型筛选 Twitter 内容，精选最有价值的 3-5 条。

    如果推文总字数超过 max_chars，自动拆分为两次请求，
    防止免费模型 context window 超限。
    """
    if not twitter_items or not config.API_KEY:
        return twitter_items[:3]

    lines = []
    for i, it in enumerate(twitter_items, 1):
        lines.append(f"{i}. [{it.source}] {it.title}\n   简介: {(it.content or '无描述')[:150]}")

    prompt_template = (
        "从以下 AI 推文中选出最有价值的 3-5 条。\n"
        "【优先保留】模型发布、技术突破、工具推荐、论文解读\n"
        "【过滤】纯个人观点、转发无评论、营销内容、无信息量的日常动态\n"
        "【去重】同一话题只保留信息量最丰富的一条\n"
        "只输出编号，用逗号分隔，如：1,3,5\n\n"
    )

    def _call_model(prompt_text: str, offset: int = 0) -> list[int]:
        """调用免费模型，返回选中编号（相对 offset 的原始索引）"""
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一个 AI 资讯筛选助手，从推文中选出最有价值的几条。"},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": 0.1,
            "max_tokens": 128,
        }).encode("utf-8")

        url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        raw = result["choices"][0]["message"]["content"]
        nums = [int(n.strip()) for n in re.split(r'[,，\s]+', raw) if n.strip().isdigit()]
        return [offset + n - 1 for n in nums if 1 <= n <= len(twitter_items[offset:])]

    # 估算输入总字符数，超限则分批
    total_chars = len(prompt_template) + sum(len(l) for l in lines)
    all_selected_indices = []

    try:
        from urllib.error import HTTPError

        if total_chars <= max_chars:
            prompt = prompt_template + "\n".join(lines)
            all_selected_indices = _call_model(prompt)
        else:
            # 分批：每批最大字符数为 max_chars 的一半（留余量）
            batch_size = max_chars // 2
            batches = []
            current_batch = []
            current_size = 0
            for l in lines:
                if current_size + len(l) > batch_size and current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_size = 0
                current_batch.append(l)
                current_size += len(l)
            if current_batch:
                batches.append(current_batch)

            log.info("  -> Twitter 推文 %d 条 (%d 字符)，拆为 %d 批筛选",
                     len(twitter_items), total_chars, len(batches))

            offset = 0
            for batch_lines in batches:
                prompt = prompt_template + "\n".join(batch_lines)
                indices = _call_model(prompt, offset)
                all_selected_indices.extend(indices)
                offset += len(batch_lines)

        selected = [twitter_items[i] for i in all_selected_indices if 0 <= i < len(twitter_items)]
        if not selected:
            selected = twitter_items[:3]
        log.info("  -> Twitter 精选: %d 条 -> %d 条 (%s)", len(twitter_items), len(selected), model)
        return selected
    except Exception as e:
        log.warning("Twitter 精选失败 (%s)，保留前 3 条", str(e)[:50])
        return twitter_items[:3]


def call_ai_analysis(items: list[NewsItem], max_retries: int = 3):
    """
    将过滤后的干净新闻发给大模型。

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

    for attempt in range(1, max_retries + 1):
        log.info("")
        log.info("  -> 调用 AI 分析 (%s) ...", config.MODEL_NAME)

        payload = json.dumps({
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode("utf-8")

        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        try:
            with urlopen(req, timeout=180) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
            if "choices" not in result or len(result["choices"]) == 0:
                raise ValueError(f"API 返回异常: {str(result)[:200]}")

            content = result["choices"][0]["message"]["content"]
            log.info("成功 (%d 字符)", len(content))

            # Token 监控：记录实际消耗 vs 预估
            actual_usage = result.get("usage", {})
            actual_prompt = actual_usage.get("prompt_tokens", 0)
            actual_completion = actual_usage.get("completion_tokens", 0)
            if actual_prompt > 0:
                est = ctx["total_tokens"]
                dev = abs(est - actual_prompt) / actual_prompt
                status = "正常" if dev < 0.15 else "偏差过大"
                log.info("  Token 监控: %s | 预估=%d | 实际=%d | 输出=%d | 偏差=%.1f%%",
                         status, est, actual_prompt, actual_completion, dev * 100)
            else:
                log.info("  Token 监控: API 未返回 usage 数据")

            parsed = _safe_parse_json(content)
            if not parsed:
                raise ValueError("AI 返回内容无法解析为 JSON")

            news_count = len(parsed.get("news", [])) if "news" in parsed else 0
            if not news_count:
                news_count = len(parsed.get("international", [])) + len(parsed.get("china", []))
            log.info("  -> AI 筛选: %d 条新闻", news_count)
            stats = _json_parse_stats
            if stats["total"] > 0:
                direct_pct = stats["direct_ok"] / stats["total"] * 100
                comma_pct = stats["fallback_comma"] / stats["total"] * 100
                quote_pct = stats["fallback_quotes"] / stats["total"] * 100
                fail_pct = stats["failed"] / stats["total"] * 100
                log.info("  JSON 质量: 直接通过 %.0f%% | 逗号修复 %.0f%% | 引号修复 %.0f%% | 失败 %.0f%%",
                         direct_pct, comma_pct, quote_pct, fail_pct)
                if fail_pct > 5:
                    log.warning("JSON 解析失败率 %.0f%% 超过 5%% 阈值，建议检查 Prompt 效果", fail_pct)
            return (style_name, parsed)

        except Exception as e:
            if attempt < max_retries:
                log.warning("第%d次失败 (%s)，5秒后重试...", attempt, str(e)[:60])
                time.sleep(5)
            else:
                log.error("全部 %d 次重试均失败: %s", max_retries, str(e)[:80])
                return (style_name, None)
