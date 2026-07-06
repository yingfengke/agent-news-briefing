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
from datetime import datetime
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style, get_random_trivia
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

    # 异常补救模式：当前时间 >= 09:00 说明 06:00 主简报和 08:30 补推均未成功，
    # 将 AIHOT 精选合并到数据池一起送入 AI 分析，不再依赖单独补推
    now = datetime.now()
    if now.hour >= 9:
        from src.collector import collect_aihot
        log.info("")
        log.info("  补救模式（当前 %s），合并 AIHOT 精选数据", now.strftime("%H:%M"))
        raw_pool.extend(collect_aihot())

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
            ok_count = skip_count = 0

            if "news" in ai_result:
                for it in ai_result.get("news", []):
                    parsed, ok = _try_parse_item(it)
                    if not ok:
                        skip_count += 1
                        continue
                    ok_count += 1
                    summary = parsed.get("summary", "")
                    final_items.append({
                        "title": parsed.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(parsed, summary, title_exact_map, source_title_map),
                        "source": parsed.get("source", "AI"),
                        "score": parsed.get("score", 0),
                        "tags": parsed.get("tags", []),
                    })
                detail = ""
                if skip_count:
                    detail = f" (跳过 {skip_count} 条无法解析)"
                log.info("  AI 筛选后: %d 条%s", ok_count, detail)
            elif "items" in ai_result:
                items_ok = items_skip = 0
                for it in ai_result["items"]:
                    parsed, ok = _try_parse_item(it)
                    if not ok:
                        items_skip += 1
                        continue
                    items_ok += 1
                    summary = parsed.get("summary", "")
                    final_items.append({
                        "title": parsed.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(parsed, summary, title_exact_map, source_title_map),
                        "source": parsed.get("source", "AI"),
                        "score": parsed.get("score", 0),
                        "tags": parsed.get("tags", []),
                    })
                detail = ""
                if items_skip:
                    detail = f" (跳过 {items_skip} 条无法解析)"
                log.info("  AI 筛选后: %d 条%s", items_ok, detail)
        else:
            if ai_result and ("international" in ai_result or "china" in ai_result):
                fallback_items = []
                for key in ("international", "china"):
                    for it in ai_result.get(key, []):
                        parsed, ok = _try_parse_item(it)
                        if not ok:
                            continue
                        summary = parsed.get("summary", "")
                        fallback_items.append({
                            "title": parsed.get("title", ""),
                            "summary": summary,
                            "link": _extract_link(parsed, summary, {}, {}),
                            "source": parsed.get("source", "AI"),
                        })
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
