#!/usr/bin/env python3
"""
trending_fetcher.py — GitHub Trending 热门项目抓取

使用 BeautifulSoup 解析 HTML（主路径，不依赖第三方 API）。
独立数据源，不经过过滤层和 AI 分析。

分类采用「GitHub topics 优先 + 知名仓库兜底 + 描述加权 + 其他」四层
（见 src/config/trending_tags.py），不再依赖易过时的静态关键词 first-match。

2026-09-02 修复（推荐长期漏推 deepseek-harness 类爆款）：
1. 主路径每榜重试 3 次 + 请求头 Connection: close / Accept-Encoding: identity，
   治 GitHub 偶发 IncompleteRead 传输截断（本地实测 daily 页 2/3 概率截断）；
2. 榜单内过滤分类为「其他」的非 AI 项目（如卫星模拟器混入 AI 推荐）；
3. Search API 兜底从「topic:llm+topic:agent AND + created:>7 天」改为
   「近 30 天 + 多组 AI topic 各自查询合并」——原查询词把 8/13 开源的
   deepseek-harness（创建超 7 天、topics 为 ai-agents/cordis/dsh 无精确 llm+agent）
   双保险排除，且 7 天内双 topic 精确匹配只搜到 <50 星的噪声仓库。
"""

import json
import logging
import os
import re
import urllib.error
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src import config
from src.config import trending_tags as tt
from src.core.logger import get_logger

log = get_logger("trending")

# topics 端点需要此 Accept，否则返回空（易踩坑）
_TOPICS_ACCEPT = "application/vnd.github.mercy-preview+json"
_API_ACCEPT = "application/vnd.github+json"
# 只给可能展示的 Top N 拉 topics，控制 API 调用量
TOPICS_FETCH_LIMIT = 10
# 每榜抓取重试次数（GitHub Trending 响应偶发 IncompleteRead 截断）
_PAGE_RETRIES = 3
# 网络超时（秒）：topics 单仓库 / Search API 单查询 / Trending HTML 整页
_TIMEOUT_TOPICS = 5
_TIMEOUT_SEARCH = 15
_TIMEOUT_HTML = 20
# HTML 正常返回但解析出 0 条时的告警阈值：超过说明页面结构可能已变更
_HTML_STRUCTURE_WARN_BYTES = 10000
# Search API 兜底参数
_SEARCH_TOPICS = ["llm", "agent", "ai-agents", "mcp", "rag"]
_FALLBACK_MIN_STARS = 300
_FALLBACK_DAYS = 30


