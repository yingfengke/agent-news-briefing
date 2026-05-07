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
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

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


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"(Article|Comments)\s*URL\s*:\s*https?://\S+", "", text, flags=re.I)
    text = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200] if len(text) > 200 else text


def _text(el, tag, ns=None):
    child = el.find(tag, ns or {})
    return child.text.strip() if child is not None and child.text else ""


def _parse_rss(xml_data: bytes, source_name: str) -> list[NewsItem]:
    """解析 RSS / Atom 格式，返回 NewsItem 列表"""
    items = []
    root = ET.fromstring(xml_data)

    # RSS 2.0
    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        desc = _text(item, "description") or _text(item, "content:encoded") or ""
        pub = _text(item, "pubDate") or _text(item, "dc:date")
        if title and link:
            items.append(_build_item(
                title, _clean(desc), link, source_name,
                _detect_lang(source_name), "rss", published_at=pub,
            ))

    # Atom
    if not items:
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = _text(entry, "a:title", {"a": "http://www.w3.org/2005/Atom"})
            href_el = entry.find("a:link", {"a": "http://www.w3.org/2005/Atom"})
            link = href_el.get("href") if href_el is not None else ""
            desc = _text(entry, "a:summary", {"a": "http://www.w3.org/2005/Atom"}) \
                   or _text(entry, "a:content", {"a": "http://www.w3.org/2005/Atom"}) or ""
            pub = _text(entry, "a:published", {"a": "http://www.w3.org/2005/Atom"}) \
                  or _text(entry, "a:updated", {"a": "http://www.w3.org/2005/Atom"})
            if title and link:
                items.append(_build_item(
                    title, _clean(desc), link, source_name,
                    _detect_lang(source_name), "rss", published_at=pub,
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
            print(f"✔ {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
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

                # 通用文章提取
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

                        # 提取摘要（优先用描述性元素）
                        summary = title
                        for sel in [".summary", ".desc", ".excerpt",
                                    ".abstract", "p", ".description"]:
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
            if attempt < config.CRAWLER_RETRIES:
                wait = config.CRAWLER_RETRY_DELAY
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
