"""postprocess.py - AI 输出后处理 / 降级兜底：将 AI JSON 或原始数据构造为最终新闻条目。
"""
import json
import re
from urllib.parse import urlparse

from src.config.sources import CATEGORY_ORDER, CREDIBILITY_WHITELIST, TITLE_CATEGORY_MAP
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("analysis.postprocess")

_INVALID_TAG_TOKENS = {
    "ai", "其他", "其他动态", "无", "none", "null", "n/a", "未知",
    "general", "综合", "资讯", "新闻", "动态", "daily", "今日",
}

def _extract_link(it: dict, summary: str, title_exact_map: dict, source_title_map: dict) -> str:
    """从 AI 输出条目中提取原文链接（多层兜底）。"""
    link = it.get("link") or it.get("url") or ""
    if not link and summary:
        m = re.search(r'https?://[^\s<>)\]】、，,]+', summary)
        if m:
            link = m.group(0)
            log.debug("链接兜底-摘要: %s", link[:60])

    if not link:
        title = (it.get("title", "") or "").lower().strip()
        if title[:50] in title_exact_map:
            link = title_exact_map[title[:50]]
            log.debug("链接兜底-精确匹配: %s", link[:60])

    if not link:
        title = (it.get("title", "") or "").lower().strip()
        ai_source = (it.get("source", "") or "").lower().strip()
        candidates = []
        for src_key, entries in source_title_map.items():
            if ai_source and (ai_source in src_key or src_key in ai_source):
                candidates.extend(entries)
        if not candidates:
            for entries in source_title_map.values():
                candidates.extend(entries)

        title_words = set(w for w in re.split(r'[\s：:，,、()（）\[\]【】]', title) if len(w) > 1)
        best_match = ""
        best_score = 0
        for orig_title, orig_url in candidates:
            orig_words = set(w for w in re.split(r'[\s：:，,、()（）\[\]【】]', orig_title) if len(w) > 1)
            if not title_words or not orig_words:
                continue
            overlap = len(title_words & orig_words)
            score = overlap / min(len(title_words), len(orig_words))
            if score > best_score:
                best_score = score
                best_match = orig_url

        if best_score >= 0.4 and best_match:
            link = best_match
            log.debug("链接兜底-模糊匹配: %s (相似度%.2f)", link[:60], best_score)

    return link


def _normalize_score(raw_score) -> float:
    """将 AI 返回的 score 规范化，处理字符串/None/数字等异常情况。"""
    if raw_score is None:
        return 0
    if isinstance(raw_score, (int, float)):
        return float(raw_score)
    if isinstance(raw_score, str):
        raw_score = raw_score.strip()
        try:
            return float(raw_score)
        except (ValueError, TypeError):
            return 0
    return 0


def _try_parse_item(it):
    """尝试将 AI 输出条目解析为字典。"""
    if isinstance(it, dict):
        return it, True
    if isinstance(it, str):
        stripped = it.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed, True
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                log.debug("字符串 JSON 数组，取首元素")
                return parsed[0], True
        except json.JSONDecodeError:
            pass
    log.warning("无法解析的条目: %s", str(it)[:80])
    return None, False


def _resolve_source(parsed: dict, clean_items: list[NewsItem]) -> str:
    """
    解析新闻来源：优先使用 AI 返回的源名，
    若为空或 'AI' 则回溯到原始 RSS 采集的真实源名（如 ArXiv / TechCrunch）。
    """
    ai_src = (parsed.get("source") or "").strip()
    if ai_src and ai_src.lower() != "ai":
        return ai_src

    # 回溯：通过标题匹配找到原始 clean_items 的真实 source
    title = (parsed.get("title", "") or "").strip().lower()

    # 精确匹配（前 50 字符）
    for ci in clean_items:
        if ci.title.strip().lower()[:50] == title[:50]:
            return ci.source or "AI"

    # 短精确匹配（前 30 字符）
    for ci in clean_items:
        if ci.title.strip().lower()[:30] == title[:30]:
            return ci.source or "AI"

    # 模糊词重叠兜底（与 _extract_link 同逻辑）
    title_words = set(w for w in re.split(r'[\s：:，,、()（）\[\]【】]', title) if len(w) > 1)
    best_source = ""
    best_score = 0
    for ci in clean_items:
        orig_words = set(
            w for w in re.split(r'[\s：:，,、()（）\[\]【】]', ci.title.lower()) if len(w) > 1
        )
        if not title_words or not orig_words:
            continue
        overlap = len(title_words & orig_words)
        score = overlap / min(len(title_words), len(orig_words))
        if score > best_score:
            best_score = score
            best_source = ci.source or "AI"

    # URL 域名兜底：AI 改写标题导致上面匹配失败时的最后手段
    url = parsed.get("url") or ""
    if url:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            dom_map = {}
            for ci in clean_items:
                if not ci.url:
                    continue
                d = urlparse(ci.url).netloc.lower()
                if d.startswith("www."):
                    d = d[4:]
                if d and ci.source:
                    dom_map.setdefault(d, ci.source)
            if domain in dom_map:
                return dom_map[domain]

    return best_source if best_score >= 0.4 else "AI"


