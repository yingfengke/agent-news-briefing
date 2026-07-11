#!/usr/bin/env python3
"""
trending_fetcher.py — GitHub Trending 热门项目抓取

使用 BeautifulSoup 解析 HTML（主路径，不依赖第三方 API）。
独立数据源，不经过过滤层和 AI 分析。

分类采用「GitHub topics 优先 + 知名仓库兜底 + 描述加权 + 其他」四层
（见 src/config/trending_tags.py），不再依赖易过时的静态关键词 first-match。
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src import config
from src.config import trending_tags as tt
from src.logger import get_logger

log = get_logger("trending")

# topics 端点需要此 Accept，否则返回空（易踩坑）
_TOPICS_ACCEPT = "application/vnd.github.mercy-preview+json"
_API_ACCEPT = "application/vnd.github+json"
# 只给可能展示的 Top N 拉 topics，控制 API 调用量
TOPICS_FETCH_LIMIT = 10


def _api_headers():
    """构造 API 请求头。

    有 GITHUB_TOKEN（workflow 配了 secret 即自动带上）：5000 次/小时，完全无忧；
    无 token（未配置 secret）：60 次/小时，Top 3 只需 3 次，也够用。
    两种情况都能跑，token 只是锦上添花，不强制依赖。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        "Accept": _API_ACCEPT,
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_topics(owner, repo, headers):
    """拉取仓库 topics；失败（超时/限流/404/仓库被删）一律返回空列表，交由下层兜底。"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/topics"
        req = Request(url, headers={**headers, "Accept": _TOPICS_ACCEPT})
        with urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                return data.get("names", []) or []
    except Exception:
        pass
    return []


def _extract_stars_today(article) -> int:
    """
    从 trending 文章块提取「今日新增 star 数」。

    关键修正：GitHub 把「总 star 数」链接与「stars today」文本放在同一父 <div> 下，
    若直接对该父容器 get_text() 会拼出 "456782,514 stars today"，导致取到累计总数而非日增。
    这里只取「自身直接文本节点包含 'stars today'」的元素（即最内层 span），
    用 recursive=False 排除子元素（如总 star 数链接）的干扰。
    """
    for tag in article.find_all(["span", "div", "a"]):
        direct = "".join(tag.find_all(text=True, recursive=False)).strip()
        if "stars today" in direct.lower():
            return _try_parse_int(direct)
    return 0


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
    api_headers = _api_headers()
    urls = [
        ("https://github.com/trending?since=daily", "daily"),
        ("https://github.com/trending?since=weekly", "weekly"),
    ]
    candidates = []

    for url, period in urls:
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
                if not desc or len(desc) < 5:
                    continue

                # 今日星标（只取直接文本，避免父容器把累计总数拼进来）
                stars_n = _extract_stars_today(article)
                candidates.append({
                    "name": full_name,
                    "desc": desc[:100],
                    "stars_n": stars_n,
                    "stars": f"star+{stars_n} today" if stars_n else "star N/A",
                    "link": f"https://github.com/{full_name}",
                })
            if candidates:
                break
        except Exception as e:
            log.warning("GitHub Trending 抓取失败: %s", e)
            continue

    # 主路径：按日增 star 排序，只给 Top N 拉 topics（控制 API 调用），再四层分类
    candidates.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    for c in candidates[:TOPICS_FETCH_LIMIT]:
        parts = c["name"].split("/")
        if len(parts) == 2:
            topics = fetch_topics(parts[0], parts[1], api_headers)
        else:
            topics = []
        c["tag"] = tt.classify_repo(topics, c["name"], c["desc"])

    if not candidates:
        log.info("  备用：GitHub Search API ...")
        try:
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            search_url = (f"https://api.github.com/search/repositories"
                          f"?q=topic:llm+topic:agent+created:>{week_ago}"
                          f"&sort=stars&order=desc&per_page=10")
            req2 = Request(search_url, headers=api_headers)
            with urlopen(req2, timeout=15) as r2:
                sdata = json.loads(r2.read().decode("utf-8"))
            for repo in sdata.get("items") or []:
                fn = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                sn = repo.get("stargazers_count", 0)
                if not fn or len(desc) < 5:
                    continue
                # Search API 返回项自带 topics 字段，L1 同样生效
                topics = repo.get("topics") or []
                candidates.append({
                    "name": fn,
                    "desc": desc[:100],
                    "stars": f"star {sn:,}",
                    "link": f"https://github.com/{fn}",
                    "tag": tt.classify_repo(topics, fn, desc),
                })
                if len(candidates) >= 3:
                    break
            log.info("  备用找到 %d 个", len(candidates))
        except Exception as e2:
            log.warning("备用 API 失败: %s", e2)

    for p in candidates:
        p.pop("stars_n", None)
    return candidates[:3]
