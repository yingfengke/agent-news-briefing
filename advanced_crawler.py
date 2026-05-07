#!/usr/bin/env python3
"""
advanced_crawler.py — 多模态数据采集系统·动态网页爬虫模块

用途：个人学习与研究，非商业目的
遵守 robots.txt 规则，仅提取标题与摘要（不超过150字），附带原文链接导流回原网站。
不爬取任何个人信息、用户评论或非公开内容。
每个源每天最多爬取1次。

项目链接: https://github.com/yingfengke/agent-news-briefing
"""

import json
import os
import re
import time
import random
from datetime import datetime
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

# ============================================================
# 配置
# ============================================================

# 透明身份 User-Agent（含项目链接和用途说明）
CRAWLER_USER_AGENT = (
    "Mozilla/5.0 (compatible; AgentNewsBriefing/1.0; "
    "+https://github.com/yingfengke/agent-news-briefing; "
    "Personal Learning Project)"
)

# 每个源每天最多爬取1次（由上层调度控制，此变量仅用于记录）
MAX_CRAWLS_PER_SOURCE_PER_DAY = 1

# 请求间隔（秒）
MIN_DELAY = 5
MAX_DELAY = 15

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 5

# 摘要最大长度
SUMMARY_MAX_LENGTH = 150

# 输出目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 已爬取记录文件（用于每日频次控制）
CRAWL_LOG_FILE = os.path.join(BASE_DIR, ".crawl_log.json")


