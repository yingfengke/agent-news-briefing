#!/usr/bin/env python3
"""
generate_briefing.py — AI & Agent 开发者晨报 主流程编排器

职责：
  1. 调用采集层 -> 获取原始新闻数据池
  2. 调用过滤层 -> 去重/评分得到干净数据
  3. AI 智能筛选与摘要生成
  4. 写入 HTML + 生成邮件

架构：
  collect/collector.py (采集层)
    -> collect/dedupe/ (过滤层)
      -> analysis/ (AI 分析编排)
        -> delivery/html_gen.py (网页) + email_gen.py (邮件) + rss_gen.py (RSS)
          -> collect/trending_fetcher.py (GitHub Trending)

分层独立，每层专注一个职责。
"""

import json
import logging
import os
from datetime import datetime

from src import config
from src.config import get_today_trivia
from src.core.models import FilterReport, NewsItem
from src.collect.collector import collect_all
from src.dedupe import run_pipeline
from src.analysis import call_ai_analysis, reset_parse_stats, _translate_english_titles
from src.analysis.postprocess import (
    _append_parsed_items, _build_fallback_items, _apply_fallback_scores,
)
from src.delivery.html_gen import write_html
from src.delivery.email_gen import make_email_with_categories
from src.delivery.rss_gen import generate_rss_feed
from src.delivery.timefmt import _attach_published_at
from src.collect.trending_fetcher import fetch_github_trending
from src.core.logger import get_logger, log_structured, Timeline
from src.core.rerun import (
    is_rerun, clear_dedup_for_rerun,
    load_cached_clean_items, save_clean_items, _reset_html_news_data,
)

log = get_logger(__name__)

# 质量异常告警阈值（保守起步，避免误报骚扰）
MIN_NEWS_ALERT = 5      # 最终新闻数低于该值视为异常
MIN_INPUT_ALERT = 10    # 进入 AI 分析的条数低于该值视为异常


def _collect_quality_issues(final_items, report, ai_failed):
    """汇总「流程成功但质量异常」的问题列表（无异常返回空列表）。

    只覆盖两类极端情况，避免告警疲劳：AI 降级兜底、内容量过少。
    Trending 抓空不计入（推荐偶尔为空属正常，已由 timeline 与摘要记录）。
    """
    issues = []
    if ai_failed:
        issues.append("AI 分析失败，本期已降级为原始数据兜底（无摘要润色与深度分析）")
    if len(final_items) < MIN_NEWS_ALERT:
        issues.append(f"最终新闻仅 {len(final_items)} 条（阈值 {MIN_NEWS_ALERT} 条）")
    total_input = getattr(report, "total_input", 0) or 0
    if not ai_failed and total_input < MIN_INPUT_ALERT:
        issues.append(f"进入 AI 分析的新闻仅 {total_input} 条（阈值 {MIN_INPUT_ALERT} 条），"
                      "采集或过滤可能异常")
    return issues


