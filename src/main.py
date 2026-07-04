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
import os
import re
import sys
from urllib.request import Request, urlopen

from src import config
from src.config import get_random_style, get_random_trivia
from src.models import NewsItem, FilterReport
from src.collector import collect_all
from src.deduplicator import run_pipeline
from src.ai_analyzer import call_ai_analysis, reset_parse_stats
from src.html_writer import write_html, generate_email_html
from src.trending_fetcher import fetch_github_trending


def _extract_link(it: dict, summary: str, title_exact_map: dict, source_title_map: dict) -> str:
    """从 AI 输出条目中提取原文链接（多层兜底）。"""
    link = it.get("link") or it.get("url") or ""
    if not link and summary:
        m = re.search(r'https?://[^\s<>)\]】、，,]+', summary)
        if m:
            link = m.group(0)
            print(f"    [链接兜底-摘要] {link[:60]}")

    if not link:
        title = (it.get("title", "") or "").lower().strip()
        if title[:50] in title_exact_map:
            link = title_exact_map[title[:50]]
            print(f"    [链接兜底-精确匹配] {link[:60]}")

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
            print(f"    [链接兜底-模糊匹配] {link[:60]} (相似度{best_score:.2f})")

    return link


def _try_parse_item(it):
    """尝试将 AI 输出条目解析为字典。"""
    import json as _json
    if isinstance(it, dict):
        return it, True
    if isinstance(it, str):
        stripped = it.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        try:
            parsed = _json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed, True
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                print(f"    [抢救] 字符串 JSON 数组 -> 取首元素")
                return parsed[0], True
        except _json.JSONDecodeError:
            pass
    print(f"    [警告] 无法解析的条目: {str(it)[:80]}")
    return None, False


# ============================================================
# 主流程
# ============================================================

def main():
    reset_parse_stats()
    print("=" * 60)
    print("  AI & Agent 开发者晨报 - 三层架构 v2.0")
    print(f"  采集: {len(config.RSS_SOURCES)} 个 RSS 源")
    print(f"  模型: {config.MODEL_NAME}")
    print("=" * 60)

    # ---- 1. 采集层 ----
    print(f"\n{'=' * 40}")
    print("  第 1 层：多模态数据采集")
    print(f"{'=' * 40}")
    raw_pool = collect_all()

    # ---- 2. 过滤层 ----
    print(f"\n{'=' * 40}")
    print("  第 2 层：智能过滤与去重")
    print(f"{'=' * 40}")
    if raw_pool:
        report = run_pipeline(raw_pool)
    else:
        report = FilterReport(total_input=0)
    report.print_report()
    clean_items = report.remaining_items

    # ---- 3. AI 分析层 ----
    print(f"\n{'=' * 40}")
    print("  第 3 层：AI 分析与简报生成")
    print(f"{'=' * 40}")

    trivia = get_random_trivia()
    print(f"  今日彩蛋: {trivia}")

    final_items = []
    daily_analysis = ""
    ai_failed = False

    if not clean_items:
        print("  [信息] 过滤后无可用数据，发送空报告邮件")
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
                print(f"\n  AI 筛选后: {ok_count} 条{detail}")
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
                print(f"\n  AI 筛选后: {items_ok} 条{detail}")
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
                            "link": _extract_link(parsed, summary),
                            "source": parsed.get("source", "AI"),
                        })
                if fallback_items:
                    print(f"  [降级] 使用旧格式 international/china，解析 {len(fallback_items)} 条")
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
    print(f"\n  -- 按评分排序（高到低） --")
    final_items.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    scored = sum(1 for it in final_items if it.get("score", 0) > 0)
    print(f"  评分分布: {scored}/{len(final_items)} 条有评分")

    # ---- GitHub Trending ----
    print(f"\n  -- 抓取 GitHub Trending 项目 --")
    trending_projects = fetch_github_trending()
    if trending_projects:
        print(f"  本周热门学习项目: {len(trending_projects)} 个")
        for p in trending_projects:
            print(f"    {p['name']} ({p['tag']})")
    else:
        print("  [信息] 今日暂无合适的 Trending 项目推荐")

    # ---- 写入网页 HTML ----
    print(f"\n  -- 写入网页 HTML --")
    write_html(final_items, daily_analysis, trending_projects)

    # ---- 生成邮件 HTML ----
    print(f"\n  -- 生成邮件 HTML --")
    if ai_failed and not final_items:
        generate_email_html(
            [], f"今日无可用新闻。过滤报告：采集 {report.total_input} 条 -> "
                f"过滤后 {report.total_output} 条。",
            trending_projects, filter_report=report,
            style_name="", trivia=trivia,
        )
    else:
        generate_email_html(
            final_items, daily_analysis, trending_projects,
            filter_report=report,
            style_name=style_name if not ai_failed else "降级",
            trivia=trivia,
        )

    # ---- 邮件已生成，由 workflow 步骤发送 ----
    print(f"\n  -- 邮件已生成，由 workflow 步骤发送 --")

    if daily_analysis:
        print(f"\n  今日深度分析:")
        print(f"     {daily_analysis[:200]}...")

    print(f"\n  简报生成完毕 | {len(final_items)} 条新闻 | {len(trending_projects)} 个项目")
    print(f"     邮件: {config.EMAIL_OUTPUT}")
    print(f"     过滤前: {report.total_input} 条 -> 过滤后: {report.total_output} 条")


if __name__ == "__main__":
    main()