# 标签清洗：丢弃这些无意义词（LLM 常把来源/分类误填为标签）
_INVALID_TAG_TOKENS = {
    "ai", "其他", "其他动态", "无", "none", "null", "n/a", "未知",
    "general", "综合", "资讯", "新闻", "动态", "daily", "今日",
}


def _sanitize_tags(tags) -> list:
    """
    清洗 AI 返回的标签数组：去掉空值、无意义词（如 'AI'）、重复项。
    返回干净、可用于前端 chip 渲染的标签列表。
    """
    if not isinstance(tags, list):
        return []
    out, seen = [], set()
    for t in tags:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s:
            continue
        low = s.lower()
        if low in _INVALID_TAG_TOKENS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
    return out


def _resolve_category(parsed: dict) -> str:
    """
    解析新闻分类，结果必为 CATEGORY_ORDER 中的一员。

    优先级：
      1. AI 返回的 tags 中首个属于合法枚举的值 → 直接用
         （扫描全部 tags 而非只看 tags[0]，避免 LLM 把分类放在后面）
      2. 否则按「标题」关键词匹配 TITLE_CATEGORY_MAP（不扫摘要，避免把
         "其他动态" 二次拆出，导致分类散乱）
      3. 兜底 → 其他动态
    """
    tags = parsed.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            if t in CATEGORY_ORDER:
                return t

    title = (parsed.get("title") or "").lower()
    for pattern, category in TITLE_CATEGORY_MAP:
        if re.search(pattern, title):
            return category
    return "其他动态"


def _append_parsed_items(parsed_list: list, final_items: list,
                         title_exact_map: dict, source_title_map: dict,
                         clean_items: list) -> tuple[int, int]:
    """
    把 AI 返回的 news/items 列表逐条解析并追加到 final_items。
    返回 (成功数, 跳过数)。news / items 两分支共用此函数，
    避免重复构造 final_item 字典。
    """
    ok = skip = 0
    for it in parsed_list:
        parsed, valid = _try_parse_item(it)
        if not valid:
            skip += 1
            continue
        ok += 1
        summary = parsed.get("summary", "")
        final_items.append({
            "title": parsed.get("title", ""),
            "summary": summary,
            "link": _extract_link(parsed, summary, title_exact_map, source_title_map),
            "source": _resolve_source(parsed, clean_items),
            "score": _normalize_score(parsed.get("score")),
            "tags": _sanitize_tags(parsed.get("tags", [])),
            "category": _resolve_category(parsed),
        })
    return ok, skip


def _apply_fallback_scores(items: list[dict]) -> None:
    """
    规则补分：当 AI 返回的 score 全为 0 时，用规则自动打分。

    评分维度（满分 5.0）：
    - 基础分 2.0
    - 来源在可信度白名单 +1.0
    - 多家来源报道 +0.5
    - 有 tags +0.3
    - 标题含重要关键词 +0.5
    """
    keywords = ["发布", "开源", "突破", "重大", "首发", "独家", "正式", "上线", "推出", "实测"]
    whitelist_lower = [w.lower() for w in CREDIBILITY_WHITELIST]

    for item in items:
        score = 2.0

        link = (item.get("link") or "").lower()
        source = (item.get("source") or "").lower()
        if any(w in link or w in source for w in whitelist_lower):
            score += 1.0

        summary = item.get("summary") or ""
        if any(kw in summary for kw in ["多家", "N家", "交叉验证", "多家来源", "多家都在报"]):
            score += 0.5

        if item.get("tags"):
            score += 0.3

        title = item.get("title") or ""
        if any(kw in title for kw in keywords):
            score += 0.5

        item["score"] = round(min(score, 5.0), 1)

    log.info("  -> 规则补分完成: %d 条新闻已自动评分", len(items))


def _fallback_category(ci: NewsItem) -> str:
    """
    AI 失败兜底时，用标题 + tags 粗分新闻板块。
    只映射到已有的新闻板块，避免产生未知分类。
    """
    text = (ci.title or "") + " " + " ".join(ci.tags or [])
    t = text.lower()
    if any(k in t for k in ["agent", "智能体", "多智能"]):
        return "Agent框架"
    if any(k in t for k in ["论文", "paper", "arxiv", "研究", "测评", "评测"]):
        return "论文与研究"
    if any(k in t for k in ["发布", "开源", "上线", "推出", "首发", "正式"]):
        return "产品与发布"
    if any(k in t for k in ["行业", "融资", "收购", "政策", "监管", "合作", "上市"]):
        return "行业动态"
    return "其他动态"

def _build_fallback_items(clean_items: list[NewsItem]) -> list[dict]:
    """
    AI 分析失败时的降级兜底：直接用原始采集数据构造 final_items，
    保证简报至少有内容（未经 AI 润色、无深度分析、无英文翻译）。
    字段结构与正常路径一致，score 留 0 以触发 _apply_fallback_scores 规则补分。
    """
    items = []
    for ci in clean_items:
        content = ci.content or ""
        if len(content) > 200:
            content = content[:200].rstrip() + "…"
        items.append({
            "title": ci.title or "",
            "summary": content,
            "link": ci.url or "",
            "source": ci.source or "",
            "score": 0,
            "tags": list(ci.tags or []),
            "category": _fallback_category(ci),
        })
    return items
