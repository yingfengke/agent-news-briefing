#!/usr/bin/env python3
"""
collector.py — 多模态数据采集层

职责：
  - RSS 源抓取与解析（21 个源，4 大类）
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
from datetime import datetime
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

        # 发布时间
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime.fromtimestamp(time.mktime(entry.published_parsed)).isoformat()
        elif hasattr(entry, "published"):
            published = entry.published

        items.append(_build_item(
            title, content_clean, link, source_name,
            _detect_lang(source_name), "rss",
            published_at=published,
        ))

    return items


def _detect_lang(source_name: str) -> str:
    """根据来源名判断语言"""
    for name, _, lang in config.RSS_SOURCES:
        if name == source_name:
            return lang
    # 不在 RSS 配置中（爬虫来源），看中文源集合
    return "zh" if source_name in config.CHINESE_SOURCE_NAMES else "en"


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
    单个源失败不影响整体。
    """
    all_items = []
    source_status = {}

    log.info("")
    log.info("  RSS 采集 [%d 个源，并发数 %d]", len(config.RSS_SOURCES), CONCURRENT_WORKERS)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {
            executor.submit(_collect_single_source, name, url, lang): name
            for name, url, lang in config.RSS_SOURCES
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
