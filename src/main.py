#!/usr/bin/env python3
"""
generate_briefing.py — AI & Agent 开发者晨报 主流程编排器

职责：
  1. 调用采集层 -> 获取原始新闻数据池
  2. 调用过滤层 -> 去重/评分得到干净数据
  3. AI 智能筛选与摘要生成
  4. 写入 HTML + 生成邮件

架构：
  collector.py (采集层)
    -> deduplicator.py (过滤层)
      -> ai_analyzer.py (AI 分析)
        -> html_writer.py (HTML/邮件生成)
          -> trending_fetcher.py (GitHub Trending)

分层独立，每层专注一个职责。
"""

import json
import logging
import os
import re
import sys
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style, get_random_trivia
from src.config.sources import CATEGORY_ORDER, TITLE_CATEGORY_MAP
from src.models import NewsItem, FilterReport
from src.collector import collect_all
from src.deduplicator import run_pipeline
from src.ai_analyzer import call_ai_analysis, reset_parse_stats
from src.html_writer import write_html, make_email_with_categories, generate_rss_feed
from src.trending_fetcher import fetch_github_trending
from src.logger import get_logger, log_structured

log = get_logger("main")


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

    return best_source if best_score >= 0.4 else "AI"


def _resolve_category(parsed: dict) -> str:
    """
    解析新闻分类，结果必为 CATEGORY_ORDER 中的一员。

    优先级：
      1. AI 返回的 tags[0]，且属于合法枚举 → 直接用
      2. 否则按「标题」关键词匹配 TITLE_CATEGORY_MAP（不扫摘要，避免把
         "其他动态" 二次拆出，导致分类散乱）
      3. 兜底 → 其他动态
    """
    tags = parsed.get("tags") or []
    if tags and isinstance(tags, list) and tags[0] in CATEGORY_ORDER:
        return tags[0]

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
    返回 (成功数, 跳过数)。news / items / international·china 三分支共用此函数，
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
            "tags": parsed.get("tags", []),
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
    from src.config.sources import CREDIBILITY_WHITELIST

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


# ============================================================
# 主流程
# ============================================================

