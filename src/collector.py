#!/usr/bin/env python3
"""
collector.py — 多模态数据采集层

职责：
  - RSS 源抓取与解析（35 个源）
  - 输出统一数据池（list[NewsItem]）

数据流向：采集层 → 过滤层 → 分析层
"""

import concurrent.futures
import hashlib
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import feedparser

from src import config
from src.models import NewsItem
from src.logger import get_logger, log_structured

log = get_logger("collector")


# ============================================================
# 工具函数
# ============================================================

def _make_id(url: str) -> str:
    """从 URL 生成唯一 ID"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    """当前时间 ISO 格式"""
    return datetime.now().isoformat()


def _build_item(title, content, url, source, lang, source_type,
                published_at="", tags=None) -> NewsItem:
    """统一构建 NewsItem"""
    return NewsItem(
        id=_make_id(url),
        title=title.strip(),
        content=content.strip()[:config.SUMMARY_MAX_LENGTH],
        url=url.strip(),
        source=source,
        lang=lang,
        source_type=source_type,
        crawled_at=_now_iso(),
        published_at=published_at,
        tags=tags or [],
    )


# ============================================================
# RSS 抓取
# ============================================================

RSS_TIMEOUT = 15
RSS_RETRIES = 2                    # 指数退避重试次数
RSS_BACKOFF_BASE = 2               # 初始退避秒数
CONCURRENT_WORKERS = 8             # 并行采集并发数
RSS_USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/2.0)"


# ============================================================
# RSS 源健康跟踪
# ============================================================

def _load_source_health() -> dict[str, int]:
    """读取源连续失败次数记录"""
    if os.path.exists(config.SOURCE_HEALTH_FILE):
        try:
            with open(config.SOURCE_HEALTH_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_source_health(health: dict[str, int]) -> None:
    """保存源连续失败次数记录"""
    try:
        with open(config.SOURCE_HEALTH_FILE, "w") as f:
            json.dump(health, f)
    except OSError:
        pass


def _update_source_health(name: str, success: bool) -> dict[str, int]:
    """
    更新单个源的连续失败计数并保存。
    success=True → 重置为 0；success=False → 递增。
    返回更新后的全量健康数据。
    """
    health = _load_source_health()
    if success:
        health[name] = 0
    else:
        health[name] = health.get(name, 0) + 1
    _save_source_health(health)
    return health


def _fetch(url: str) -> bytes:
    """带指数退避重试的 HTTP GET 请求"""
    last_exc = None
    for attempt in range(1 + RSS_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": RSS_USER_AGENT})
            with urlopen(req, timeout=RSS_TIMEOUT) as resp:
                return resp.read()
        except Exception as e:
            last_exc = e
            if attempt < RSS_RETRIES:
                delay = RSS_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _parse_rss(raw: bytes, source_name: str) -> list[NewsItem]:
    """
    使用 feedparser 解析 RSS / Atom，返回 NewsItem 列表。

    feedparser 优势：
      - 自动识别 RSS 2.0 / Atom / RDF
      - 容错处理格式松散的 XML（如机器之心）
      - 自动处理 content:encoded 命名空间
      - 自动提取 published 时间
    """
    items = []
    feed = feedparser.parse(raw)

    if feed.bozo and not feed.entries:
        # bozo=1 且无条目 -> 真实解析失败（如返回的是 HTML 不是 XML）
        log.warning("feedparser 解析失败 (bozo): %s", feed.bozo_exception)
        return items

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        # 提取正文内容：优先 content，再 summary，再 description
        content_raw = ""
        if hasattr(entry, "content") and entry.content:
            content_raw = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content_raw = entry.summary or ""
        elif hasattr(entry, "description"):
            content_raw = entry.description or ""

        # 清理 HTML 标签
        content_clean = re.sub(r"<[^>]+>", " ", content_raw)
        content_clean = re.sub(r"\s+", " ", content_clean).strip()[:config.SUMMARY_MAX_LENGTH]

        # 发布时间：优先 published_parsed，再 published，再 updated_parsed，再 updated
        # 注意：feedparser 的 *_parsed 是 UTC 时间（struct_time）。
        # 用 time.mktime 会按本地时区解释，导致 +8h 偏移；这里直接按 UTC 构造。
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        elif hasattr(entry, "published"):
            published = entry.published
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
        elif hasattr(entry, "updated"):
            published = entry.updated

        items.append(_build_item(
            title, content_clean, link, source_name,
            _detect_lang(source_name, title), "rss",
            published_at=published,
        ))

    return items


def _detect_lang(source_name: str, title_or_content: str = "") -> str:
    """
    判断新闻语言。
    优先查 RSS_SOURCES 配置表；
    次优查 CHINESE_SOURCE_NAMES 集合；
    最后尝试基于内容检测（包含中文字符则判定为中文）。
    """
    for name, _, lang in config.RSS_SOURCES:
        if name == source_name:
            return lang
    if source_name in config.CHINESE_SOURCE_NAMES:
        return "zh"
    # 内容回退检测：包含中文字符 → 中文
    if title_or_content and re.search(r"[\u4e00-\u9fff]", title_or_content):
        return "zh"
    return "en"


def _collect_single_source(name: str, url: str, lang: str) -> dict:
    """采集单个 RSS 源（可被 ThreadPoolExecutor 并行调用）"""
    limit = config.MAX_PER_SOURCE.get(name, 3)
    result = {"name": name, "items": [], "status": "fail", "count": 0, "error": ""}

    try:
        raw = _fetch(url)
        items = _parse_rss(raw, name)[:limit]
        if items:
            result["items"] = items
            result["status"] = "success"
            result["count"] = len(items)
            return result
        raise ValueError("0 条")
    except Exception as e:
        # 尝试 RSSHub 备用 URL
        fallback_url = config.RSS_FALLBACKS.get(name)
        if fallback_url:
            try:
                raw = _fetch(fallback_url)
                items = _parse_rss(raw, name)[:limit]
                if items:
                    result["items"] = items
                    result["status"] = "success(fallback)"
                    result["count"] = len(items)
                    return result
                result["error"] = "备用RSS无数据"
            except Exception as e2:
                result["error"] = str(e2)[:50]
        else:
            result["error"] = str(e)[:50]
        return result


def collect_rss() -> list[NewsItem]:
    """
    并发抓取所有 RSS 源（ThreadPoolExecutor），返回 NewsItem 列表。
    单个源失败不影响整体。连续失败超过 SOURCE_HEALTH_MAX_FAILURES 次的源自动跳过。
    """
    all_items = []
    source_status = {}

    log.info("")
    log.info("  RSS 采集 [%d 个源，并发数 %d]", len(config.RSS_SOURCES), CONCURRENT_WORKERS)

    # 读取源健康状态，跳过连续失败过多的源
    health = _load_source_health()
    max_fail = config.SOURCE_HEALTH_MAX_FAILURES
    skipped_sources = []
    active_sources = []
    for name, url, lang in config.RSS_SOURCES:
        fail_count = health.get(name, 0)
        if fail_count >= max_fail:
            skipped_sources.append((name, fail_count))
        else:
            active_sources.append((name, url, lang))

    if skipped_sources:
        log.warning("  跳过 %d 个连续失败源:", len(skipped_sources))
        for name, cnt in sorted(skipped_sources):
            log.warning("      %s (%d 次)", name, cnt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {
            executor.submit(_collect_single_source, name, url, lang): name
            for name, url, lang in active_sources
        }

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            name = result["name"]
            status = result["status"]
            count = result["count"]

            if status == "success":
                log.info("  -> %s: %d 条", name, count)
            elif status == "success(fallback)":
                log.info("  -> %s: %d 条 (备用)", name, count)
            else:
                log.warning("  -> %s: 失败 %s", name, result["error"])

            # 更新源健康状态
            _update_source_health(name, status.startswith("success"))

            source_status[name] = {
                "status": status,
                "count": count,
                "error": result.get("error", ""),
            }
            all_items.extend(result["items"])

    # 清晰汇总：成功源与失败源分开统计
    success_items = [(k, v) for k, v in source_status.items()
                     if v["status"].startswith("success")]
    failed_items = [(k, v) for k, v in source_status.items()
                    if v["status"] == "fail"]

    log.info("  RSS 共获取 %d 条", len(all_items))
    if success_items:
        log.info("  成功 %d 个源:", len(success_items))
        for k, v in sorted(success_items):
            tag = " (备用)" if v["status"] == "success(fallback)" else ""
            log.info("     %s: %d条%s", k, v["count"], tag)
    if failed_items:
        log.warning("  失败 %d 个源:", len(failed_items))
        for k, v in sorted(failed_items):
            log.warning("     %s: %s", k, v["error"])

    log_structured(
        log, logging.INFO, "rss_collect_complete",
        total_items=len(all_items),
        success_sources=len(success_items),
        failed_sources=len(failed_items),
    )
    return all_items


def collect_all() -> list[NewsItem]:
    """
    运行所有采集器，返回合并后的统一数据池。

    采集：RSS 源（21 个）
    """
    pool = []

    # RSS
    pool.extend(collect_rss())

    log.info("")
    log.info("  数据池总计: %d 条新闻", len(pool))
    if pool:
        log.info("     来源: %d 个不同源", len(set(it.source for it in pool)))
    return pool


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    items = collect_all()
    print(f"\n  采集完成，共 {len(items)} 条")
    for it in items[:5]:
        print(f"  [{it.source}] {it.title[:50]}")
