#!/usr/bin/env python3
"""
collector.py — 多模态数据采集层

职责：
  - RSS 源抓取与解析（21 个源，4 大类）
  - 输出统一数据池（list[NewsItem]）

数据流向：采集层 → 过滤层 → 分析层
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import feedparser

import config
from models import NewsItem


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
RSS_USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/2.0)"


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": RSS_USER_AGENT})
    with urlopen(req, timeout=RSS_TIMEOUT) as resp:
        return resp.read()


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
        # bozo=1 且无条目 → 真实解析失败（如返回的是 HTML 不是 XML）
        print(f"  ⚠ feedparser 解析失败 (bozo): {feed.bozo_exception}")
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
        content_clean = re.sub(r"\s+", " ", content_clean).strip()[:200]

        # 发布时间
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            from time import mktime
            published = datetime.fromtimestamp(mktime(entry.published_parsed)).isoformat()
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


def collect_rss() -> list[NewsItem]:
    """
    抓取所有 RSS 源，返回 NewsItem 列表。
    单个源失败不影响整体。
    使用 source_status 字典精确跟踪每个源的状态（不再依赖 except 副作用）。
    """
    all_items = []
    source_status = {}  # name -> {"status": str, "count": int, "error": str}

    print(f"\n  ── RSS 采集 [{len(config.RSS_SOURCES)} 个源] ──")

    for name, url, lang in config.RSS_SOURCES:
        try:
            print(f"  → {name} ({lang}) ... ", end="", flush=True)
            limit = config.MAX_PER_SOURCE.get(name, 3)
            items = _parse_rss(_fetch(url), name)[:limit]
            if items:
                print(f"✔ {len(items)} 条")
                source_status[name] = {"status": "success", "count": len(items)}
                all_items.extend(items)
            else:
                raise ValueError("0 条，尝试备用 RSS")
        except Exception as e:
            # 尝试 RSSHub 备用 URL
            fallback_url = config.RSS_FALLBACKS.get(name)
            if fallback_url:
                try:
                    print(f"⚠ 主RSS失败，尝试备用 ... ", end="", flush=True)
                    items = _parse_rss(_fetch(fallback_url), name)[:config.MAX_PER_SOURCE.get(name, 3)]
                    if items:
                        print(f"✔ {len(items)} 条 (备用)")
                        source_status[name] = {"status": "success(fallback)", "count": len(items)}
                        all_items.extend(items)
                    else:
                        print(f"✘ 备用也无数据")
                        source_status[name] = {"status": "fail", "count": 0, "error": "备用RSS无数据"}
                except Exception as e2:
                    print(f"✘ 备用也失败: {str(e2)[:40]}")
                    source_status[name] = {"status": "fail", "count": 0, "error": str(e2)[:50]}
            else:
                print(f"✘ {str(e)[:60]}")
                source_status[name] = {"status": "fail", "count": 0, "error": str(e)[:50]}

    # 清晰汇总：成功源与失败源分开统计
    success_items = [(k, v) for k, v in source_status.items()
                     if v["status"].startswith("success")]
    failed_items = [(k, v) for k, v in source_status.items()
                    if v["status"] == "fail"]

    print(f"  RSS 共获取 {len(all_items)} 条")
    if success_items:
        print(f"  ✅ 成功源 ({len(success_items)} 个):")
        for k, v in success_items:
            tag = " (备用)" if v["status"] == "success(fallback)" else ""
            print(f"     {k}: {v['count']}条{tag}")
    if failed_items:
        print(f"  ❌ 失败源 ({len(failed_items)} 个):")
        for k, v in failed_items:
            print(f"     {k}: {v['error']}")
    return all_items


def collect_all() -> list[NewsItem]:
    """
    运行所有采集器，返回合并后的统一数据池。

    采集：RSS 源（21 个）
    """
    pool = []

    # RSS
    pool.extend(collect_rss())

    print(f"\n  📦 数据池总计: {len(pool)} 条新闻")
    if pool:
        print(f"     来源: {len(set(it.source for it in pool))} 个不同源")
    return pool


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    items = collect_all()
    print(f"\n  采集完成，共 {len(items)} 条")
    for it in items[:5]:
        print(f"  [{it.source}] {it.title[:50]}")