def _load_crawl_log():
    """读取今日已爬取记录"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(CRAWL_LOG_FILE, "r") as f:
            log = json.load(f)
        return log.get(today, [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_crawl_log(source_name):
    """记录某源今日已被爬取"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(CRAWL_LOG_FILE, "r") as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log = {}
    if today not in log:
        log[today] = []
    if source_name not in log[today]:
        log[today].append(source_name)
    with open(CRAWL_LOG_FILE, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _can_crawl(source_name):
    """检查某源今天是否已爬取过"""
    return source_name not in _load_crawl_log()


# ============================================================
# robots.txt 合规检查
# ============================================================

def check_robots_txt(site_url):
    """
    检查目标网站的 robots.txt，只爬取允许的路径。

    robots.txt 地址: {site_url}/robots.txt
    """
    parsed = urlparse(site_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        path = parsed.path or "/"
        allowed = rp.can_fetch(CRAWLER_USER_AGENT, path)
        print(f"    [robots.txt] {robots_url} → {'允许' if allowed else '禁止'} 爬取 {path}")
        return allowed
    except Exception:
        # 无法读取 robots.txt 时保守处理：允许但不爬取受限页面
        print(f"    [robots.txt] {robots_url} → 无法读取，默认允许")
        return True


# ============================================================
# Playwright 工具函数
# ============================================================

def _random_delay():
    """随机等待 5-15 秒，模拟有礼貌的访客"""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    print(f"    [等待] {delay:.1f}秒 ...")
    time.sleep(delay)


def _extract_text(element, selector, default=""):
    """安全的元素文本提取"""
    try:
        el = element.query_selector(selector)
        return el.inner_text().strip() if el else default
    except Exception:
        return default


def _build_result(title, summary, link, source, published_at=""):
    """构建统一数据结构"""
    return {
        "id": hashlib.sha256(link.encode("utf-8")).hexdigest()[:16],
        "title": title.strip(),
        "content": summary.strip()[:SUMMARY_MAX_LENGTH],
        "url": link.strip(),
        "source": f"{source}爬虫",
        "lang": "zh",
        "source_type": "crawler",
        "crawled_at": datetime.now().isoformat(),
        "published_at": published_at,
    }


import hashlib


# ============================================================
# 目标站点爬取函数
# 每个函数都遵守：robots.txt 检查、身份透明、频率控制
# ============================================================

def crawl_jiqizhixin():
    """
    爬取机器之心官网首页文章列表

    目标: https://www.jiqizhixin.com
    robots.txt: https://www.jiqizhixin.com/robots.txt
    用途: 个人学习与研究，非商业目的
    仅提取标题和摘要（不超过150字），不全文转载
    """
    site_url = "https://www.jiqizhixin.com"
    source_name = "机器之心"
    items = []

    if not _can_crawl(source_name):
        print(f"  [跳过] {source_name} 今天已爬取过")
        return items

    if not check_robots_txt(site_url):
        print(f"  [跳过] {source_name} robots.txt 禁止爬取")
        return items

    print(f"\n  → 爬取 {source_name} ({site_url}) ... ", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=CRAWLER_USER_AGENT)
                page.goto(site_url, wait_until="networkidle", timeout=30000)
                _random_delay()

                # 提取文章列表
                articles = page.query_selector_all("article, .post-item, .article-item, .card")
                if not articles:
                    # 备用：找所有 h2/h3 中的链接
                    articles = page.query_selector_all("h2 a, h3 a")

                count = 0
                for art in articles:
                    if count >= 5:
                        break
                    try:
                        link_el = art.query_selector("a[href]")
                        if not link_el:
                            continue
                        href = link_el.get_attribute("href") or ""
                        title = link_el.inner_text().strip()
                        if not title or len(title) < 8:
                            continue
                        # 补全链接
                        if href.startswith("/"):
                            href = urljoin(site_url, href)

                        # 尝试提取摘要
                        summary = ""
                        for sel in [".summary", ".desc", "p", ".excerpt", ".abstract"]:
                            summary = _extract_text(art, sel)
                            if summary and len(summary) > 10:
                                break
                        if not summary or len(summary) < 10:
                            summary = title

                        items.append(_build_result(title, summary, href, source_name))
                        count += 1
                    except Exception:
                        continue

                browser.close()

            print(f"✔ {count} 条")
            _save_crawl_log(source_name)
            return items

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"✘ 第{attempt}次失败 ({e})，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✘ 3次重试均失败: {e}")

    return items


def crawl_qbitai():
    """
    爬取量子位官网首页

    目标: https://www.qbitai.com
    robots.txt: https://www.qbitai.com/robots.txt
    用途: 个人学习与研究，非商业目的
    仅提取标题和摘要（不超过150字），不全文转载
    """
    site_url = "https://www.qbitai.com"
    source_name = "量子位"
    items = []

    if not _can_crawl(source_name):
        print(f"  [跳过] {source_name} 今天已爬取过")
        return items

    if not check_robots_txt(site_url):
        print(f"  [跳过] {source_name} robots.txt 禁止爬取")
        return items

    print(f"\n  → 爬取 {source_name} ({site_url}) ... ", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=CRAWLER_USER_AGENT)
                page.goto(site_url, wait_until="networkidle", timeout=30000)
                _random_delay()

                articles = page.query_selector_all("article, .post, .entry, .item")
                count = 0
                for art in articles:
                    if count >= 5:
                        break
                    try:
                        link_el = art.query_selector("a[href]")
                        if not link_el:
                            continue
                        href = link_el.get_attribute("href") or ""
                        title = link_el.inner_text().strip()
                        if not title or len(title) < 8:
                            continue
                        if href.startswith("/"):
                            href = urljoin(site_url, href)

                        summary = ""
                        for sel in [".summary", ".desc", "p", ".excerpt"]:
                            summary = _extract_text(art, sel)
                            if summary and len(summary) > 10:
                                break
                        if not summary or len(summary) < 10:
                            summary = title

                        items.append(_build_result(title, summary, href, source_name))
                        count += 1
                    except Exception:
                        continue

                browser.close()

            print(f"✔ {count} 条")
            _save_crawl_log(source_name)
            return items

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"✘ 第{attempt}次失败 ({e})，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✘ 3次重试均失败: {e}")

    return items


