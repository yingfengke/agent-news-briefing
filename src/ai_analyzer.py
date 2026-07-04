#!/usr/bin/env python3
"""
ai_analyzer.py — AI 分析、来源配额、Token 估算与上下文截断
"""

import json
import os
import re
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style
from src.models import NewsItem

# tiktoken 编码器（cl100k_base 兼容主流模型）
import tiktoken
_tk_encoding = tiktoken.get_encoding("cl100k_base")


# ============================================================
# Markdown 链接清洗（用于邮件安全嵌入）
# ============================================================

def load_history_titles():
    """
    从 tech-briefing.html 中读取 __NEWS_DATA__ 数组并提取标题，
    用于 AI 排重（避免每日重复报道相似内容）。
    """
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
        if not m:
            return []
        data = json.loads(m.group(1))
        titles = [item.get("title", "") for item in data if item.get("title")]
        return titles
    except Exception as e:
        print(f"  [警告] 读取历史简报用于排重时出错: {e}")
        return []


def _balance_sources(items: list, max_total: int = 30, min_per_source: int = 2, min_sources: int = 5) -> list:
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
    print(f"  -> 配额后: {len(selected)} 条（覆盖 {source_count} 个来源）")
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
        print(f"  -> 历史排重: 过滤 {removed} 条已报道过的新闻")
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
            print(f"  -> 上下文超限 ({ctx['total_tokens']} > {token_budget})，"
                  f"content 缩短 {old}->{content_limit} 字")
            continue
        if max_items > 25:
            max_items = 25
            print(f"  -> 上下文仍超限，总条数缩至 {max_items}")
            continue
        if max_items > 20:
            max_items = 20
            print(f"  -> 上下文仍超限，总条数缩至 {max_items}")
            continue

        print(f"  [注意] 已达最大截断仍超限 ({ctx['total_tokens']} > {token_budget})，继续发送")
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
    print(f"\n  [翻译兜底] {len(need)} 条纯英文标题，正在翻译...")
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
                    print(f"    {old[:35]}... -> {translated[:35]}")
            except (ValueError, IndexError):
                continue
        print(f"  [翻译兜底] 完成 {len(need)} 条")
    except Exception as e:
        print(f"  [翻译兜底] 失败: {str(e)[:60]}")
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


def call_ai_analysis(items: list[NewsItem], max_retries: int = 3):
    """
    将过滤后的干净新闻发给大模型。

    返回:
      (style_name, parsed_json)  成功
      (style_name, None)          全部失败
    """
    if not config.API_KEY:
        print("[警告] 未配置 API_KEY，跳过 AI 分析")
        return ("", None)

    style_name, system_prompt = get_random_style()
    print(f"\n  -> 今日风格: [{style_name}]")

    balanced = _balance_sources(items)
    zh_items = [it for it in balanced if it.lang == "zh"]
    en_items = [it for it in balanced if it.lang == "en"]
    items_for_ai = en_items + zh_items
    print(f"  -> 喂给 AI: 英文 {len(en_items)} 条 + 中文 {len(zh_items)} 条 = {len(items_for_ai)} 条")

    items_for_ai = _filter_history_duplicates(items_for_ai)
    if not items_for_ai:
        print("  [警告] 所有新闻均已被历史报道过滤，将继续使用 AI 判断")

    ctx = _truncate_context(items_for_ai, system_prompt)
    user_content = ctx["user_content"]
    print(f"  -> 最终输入: {ctx['content_limit']}字摘要 x {ctx['item_count']}条 "
          f"(预估 {ctx['total_tokens']} tokens, 系统 {ctx['system_tokens']} tokens)")

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"

    for attempt in range(1, max_retries + 1):
        print(f"\n  -> 调用 AI 分析 ({config.MODEL_NAME}) ... ", end="", flush=True)

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
            print(f"成功 ({len(content)} 字符)")

            # Token 监控：记录实际消耗 vs 预估
            actual_usage = result.get("usage", {})
            actual_prompt = actual_usage.get("prompt_tokens", 0)
            actual_completion = actual_usage.get("completion_tokens", 0)
            if actual_prompt > 0:
                est = ctx["total_tokens"]
                dev = abs(est - actual_prompt) / actual_prompt
                status = "正常" if dev < 0.15 else "偏差过大"
                print(f"  Token 监控: {status} | 预估={est} | 实际={actual_prompt} | 输出={actual_completion} | 偏差={dev:.1%}")
            else:
                print(f"  Token 监控: API 未返回 usage 数据")

            parsed = _safe_parse_json(content)
            if not parsed:
                raise ValueError("AI 返回内容无法解析为 JSON")

            news_count = len(parsed.get("news", [])) if "news" in parsed else 0
            if not news_count:
                news_count = len(parsed.get("international", [])) + len(parsed.get("china", []))
            print(f"  -> AI 筛选: {news_count} 条新闻")
            stats = _json_parse_stats
            if stats["total"] > 0:
                direct_pct = stats["direct_ok"] / stats["total"] * 100
                comma_pct = stats["fallback_comma"] / stats["total"] * 100
                quote_pct = stats["fallback_quotes"] / stats["total"] * 100
                fail_pct = stats["failed"] / stats["total"] * 100
                print(f"  JSON 质量: 直接通过 {direct_pct:.0f}% | 逗号修复 {comma_pct:.0f}% | 引号修复 {quote_pct:.0f}% | 失败 {fail_pct:.0f}%")
                if fail_pct > 5:
                    print(f"  [WARNING] JSON 解析失败率 {fail_pct:.0f}% 超过 5% 阈值，建议检查 Prompt 效果")
            return (style_name, parsed)

        except Exception as e:
            if attempt < max_retries:
                print(f"第{attempt}次失败 ({str(e)[:60]})，5秒后重试...")
                import time
                time.sleep(5)
            else:
                print(f"全部 {max_retries} 次重试均失败: {str(e)[:80]}")
                return (style_name, None)