def _write_daily_summary(timeline_data: dict, **metrics) -> str:
    """写当日运行摘要 JSON（logs/，已被 .gitignore 忽略），返回文件路径。"""
    logs_dir = os.path.join(config.BASE_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, f"daily-summary-{datetime.now().strftime('%Y-%m-%d')}.json")
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timeline": timeline_data,
        "metrics": metrics,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _run_main():
    reset_parse_stats()
    tl = Timeline()
    # 同日重跑检测：有缓存则直接复用去重后原始数据（跳过采集+去重）；
    # 无缓存（如首跑失败、被旧逻辑清空）则清空去重库后正常重抓。
    reused = False
    if is_rerun():
        cached = load_cached_clean_items()
        if cached is not None:
            reused = True
            clean_items = cached
            report = FilterReport(
                total_input=len(clean_items),
                total_output=len(clean_items),
                remaining_items=clean_items,
            )
            _reset_html_news_data()  # 复用时不让历史标题去重吃掉同日数据
            log.info("  同日重跑：复用已缓存原始数据 %d 条（跳过采集与去重）",
                     len(clean_items))
        else:
            clear_dedup_for_rerun()
    log.info("=" * 60)
    log.info("  AI & Agent 开发者晨报 - 三层架构 v2.0")
    log.info("  采集: %d 个 RSS 源", len(config.RSS_SOURCES))
    log.info("  模型: %s", config.MODEL_NAME)
    log.info("=" * 60)

    # ---- 1. 采集层 + 2. 过滤层（仅非复用路径执行） ----
    if not reused:
        log.info("")
        log.info("%s", "=" * 40)
        log.info("  第 1 层：多模态数据采集")
        log.info("%s", "=" * 40)
        raw_pool = collect_all()
        tl.mark("采集", "rss_fetch", "ok" if raw_pool else "failed",
                f"{len(raw_pool)} 条原始")

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
        tl.mark("过滤", "dedupe", "ok" if clean_items else "failed",
                f"{report.total_input} -> {report.total_output}")
        # 落盘去重后原始数据，供本次之后的同日重跑复用
        save_clean_items(clean_items)
    else:
        tl.mark("采集", "rss_fetch", "skipped", "复用同日缓存")
        tl.mark("过滤", "dedupe", "skipped", "复用同日缓存")

    # ---- 3. AI 分析层 ----
    log.info("")
    log.info("%s", "=" * 40)
    log.info("  第 3 层：AI 分析与简报生成")
    log.info("%s", "=" * 40)

    trivia = get_today_trivia()
    log.info("  今日彩蛋: %s", trivia)

    final_items = []
    daily_analysis = ""
    ai_failed = False
    style_name = ""  # 空数据路径不经过 call_ai_analysis，预置防止 NameError

    if not clean_items:
        log.info("  过滤后无可用数据，发送空报告邮件")
        ai_failed = True
        tl.mark("分析", "ai_analysis", "skipped", "无可用数据")
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
            tl.mark("分析", "ai_analysis", "ok", f"{len(final_items)} 条")
        else:
            ai_failed = True
            tl.mark("分析", "ai_analysis", "degraded", "AI 返回空，走降级兜底")

    # ---- AI 失败兜底：用原始采集数据直接拼简报，保证有内容 ----
    if ai_failed and not final_items and clean_items:
        log.warning(
            "  AI 分析失败（已过滤 %d 条新闻），启用降级兜底："
            "直接使用原始新闻生成简报（未经润色、无深度分析）",
            len(clean_items),
        )
        final_items = _build_fallback_items(clean_items)

    # ---- 英文标题翻译兜底 ----
    if final_items and not ai_failed:
        final_items = _translate_english_titles(final_items)
        tl.mark("分析", "translate", "ok", f"{len(final_items)} 条")

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

    # ---- 回填发布时间（采集层 published_at，按 URL / 标题回关联） ----
    _attach_published_at(final_items, clean_items)

    # ---- 统一生成时间戳（北京时间），网页 / 邮件 / RSS 共用同一时刻 ----
    generated_at = config.now_bjt().strftime("%Y-%m-%d %H:%M（北京时间）")

    # ---- GitHub Trending（独立模块，异常时不影响主流程） ----
    log.info("")
    log.info("  -- 抓取 GitHub Trending 项目 --")
    try:
        trending_projects = fetch_github_trending()
        tl.mark("采集", "trending",
                "ok" if trending_projects else "skipped",
                f"{len(trending_projects)} 个")
    except Exception as e:
        log.warning("  GitHub Trending 抓取异常，本期跳过项目推荐: %s", e)
        trending_projects = []
        tl.mark("采集", "trending", "failed", f"{type(e).__name__}")
    if trending_projects:
        log.info("  本周热门学习项目: %d 个", len(trending_projects))
        for p in trending_projects:
            log.info("    %s (%s)", p["name"], p["tag"])
    else:
        log.info("  今日暂无合适的 Trending 项目推荐")

    # ---- 写入网页 HTML ----
    log.info("")
    log.info("  -- 写入网页 HTML --")
    write_html(final_items, daily_analysis, trending_projects, generated_at=generated_at,
               style_name=style_name if not ai_failed else "降级")
    tl.mark("生成", "html_render", "ok", f"{len(final_items)} 条")

    # ---- 生成邮件 HTML（分类版） + RSS Feed ----
    log.info("")
    log.info("  -- 生成邮件（分类版）+ RSS Feed --")
    if ai_failed and not final_items:
        make_email_with_categories(
            [], f"今日无可用新闻。过滤报告：采集 {report.total_input} 条 -> "
                f"过滤后 {report.total_output} 条。",
            trending_projects, filter_report=report,
            style_name="", trivia=trivia, generated_at=generated_at,
        )
    else:
        make_email_with_categories(
            final_items, daily_analysis, trending_projects,
            filter_report=report,
            style_name=style_name if not ai_failed else "降级",
            trivia=trivia, generated_at=generated_at,
        )
    generate_rss_feed(final_items, daily_analysis, generated_at=generated_at)
    tl.mark("生成", "email_rss", "ok", f"{len(final_items)} 条")

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

    # ---- 阶段耗时汇总 ----
    tl.summary(log)

    # ---- 当日运行摘要（JSON，logs/ 已被 gitignore） ----
    try:
        summary_path = _write_daily_summary(
            tl.to_dict(),
            news_count=len(final_items),
            projects_count=len(trending_projects),
            total_input=report.total_input,
            total_output=report.total_output,
            ai_failed=ai_failed,
            style=style_name if not ai_failed else "降级",
        )
        log.info("  运行摘要: %s", summary_path)
    except Exception as e:
        log.warning("  运行摘要写入失败: %s", e)

    # ---- 质量异常检查：流程成功但内容可能不合格时主动提醒 ----
    issues = _collect_quality_issues(final_items, report, ai_failed)
    if issues:
        log.warning("  本次运行存在质量异常 %d 项:", len(issues))
        for it in issues:
            log.warning("    - %s", it)
        try:
            from src.delivery.send_email import send_quality_alert
            send_quality_alert(
                issues,
                summary=(f"指标: 新闻 {len(final_items)} 条 | 项目 {len(trending_projects)} 个 | "
                         f"过滤输入 {report.total_input} 条 | 风格 {style_name or '降级'}"),
            )
        except Exception as e:
            log.error("  质量异常提醒发送出错: %s", e)


def main():
    """入口：运行主流程；任意异常时发送失败告警（best-effort），随后按原样抛出。"""
    try:
        _run_main()
    except Exception as e:
        log.error("简报生成失败: %s", e, exc_info=True)
        try:
            from src.delivery.send_email import send_failure_alert
            send_failure_alert(e, phase="生成")
        except Exception as alert_err:
            log.error("发送失败告警时出错: %s", alert_err)
        try:
            from src.core.logger import log_structured
            log_structured(log, logging.ERROR, "briefing_failed",
                           error=f"{type(e).__name__}: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
