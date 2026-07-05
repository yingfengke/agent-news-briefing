#!/usr/bin/env python3
"""
trending_fetcher.py — GitHub Trending 热门项目抓取

使用 BeautifulSoup 解析 HTML，替代脆弱的正则表达式方案。

独立数据源，不经过过滤层和 AI 分析。
"""

import json
import logging
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src import config
from src.logger import get_logger

log = get_logger("trending")


def _try_parse_int(text: str) -> int:
    """尝试从文本中提取整数（如 '1,234 stars today' -> 1234）"""
    nums = re.findall(r'[\d,]+', text)
    if nums:
        return int(nums[0].replace(",", ""))
    return 0


def fetch_github_trending():
    """
    用 BeautifulSoup 解析 github.com/trending 官方页面。
    不依赖任何第三方 API。
    返回: [{"name","desc","stars","link","tag"}, ...]
    """
    TAG_MAP = config.TRENDING_TAG_MAP if hasattr(config, 'TRENDING_TAG_MAP') else {}

    urls = [
        ("https://github.com/trending?since=daily", "daily"),
        ("https://github.com/trending?since=weekly", "weekly"),
    ]
    all_projects = []

    for url, period in urls:
        projects = []
        try:
            log.info("  抓取 GitHub Trending (%s) ...", period)
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")

            soup = BeautifulSoup(html, "html.parser")
            repo_articles = soup.find_all("article", class_=lambda c: c and "Box-row" in c)
            log.info("  找到 %d 个项目块", len(repo_articles))

            for article in repo_articles:
                # 仓库全名
                h2 = article.find("h2")
                if not h2:
                    continue
                a_tag = h2.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                full_name = a_tag["href"].strip("/")

                # 描述
                desc = ""
                p_tag = article.find("p", class_=lambda c: c and "col-9" in c)
                if p_tag:
                    desc = p_tag.get_text(strip=True)
                if not desc or len(desc) < 5:
                    p_tag = article.find("p")
                    if p_tag:
                        desc = p_tag.get_text(strip=True)

                # 今日星标
                stars_str = ""
                stars_n = 0
                # 查找包含 "stars today" 的标签
                for tag in article.find_all(["span", "div", "a"]):
                    text = tag.get_text(strip=True)
                    if "stars today" in text.lower():
                        stars_n = _try_parse_int(text)
                        stars_str = f"star+{stars_n} today"
                        break
                if not stars_str:
                    stars_str = "star N/A"

                # 标签匹配
                combined = f"{full_name} {desc}".lower()
                matched_tag = ""
                for kw, tag in TAG_MAP.items():
                    if kw in combined:
                        matched_tag = tag
                        break

                if matched_tag and len(desc) > 5 and full_name not in [p["name"] for p in projects]:
                    projects.append({
                        "name": full_name, "desc": desc[:100],
                        "stars": stars_str, "stars_n": stars_n,
                        "link": f"https://github.com/{full_name}", "tag": matched_tag,
                    })

            log.info("  筛出 %d 个", len(projects))
            all_projects.extend(projects)
            if all_projects:
                break
        except Exception as e:
            log.warning("GitHub Trending 抓取失败: %s", e)
            continue

    if not all_projects:
        log.info("  备用：GitHub Search API ...")
        try:
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            search_url = (f"https://api.github.com/search/repositories"
                          f"?q=topic:llm+topic:agent+created:>{week_ago}"
                          f"&sort=stars&order=desc&per_page=10")
            req2 = Request(search_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
                "Accept": "application/vnd.github+json",
            })
            with urlopen(req2, timeout=15) as r2:
                sdata = json.loads(r2.read().decode("utf-8"))
            for repo in sdata.get("items") or []:
                fn = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                sn = repo.get("stargazers_count", 0)
                combined = f"{fn} {desc}".lower()
                mt = ""
                for kw, tag in TAG_MAP.items():
                    if kw in combined:
                        mt = tag
                        break
                if not mt:
                    mt = "Agent 框架"
                if fn and len(desc) > 5:
                    all_projects.append({
                        "name": fn, "desc": desc[:100],
                        "stars": f"star {sn:,}", "link": f"https://github.com/{fn}", "tag": mt,
                    })
                if len(all_projects) >= 3:
                    break
            log.info("  备用找到 %d 个", len(all_projects))
        except Exception as e2:
            log.warning("备用 API 失败: %s", e2)

    all_projects.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    for p in all_projects:
        p.pop("stars_n", None)
    return all_projects[:3]
