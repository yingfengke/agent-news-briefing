#!/usr/bin/env python3
"""
collector.py — 多模态数据采集层

职责：
  - RSS 源抓取与解析（18 个源，4 大类）
  - 动态网页爬虫（Playwright 驱动，4 个目标站）
  - 输出统一数据池（list[NewsItem]）

数据流向：采集层 → 过滤层 → 分析层
"""

import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

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
        content=content.strip()[:config.CRAWLER_SUMMARY_MAX],
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
    """
    all_items = []
    errors = []

    print(f"\n  ── RSS 采集 [{len(config.RSS_SOURCES)} 个源] ──")

    for name, url, lang in config.RSS_SOURCES:
        try:
            print(f"  → {name} ({lang}) ... ", end="", flush=True)
            limit = config.MAX_PER_SOURCE.get(name, 3)
            items = _parse_rss(_fetch(url), name)[:limit]
            if items:
                print(f"✔ {len(items)} 条")
                all_items.extend(items)
            else:
                # 主 URL 无结果，尝试 RSSHub fallback
                raise ValueError(f"0 条，尝试备用 RSS")
        except Exception as e:
            # 尝试 RSSHub 备用 URL
            fallback_url = config.RSS_FALLBACKS.get(name)
            if fallback_url:
                try:
                    print(f"⚠ 主RSS失败，尝试备用 ... ", end="", flush=True)
                    items = _parse_rss(_fetch(fallback_url), name)[:config.MAX_PER_SOURCE.get(name, 3)]
                    if items:
                        print(f"✔ {len(items)} 条 (备用)")
                        all_items.extend(items)
                    else:
                        print(f"✘ 备用也无数据")
                        errors.append(name)
                except Exception as e2:
                    print(f"✘ 备用也失败: {str(e2)[:40]}")
                    errors.append(name)
            else:
                print(f"✘ {str(e)[:60]}")
                errors.append(name)

    print(f"  RSS 共获取 {len(all_items)} 条")
    if errors:
        print(f"  [跳过] 失败源: {', '.join(errors)}")
    return all_items


# ============================================================
# 动态网页爬虫（Playwright）
# ============================================================

def _check_robots(site_url: str) -> bool:
    """检查 robots.txt 是否允许爬取"""
    parsed = urlparse(site_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        path = parsed.path or "/"
        allowed = rp.can_fetch(config.CRAWLER_USER_AGENT, path)
        print(f"    [robots.txt] {'允许' if allowed else '禁止'} 爬取 {site_url}")
        return allowed
    except Exception:
        print(f"    [robots.txt] 无法读取，默认允许")
        return True


def _crawl_site_playwright(name: str, site_url: str) -> list[NewsItem]:
    """
    使用 Playwright 爬取单站首页。
    返回统一 NewsItem 列表。
    """
    items = []

    if not _check_robots(site_url):
        return items

    print(f"\n  → 爬取 {name} ({site_url}) ... ", end="", flush=True)

    for attempt in range(1, config.CRAWLER_RETRIES + 1):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=config.CRAWLER_USER_AGENT)
                page.goto(site_url, wait_until="networkidle",
                          timeout=config.CRAWLER_TIMEOUT * 1000)

                # 随机延迟
                delay = random.uniform(config.CRAWLER_MIN_DELAY, config.CRAWLER_MAX_DELAY)
                time.sleep(delay)

                # 站点专用选择器（优先）或通用选择器
                site_selectors = config.CRAWLER_SITE_SELECTORS.get(name, {})
                container_sel = site_selectors.get("container", "")
                if container_sel:
                    articles = page.query_selector_all(container_sel)
                else:
                    # 通用选择器
                    articles = page.query_selector_all(
                        "article, .post-item, .article-item, .card, "
                        "a[href*='/article/'], a[href*='/p/'], a[href*='/news/']"
                    )
                if not articles:
                    articles = page.query_selector_all("h2 a, h3 a")

                count = 0
                seen_urls = set()
                for art in articles:
                    if count >= config.CRAWLER_MAX_ITEMS:
                        break
                    try:
                        link_el = art if art.tag_name == "a" else art.query_selector("a[href]")
                        if not link_el:
                            continue
                        href = link_el.get_attribute("href") or ""
                        if not href or href.startswith("#") or "javascript" in href:
                            continue

                        title = link_el.inner_text().strip()
                        if not title or len(title) < 8:
                            continue

                        full_url = urljoin(site_url, href)
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        # 提取摘要（优先站点专用选择器，再通用）
                        summary_set = site_selectors.get("summary", "")
                        summary_selectors = summary_set.split(", ") if summary_set else []
                        summary_selectors.extend([".summary", ".desc", ".excerpt",
                                                   ".abstract", "p", ".description"])
                        summary = title
                        for sel in summary_selectors:
                            if not sel:
                                continue
                            el = art.query_selector(sel)
                            if el:
                                txt = el.inner_text().strip()
                                if len(txt) > 10:
                                    summary = txt
                                    break

                        items.append(_build_item(
                            title, summary, full_url, f"{name}爬虫",
                            "zh", "crawler",
                        ))
                        count += 1
                    except Exception:
                        continue

                browser.close()

            print(f"✔ {count} 条")
            return items

        except Exception as e:
            if attempt <= config.CRAWLER_RETRIES:
                wait = config.CRAWLER_RETRY_DELAYS[attempt - 1]
                print(f"✘ 第{attempt}次 ({str(e)[:50]})，{wait}s后重试...")
                time.sleep(wait)
            else:
                print(f"✘ 3次重试均失败: {str(e)[:60]}")

    return items


def collect_crawler() -> list[NewsItem]:
    """
    运行所有动态爬虫目标站，返回合并的 NewsItem 列表。
    某个爬虫失败不影响其他爬虫。
    """
    all_items = []

    print(f"\n  ── 动态爬虫 [{len(config.CRAWLER_TARGETS)} 个站] ──")

    PlaywrightAvailable = False
    try:
        from playwright.sync_api import sync_playwright
        PlaywrightAvailable = True
    except ImportError:
        print("  [降级] Playwright 不可用，跳过动态爬虫")

    if not PlaywrightAvailable:
        return all_items

    for name, url in config.CRAWLER_TARGETS:
        try:
            items = _crawl_site_playwright(name, url)
            all_items.extend(items)
        except Exception as e:
            print(f"  [{name}] ✘ 异常: {str(e)[:60]}")

    print(f"  爬虫共采集 {len(all_items)} 条")
    return all_items


# ============================================================
# 旧版爬虫降级回退（无 Playwright 时使用）
# ============================================================

OLD_CHINESE_SITES = [
    ("量子位", "https://www.qbitai.com/"),
    ("IT之家AI", "https://www.ithome.com/tag/AI"),
]


def _scrape_old_fallback() -> list[NewsItem]:
    """
    旧版正则爬虫，仅在 Playwright 不可用时作为降级方案。
    使用 urllib 直接抓取 HTML，正则提取链接。
    """
    all_items = []
    for name, url in OLD_CHINESE_SITES:
        try:
            print(f"  → 旧版爬虫 {name} ({url}) ... ", end="", flush=True)
            req = Request(url, headers={
                "User-Agent": config.CRAWLER_USER_AGENT,
            })
            with urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8", "ignore")

            found = re.findall(
                r'<a[^>]*href="([^"]*)"[^>]*>([^<]{10,80})</a>',
                data, re.I
            )
            seen = set()
            count = 0
            for href, title in found:
                title = title.strip()
                if (len(title) < 10 or title in seen
                    or href.startswith("#") or "javascript" in href
                    or ".css" in href or ".js" in href):
                    continue
                if href.startswith("/"):
                    parsed = urlparse(url)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                seen.add(title)
                all_items.append(_build_item(title, title, href, name, "zh", "crawler"))
                count += 1
                if count >= 5:
                    break
            print(f"✔ {count} 条")
        except Exception as e:
            print(f"✘ {str(e)[:60]}")
    return all_items


# ============================================================
# 统一入口
# ============================================================

def collect_all() -> list[NewsItem]:
    """
    运行所有采集器，返回合并后的统一数据池。

    采集顺序：
      1. RSS 源（18 个）
      2. 动态爬虫（4 个目标站，Playwright）
      3. 若 Playwright 不可用 → 旧版爬虫降级
    """
    pool = []

    # 1. RSS
    pool.extend(collect_rss())

    # 2. 动态爬虫（Playwright）
    try:
        pool.extend(collect_crawler())
    except Exception as e:
        print(f"\n  [降级] 动态爬虫异常 ({e})，使用旧版爬虫")
        pool.extend(_scrape_old_fallback())

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