def main():
    reset_parse_stats()
    log.info("=" * 60)
    log.info("  AI & Agent 开发者晨报 - 三层架构 v2.0")
    log.info("  采集: %d 个 RSS 源", len(config.RSS_SOURCES))
    log.info("  模型: %s", config.MODEL_NAME)
    log.info("=" * 60)

    # ---- 1. 采集层 ----
    log.info("")
    log.info("%s", "=" * 40)
    log.info("  第 1 层：多模态数据采集")
    log.info("%s", "=" * 40)
    raw_pool = collect_all()

    # ---- 2. 过滤层 ----
    log.info("")
    log.info("%s", "=" * 40)
    log.info("  第 2 层：智能过滤与去重")
    log.info("%s", "=" * 40)
    if raw_pool:
        report = run_pipeline(raw_pool)
    else:
        report = FilterReport(total_input=0)
    report.print_report()
    clean_items = report.remaining_items

    # ---- 3. AI 分析层 ----
    log.info("")
    log.info("%s", "=" * 40)
    log.info("  第 3 层：AI 分析与简报生成")
    log.info("%s", "=" * 40)

    trivia = get_random_trivia()
    log.info("  今日彩蛋: %s", trivia)

    final_items = []
    daily_analysis = ""
    ai_failed = False

    if not clean_items:
        log.info("  过滤后无可用数据，发送空报告邮件")
        ai_failed = True
    else:
        style_name, ai_result = call_ai_analysis(clean_items)
        if ai_result:
            daily_analysis = ai_result.get("daily_analysis", "")

            title_exact_map = {}
            source_title_map: dict[str, list[tuple[str, str]]] = {}
            for ci in clean_items:
                key = ci.title.strip()[:50].lower()
                if ci.url:
                    title_exact_map[key] = ci.url
                    src = (ci.source or "").lower()
                    source_title_map.setdefault(src, []).append((key, ci.url))
                    key_short = key[:30]
                    if key_short not in title_exact_map:
                        title_exact_map[key_short] = ci.url

            # 使用模块级辅助函数处理 AI 输出
            if "news" in ai_result:
                ok_count, skip_count = _append_parsed_items(
                    ai_result.get("news", []), final_items,
                    title_exact_map, source_title_map, clean_items)
                detail = ""
                if skip_count:
                    detail = f" (跳过 {skip_count} 条无法解析)"
                log.info("  AI 筛选后: %d 条%s", ok_count, detail)
            elif "items" in ai_result:
                items_ok, items_skip = _append_parsed_items(
                    ai_result["items"], final_items,
                    title_exact_map, source_title_map, clean_items)
                detail = ""
                if items_skip:
                    detail = f" (跳过 {items_skip} 条无法解析)"
                log.info("  AI 筛选后: %d 条%s", items_ok, detail)
        else:
            if ai_result and ("international" in ai_result or "china" in ai_result):
                fallback_items = []
                for key in ("international", "china"):
                    _append_parsed_items(
                        ai_result.get(key, []), fallback_items, {}, {}, clean_items)
                if fallback_items:
                    log.info("  降级: 使用旧格式 international/china，解析 %d 条", len(fallback_items))
                    final_items = fallback_items
                else:
                    ai_failed = True
            else:
                ai_failed = True

    # ---- 英文标题翻译兜底 ----
    if final_items and not ai_failed:
        from src.ai_analyzer import _translate_english_titles
        final_items = _translate_english_titles(final_items)

    # ---- 按评分排序（高到低） ----
    log.info("")
    log.info("  -- 按评分排序（高到低） --")

    # AI 未给分时规则补分
    scored = sum(1 for it in final_items if (it.get("score") or 0) > 0)
    if scored == 0 and final_items:
        log.warning("  AI 未返回评分，启用规则补分")
        _apply_fallback_scores(final_items)

    final_items.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    scored = sum(1 for it in final_items if it.get("score", 0) > 0)
    log.info("  评分分布: %d/%d 条有评分", scored, len(final_items))

    # ---- GitHub Trending ----
    log.info("")
    log.info("  -- 抓取 GitHub Trending 项目 --")
    trending_projects = fetch_github_trending()
    if trending_projects:
        log.info("  本周热门学习项目: %d 个", len(trending_projects))
        for p in trending_projects:
            log.info("    %s (%s)", p["name"], p["tag"])
    else:
        log.info("  今日暂无合适的 Trending 项目推荐")

    # ---- 写入网页 HTML ----
    log.info("")
    log.info("  -- 写入网页 HTML --")
    write_html(final_items, daily_analysis, trending_projects)

    # ---- 生成邮件 HTML（分类版） + RSS Feed ----
    log.info("")
    log.info("  -- 生成邮件（分类版）+ RSS Feed --")
    if ai_failed and not final_items:
        make_email_with_categories(
            [], f"今日无可用新闻。过滤报告：采集 {report.total_input} 条 -> "
                f"过滤后 {report.total_output} 条。",
            trending_projects, filter_report=report,
            style_name="", trivia=trivia,
        )
    else:
        make_email_with_categories(
            final_items, daily_analysis, trending_projects,
            filter_report=report,
            style_name=style_name if not ai_failed else "降级",
            trivia=trivia,
        )
    generate_rss_feed(final_items, daily_analysis)

    # ---- 邮件已生成，由 workflow 步骤发送 ----
    log.info("")
    log.info("  -- 邮件已生成，由 workflow 步骤发送 --")

    if daily_analysis:
        log.info("")
        log.info("  今日深度分析:")
        log.info("     %s...", daily_analysis[:200])

    log.info("")
    log.info("  简报生成完毕 | %d 条新闻 | %d 个项目", len(final_items), len(trending_projects))
    log.info("     邮件: %s", config.EMAIL_OUTPUT)
    log.info("     过滤前: %d 条 -> 过滤后: %d 条", report.total_input, report.total_output)

    # 结构化日志（写入文件）
    log_structured(
        log, logging.INFO, "briefing_complete",
        news_count=len(final_items),
        projects_count=len(trending_projects),
        total_input=report.total_input,
        total_output=report.total_output,
        ai_failed=ai_failed,
        style=style_name if not ai_failed else "降级",
    )


if __name__ == "__main__":
    main()