def crawl_modelscope():
    """
    爬取魔搭社区首页文章/论文

    目标: https://www.modelscope.cn
    robots.txt: https://www.modelscope.cn/robots.txt
    用途: 个人学习与研究，非商业目的
    仅提取标题和摘要（不超过150字），不全文转载
    """
    site_url = "https://www.modelscope.cn"
    source_name = "魔搭社区"
    items = []

    if not _can_crawl(source_name):
        print(f"  [跳过] {source_name} 今天已爬取过")
        return items

    if not check_robots_txt(site_url):
        print(f"  [跳过] {source_name} robots.txt 禁止爬取")
        return items

    print(f"\n  → 爬取 {source_name} ({site_url}) ... ", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=CRAWLER_USER_AGENT)
                page.goto(site_url, wait_until="networkidle", timeout=30000)
                _random_delay()

                # 魔搭社区通常是 SPA 应用，尝试抓取可见的卡片
                articles = page.query_selector_all("[class*='card'], [class*='Card'], a[href*='/models/']")
                count = 0
                seen_urls = set()
                for art in articles:
                    if count >= 5:
                        break
                    try:
                        href = art.get_attribute("href") or ""
                        if not href or not href.startswith("/") or "models" not in href:
                            continue
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)
                        title = art.inner_text().strip().split("\n")[0]
                        if not title or len(title) < 5:
                            continue
                        full_url = urljoin(site_url, href)
                        items.append(_build_result(title, title, full_url, source_name))
                        count += 1
                    except Exception:
                        continue

                browser.close()

            print(f"✔ {count} 条")
            _save_crawl_log(source_name)
            return items

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"✘ 第{attempt}次失败 ({e})，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✘ 3次重试均失败: {e}")

    return items


def crawl_tencent_cloud_developer():
    """
    爬取腾讯云开发者社区AI板块

    目标: https://cloud.tencent.com/developer
    robots.txt: https://cloud.tencent.com/robots.txt
    用途: 个人学习与研究，非商业目的
    仅提取标题和摘要（不超过150字），不全文转载
    """
    site_url = "https://cloud.tencent.com/developer"
    source_name = "腾讯云开发者"
    items = []

    if not _can_crawl(source_name):
        print(f"  [跳过] {source_name} 今天已爬取过")
        return items

    if not check_robots_txt(site_url):
        print(f"  [跳过] {source_name} robots.txt 禁止爬取")
        return items

    print(f"\n  → 爬取 {source_name} ({site_url}) ... ", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=CRAWLER_USER_AGENT)
                page.goto(site_url, wait_until="networkidle", timeout=30000)
                _random_delay()

                articles = page.query_selector_all("a[href*='/developer/article/']")
                count = 0
                seen_urls = set()
                for art in articles:
                    if count >= 5:
                        break
                    try:
                        href = art.get_attribute("href") or ""
                        if not href or href in seen_urls:
                            continue
                        seen_urls.add(href)
                        title = art.inner_text().strip()
                        if not title or len(title) < 8:
                            continue
                        full_url = href if href.startswith("http") else urljoin(site_url, href)

                        # 尝试提取摘要
                        parent = art.evaluate("el => el.closest('div')")
                        summary = title
                        if parent:
                            for sel in [".summary", ".desc", "p", ".text"]:
                                try:
                                    s = parent.query_selector(sel)
                                    if s:
                                        st = s.inner_text().strip()
                                        if len(st) > 10:
                                            summary = st
                                            break
                                except Exception:
                                    continue

                        items.append(_build_result(title, summary, full_url, source_name))
                        count += 1
                    except Exception:
                        continue

                browser.close()

            print(f"✔ {count} 条")
            _save_crawl_log(source_name)
            return items

        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"✘ 第{attempt}次失败 ({e})，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"✘ 3次重试均失败: {e}")

    return items


# ============================================================
# 统一入口
# ============================================================

def run_all_crawlers():
    """
    运行所有爬虫，返回合并后的统一数据列表。
    每个爬虫独立运行，互不干扰。
    某个爬虫失败不影响其他爬虫。
    """
    all_items = []
    crawlers = [
        ("机器之心", crawl_jiqizhixin),
        ("量子位", crawl_qbitai),
        ("魔搭社区", crawl_modelscope),
        ("腾讯云开发者社区", crawl_tencent_cloud_developer),
    ]

    print(f"\n{'=' * 60}")
    print("  动态网页爬虫模块 — 采集开始")
    print(f"{'=' * 60}")

    for name, func in crawlers:
        try:
            items = func()
            all_items.extend(items)
            print(f"  [{name}] {len(items)} 条")
        except Exception as e:
            print(f"  [{name}] ✘ 爬虫异常: {e}")

    print(f"\n  爬虫模块共采集 {len(all_items)} 条新闻")
    return all_items


# ============================================================
# 独立测试入口
# ============================================================

if __name__ == "__main__":
    results = run_all_crawlers()
    print(f"\n  爬虫运行完毕，共 {len(results)} 条结果")
    for r in results:
        print(f"  📌 [{r['source']}] {r['title'][:50]}")
        print(f"     {r['url']}")