def _api_headers():
    """构造 API 请求头。

    有 GITHUB_TOKEN（workflow 配了 secret 即自动带上）：
      core API 5000 次/小时、Search API 30 次/分钟，完全无忧；
    无 token（未配置 secret）：
      core API 60 次/小时（Top 10 topics 只需 10 次，够用）、
      Search API 10 次/分钟（兜底 5 组查询落在单分钟配额内，但同日多次触发会叠加，
      见 _search_fallback 的 403/429 显式处理）。
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
        with urlopen(req, timeout=_TIMEOUT_TOPICS) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                return data.get("names", []) or []
    except urllib.error.HTTPError as e:
        # 限流值得记录（分类会因 topics 缺失退化为纯 desc 关键词，准确性下降）
        if e.code in (403, 429):
            log.warning("topics 拉取被限流(%d): %s/%s", e.code, owner, repo)
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
    """尝试从「N stars today」文本中提取整数（如 '1,234 stars today' -> 1234）。

    锚定 stars today 之前的数字，避免文案顺序变化（如 'up from 500, now 1,234
    stars today'）时误取别的数字；找不到锚定再退化为取首个数字兜底。
    """
    m = re.search(r'([\d,]+)\s*stars?\s*today', text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    nums = re.findall(r'[\d,]+', text)
    if nums:
        return int(nums[0].replace(",", ""))
    return 0


def _fetch_html_with_retry(url, headers, retries=_PAGE_RETRIES):
    """抓取 trending 页面 HTML，失败自动重试。

    GitHub 对 Trending 页的响应偶发 IncompleteRead（连接被服务端/中间层提前掐断），
    单次抓取在 CI 网络下不可靠，必须重试。全部失败返回 None。
    HTTPError 404/410 是永久性错误（页面下线/被删），重试无意义，立即放弃。
    """
    for i in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=_TIMEOUT_HTML) as resp:
                return resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                log.warning("GitHub Trending 页面不存在(%d): %s", e.code, url)
                return None
            log.warning("GitHub Trending 抓取失败(第 %d/%d 次): HTTP %d: %s",
                        i + 1, retries, e.code, str(e)[:100])
        except Exception as e:
            log.warning("GitHub Trending 抓取失败(第 %d/%d 次): %s: %s",
                        i + 1, retries, type(e).__name__, str(e)[:100])
    return None


def _parse_trending_html(html):
    """从 trending 页面 HTML 提取项目候选（不含分类，调用方负责）。"""
    soup = BeautifulSoup(html, "html.parser")
    repo_articles = soup.find_all("article", class_=lambda c: c and "Box-row" in c)
    out = []
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
        out.append({
            "name": full_name,
            "desc": desc[:100],
            "stars_n": stars_n,
            "stars": f"star+{stars_n} today" if stars_n else "star N/A",
            "link": f"https://github.com/{full_name}",
        })

    # 健康检查：HTML 正常返回但 0 条 -> 大概率 GitHub 改版导致类名失效，尽早告警
    if not out and html and len(html) > _HTML_STRUCTURE_WARN_BYTES:
        log.warning("Trending 页面结构可能已变更：HTML %d bytes 但解析出 0 个项目，"
                    "请核对 article.Box-row / p.col-9 类名", len(html))
    return out


def _search_fallback(api_headers):
    """Search API 兜底：近 N 天创建的 AI 爆款仓库（Trending HTML 全失败时启用）。

    历史教训（2026-09-02 实证）：
    - 原查询 `topic:llm+topic:agent+created:>7天` 是双 topic 精确 AND，
      8/13 开源的 deepseek-harness（topics=ai-agents/cordis/dsh/dsh-plugin，
      无精确 llm/agent）被永久排除；且 7 天窗口内双 topic 同时命中的仓库
      全为 <50 星的噪声项目（total 87、最高 35 星）。
    - 改为：近 30 天窗口（覆盖创建数周才爆发的仓库）+ 多组热门 AI topic
      各自查询后合并去重，再按总星数排序。
    """
    log.info("  备用：GitHub Search API（近 %d 天 AI 爆款）...", _FALLBACK_DAYS)
    since = (datetime.now() - timedelta(days=_FALLBACK_DAYS)).strftime("%Y-%m-%d")
    seen = {}
    for topic in _SEARCH_TOPICS:
        url = (f"https://api.github.com/search/repositories"
               f"?q=topic:{topic}+created:>{since}&sort=stars&order=desc&per_page=8")
        try:
            req = Request(url, headers=api_headers)
            with urlopen(req, timeout=_TIMEOUT_SEARCH) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            # 限流（403/429）：继续查询只会叠加配额消耗，显式告警并放弃剩余查询
            if e.code in (403, 429):
                log.warning("Search API 被限流(%d)，放弃剩余 topic 查询", e.code)
                break
            log.warning("  备用查询 topic:%s 失败: HTTP %d", topic, e.code)
            continue
        except Exception as e:
            log.warning("  备用查询 topic:%s 失败: %s: %s",
                        topic, type(e).__name__, str(e)[:100])
            continue
        for repo in (data.get("items") or []):
            fn = repo.get("full_name", "")
            if not fn or fn in seen:
                continue
            seen[fn] = repo
        log.info("  备用 topic:%s → %d 个候选", topic, len(seen))

    # 总星数降序 → 过滤噪声（星数过低 / 非 AI 分类）
    ranked = sorted(seen.values(),
                    key=lambda r: r.get("stargazers_count", 0), reverse=True)
    scored = []
    for repo in ranked:
        sn = repo.get("stargazers_count", 0)
        if sn < _FALLBACK_MIN_STARS:
            continue
        fn = repo.get("full_name", "")
        desc = repo.get("description", "") or ""
        if not fn or len(desc) < 5:
            continue
        # Search API 返回项自带 topics 字段，L1 同样生效
        topics = repo.get("topics") or []
        tag = tt.classify_repo(topics, fn, desc)
        if tag == "其他":
            continue
        scored.append({
            "name": fn,
            "desc": desc[:100],
            "stars": f"star {sn:,}",
            "link": f"https://github.com/{fn}",
            "tag": tag,
            # 领域相关度（用户关注域优先），仅用于排序
            "relevance": tt.relevance_score(topics, fn, desc),
            "_stars_n": sn,
        })
    # 领域相关优先：relevance 降序为主、总星数降序为辅
    scored.sort(key=lambda r: (r.get("relevance", 0), r.get("_stars_n", 0)),
                reverse=True)
    out = []
    for r in scored[:3]:
        r.pop("_stars_n", None)
        r.pop("relevance", None)
        out.append(r)
    log.info("  备用入选 %d 个", len(out))
    return out


def fetch_github_trending():
    """
    主路径：BeautifulSoup 解析 github.com/trending 官方页面（daily 优先，
    该榜无有效项目或全为非 AI 项目时再试 weekly），每榜重试 3 次。
    兜底：全部失败走 GitHub Search API（近 30 天 AI 爆款）。
    返回: [{"name","desc","stars","link","tag"}, ...] 最多 3 个
    """
    api_headers = _api_headers()
    html_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        # 防 keep-alive 连接被服务端提前断开导致 IncompleteRead
        "Connection": "close",
        # 不请求压缩流，降低传输中途截断概率
        "Accept-Encoding": "identity",
    }
    urls = [
        ("https://github.com/trending?since=daily", "daily"),
        ("https://github.com/trending?since=weekly", "weekly"),
    ]
    candidates = []

    for url, period in urls:
        html = _fetch_html_with_retry(url, html_headers)
        if html is None:
            log.warning("  %s 榜抓取失败（重试 %d 次均未成功）", period, _PAGE_RETRIES)
            continue

        parsed = _parse_trending_html(html)
        if not parsed:
            log.info("  %s 榜解析出 0 个有效项目", period)
            continue

        # 主路径：按日增 star 排序，只给 Top N 拉 topics（控制 API 调用），再四层分类
        parsed.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
        for c in parsed[:TOPICS_FETCH_LIMIT]:
            parts = c["name"].split("/")
            if len(parts) == 2:
                topics = fetch_topics(parts[0], parts[1], api_headers)
            else:
                topics = []
            c["tag"] = tt.classify_repo(topics, c["name"], c["desc"])
            # 领域相关度：先按用户关注域排，热度退居第二（用户 2026-09-02 拍板）
            c["relevance"] = tt.relevance_score(topics, c["name"], c["desc"])

        # 过滤非 AI 项目（卫星模拟器 / 纯 GIS 工具等不该出现在 AI 简报推荐里），
        # 只取已完成分类（Top N 内）的项目——Top N 外未拉 topics 的不参与
        ai_projects = [c for c in parsed
                       if c.get("tag") and c["tag"] != "其他"]
        # 领域相关优先：relevance 降序为主、日增 star 降序为辅
        ai_projects.sort(key=lambda c: (c.get("relevance", 0),
                                        c.get("stars_n", 0)), reverse=True)
        log.info("  %s 榜 %d 个项目，其中 AI 相关 %d 个（强相关 %d 个）",
                 period, len(parsed), len(ai_projects),
                 sum(1 for c in ai_projects if c.get("relevance", 0) >= 2))
        if ai_projects:
            candidates = ai_projects
            break
        # 该榜全是非 AI 项目（全站 trending 偶发），继续试下一榜
        log.info("  %s 榜无 AI 相关项目，改试下一榜", period)

    for p in candidates:
        p.pop("stars_n", None)
        p.pop("relevance", None)
    if candidates:
        return candidates[:3]

    # 备用：Search API
    return _search_fallback(api_headers)[:3]
