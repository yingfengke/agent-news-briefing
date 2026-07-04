#!/usr/bin/env python3
"""
trending_fetcher.py — GitHub Trending 热门项目抓取

独立数据源，不经过过滤层和 AI 分析。
"""

import json
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from src import config


def fetch_github_trending():
    """
    直接爬取 github.com/trending 官方页面，解析热门项目。
    不依赖任何第三方 API。
    返回: [{"name","desc","stars","link","tag"}, ...]
    """
    TAG_MAP = config.TRENDING_TAG_MAP if hasattr(config, 'TRENDING_TAG_MAP') else {}

    urls = [
        "https://github.com/trending?since=daily",
        "https://github.com/trending?since=weekly",
    ]
    projects = []

    for url in urls:
        try:
            print(f"\n  -> 抓取 GitHub Trending 官方页面 ({url.split('=')[-1]}) ... ", end="", flush=True)
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")

            repo_blocks = re.findall(
                r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>([\s\S]*?)</article>',
                html, re.I
            )
            print(f"找到 {len(repo_blocks)} 个项目块 ... ", end="", flush=True)

            for block in repo_blocks:
                href_m = re.search(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', block)
                if not href_m:
                    continue
                full_name = href_m.group(1).strip()
                if "/" in full_name.replace("/", "", 1):
                    continue

                desc_m = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>\s*([\s\S]*?)\s*</p>', block)
                if not desc_m:
                    desc_m = re.search(r'<p[^>]*>\s*([^<]{10,200})\s*</p>', block)
                desc = re.sub(r'\s+', ' ', desc_m.group(1).strip()) if desc_m else ""
                desc = re.sub(r'<[^>]+>', '', desc).strip()

                stars_today_m = re.search(r'([\d,]+)\s*stars?\s*today', block, re.I)
                if stars_today_m:
                    stars_n = int(stars_today_m.group(1).replace(",", ""))
                    stars_str = f"star+{stars_n} today"
                else:
                    stars_str = "star N/A"
                    stars_n = 0

                text = f"{full_name} {desc}".lower()
                matched_tag = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        matched_tag = tag
                        break

                if matched_tag and len(desc) > 5 and full_name not in [p["name"] for p in projects]:
                    projects.append({
                        "name": full_name, "desc": desc[:100],
                        "stars": stars_str, "stars_n": stars_n,
                        "link": f"https://github.com/{full_name}", "tag": matched_tag,
                    })

            print(f" 筛出 {len(projects)} 个")
            if projects:
                break
        except Exception as e:
            print(f"失败 {e}")
            continue

    if not projects:
        print(f"\n  -> 备用：GitHub Search API ... ", end="", flush=True)
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
                text = f"{fn} {desc}".lower()
                mt = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        mt = tag
                        break
                if not mt:
                    mt = "Agent 框架"
                if fn and len(desc) > 5:
                    projects.append({
                        "name": fn, "desc": desc[:100],
                        "stars": f"star {sn:,}", "link": f"https://github.com/{fn}", "tag": mt,
                    })
                if len(projects) >= 3:
                    break
            print(f"备用找到 {len(projects)} 个")
        except Exception as e2:
            print(f"失败 {e2}")

    projects.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    for p in projects:
        p.pop("stars_n", None)
    return projects[:3]
