#!/usr/bin/env python3
"""
generate_briefing.py — AI & Agent 开发者晨报 自动生成脚本

流程:
  RSS 抓取 → AI 筛选/排序/摘要 → 写入 HTML → 发送邮件
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

from dotenv import load_dotenv

# ============================================================
# 加载 .env 配置
# ============================================================
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "https://api.siliconflow.cn")
API_KEY      = os.getenv("API_KEY", "")
MODEL_NAME   = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "tech-briefing.html")
EMAIL_TEMPLATE = os.path.join(BASE_DIR, "email_template.html")
EMAIL_OUTPUT = os.path.join(BASE_DIR, "email_content.html")

# RSS 源 — 中文源在前（均衡国内外新闻），全部经过实测可用或GitHub Actions可访问
RSS_SOURCES = [
    # ---- 中文源（全部实测可用） ----
    ("36氪",           "https://www.36kr.com/feed",                                                    "zh"),
    ("少数派",         "https://sspai.com/feed",                                                       "zh"),
    ("爱范儿",         "https://www.ifanr.com/feed",                                                   "zh"),
    ("极客公园",       "https://www.geekpark.net/rss",                                                 "zh"),
    ("Solidot 科技",   "https://www.solidot.org/index.rss",                                           "zh"),
    # ---- 英文源 ----
    ("TechCrunch AI",  "https://techcrunch.com/category/artificial-intelligence/feed/",              "en"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/",                                 "en"),
    ("Wired AI",       "https://www.wired.com/feed/tag/ai/latest/rss",                             "en"),
    ("HackerNews",     "https://hnrss.org/frontpage?count=12",                                      "en"),
    ("MIT Tech Review","https://www.technologyreview.com/topic/artificial-intelligence/feed/",      "en"),
    ("GitHub Blog",    "https://github.blog/feed/",                                                 "en"),
    ("PyTorch Blog",   "https://pytorch.org/blog/feed.xml",                                         "en"),
]

MAX_PER_SOURCE = {
    # 中文源
    "36氪": 4, "少数派": 3, "爱范儿": 3, "极客公园": 3, "Solidot 科技": 3,
    # 英文源
    "TechCrunch AI": 4, "VentureBeat AI": 4, "Wired AI": 3,
    "HackerNews": 4,
    "MIT Tech Review": 3, "GitHub Blog": 3, "PyTorch Blog": 3,
}
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/2.0)"

# AI 分析的 system prompt
SYSTEM_PROMPT = """你是一个专为中文AI开发者服务的资深技术分析师，请务必使用中文回复。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻
2. 按对开发者的重要性排序，而不是商业热度
3. 每条新闻的摘要（50-100字中文），必须点明：为什么这个更新对开发者重要
4. 输出最后生成"daily_analysis"字段，200字以内中文，预判今天最重要的1-2个技术趋势及其未来半年影响

5. 【去重规则 — 严格遵守】：
   a) 如果多条新闻讲的是同一件事（例如多家媒体报道同一次发布会），只保留信息最完整的那条，并在摘要末尾注明"（多家来源报道）"。
   b) 优先分析发布时间更近的新闻。
   c) 【历史排重】我会在用户消息末尾附上"【已报道历史】"列表，列出了过去几天已推送过的新闻标题。遇到核心主题高度相似的，自动跳过，确保每天都有新信息。

6. 【强制中文 — 非常重要】即使原文是英文，**所有 title 和 summary 字段必须输出中文**。论文名称、专有名词（如模型名/框架名）第一次出现时可以括号注明英文原名。

7. 【来源分组规则 — 严格遵守，这是最重要的规则】：
   - international（国外科技）：**只能**包含来源为 TechCrunch AI、VentureBeat AI、Wired AI、HackerNews、MIT Tech Review、GitHub Blog、PyTorch Blog 的新闻。
   - china（国内科技）：**只能**包含来源为 36氪、少数派、爱范儿、极客公园、Solidot 科技、量子位、IT之家AI 的新闻。
   - **绝对禁止**把中国来源的新闻放进 international，也禁止把国外来源的新闻放进 china。
   - 如果某个分组的新闻不够3条，就保留能找到的，宁缺毋滥。

请严格按照以下 JSON 格式输出（不要加 markdown 代码块标记，不要有任何多余的文字）：
{
  "international": [
    {"title": "标题（中文）", "summary": "摘要（50-100字中文）", "link": "原文链接", "source": "来源名称"}
  ],
  "china": [
    {"title": "标题（中文）", "summary": "摘要（50-100字中文）", "link": "原文链接", "source": "来源名称"}
  ],
  "daily_analysis": "今日深度分析（200字以内中文，预判1-2个趋势）"
}"""


# ============================================================
# RSS 抓取与解析
# ============================================================

def fetch(url):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def load_history_titles():
    """
    从 tech-briefing.html 中读取 __NEWS_DATA__ 数组并提取标题，
    用于 AI 排重（避免每日重复报道相似内容）。
    """
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # 匹配 const __NEWS_DATA__ = [ ... ];
        m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
        if not m:
            return []
        data = json.loads(m.group(1))
        titles = [item.get("title", "") for item in data if item.get("title")]
        return titles
    except Exception as e:
        print(f"  [警告] 读取历史简报用于排重时出错: {e}")
        return []


def parse(xml_data, source_name):
    root = ET.fromstring(xml_data)
    items = []
    for item in root.iter("item"):
        title = _text(item, "title")
        link  = _text(item, "link")
        desc  = _text(item, "description") or _text(item, "content:encoded") or ""
        if title and link:
            items.append({"title": title.strip(), "desc": _clean(desc), "link": link.strip(), "source": source_name})
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            # 注意：Atom 命名空间下必须用 "a:tag" 前缀，否则 find 找不到
            title = _text(entry, "a:title", ns)
            href  = entry.find("a:link", ns)
            link  = href.get("href") if href is not None else ""
            desc  = _text(entry, "a:summary", ns) or _text(entry, "a:content", ns) or ""
            if title and link:
                items.append({"title": title.strip(), "desc": _clean(desc), "link": link.strip(), "source": source_name})
    return items


def _text(el, tag, ns=None):
    child = el.find(tag, ns or {})
    return child.text.strip() if child is not None and child.text else ""


def _clean(raw):
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"(Article|Comments)\s*URL\s*:\s*https?://\S+", "", text, flags=re.I)
    text = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200] if len(text) > 200 else text


# ============================================================
# AI 分析（调用第三方 API，不消耗 WorkBuddy 积分）
# ============================================================

def call_ai_analysis(raw_items):
    """
    将所有原始新闻发给大模型，让 AI 筛选、排序、生成摘要和深度分析。
    此操作调用第三方API（硅基流动），不消耗WorkBuddy积分。
    """
    if not API_KEY:
        print("[警告] 未配置 API_KEY，跳过 AI 分析，使用原始数据")
        return None

    # 构建用户消息（精简每条描述节省 token，加速响应）
    lines = ["以下是今日抓取的科技新闻，请按你的系统指令处理：\n"]
    for i, item in enumerate(raw_items, 1):
        desc_short = (item.get("desc") or "无描述")[:80]
        lines.append(f"{i}. [{item['source']}] {item['title']}")
        lines.append(f"   简介: {desc_short}")
        lines.append(f"   链接: {item['link']}\n")

    # 读取历史简报标题，用于 AI 排重
    history_titles = load_history_titles()
    if history_titles:
        lines.append("\n---\n【已报道历史】过去几天已推送过的新闻标题（遇到核心主题相似的请跳过）：\n")
        for t in history_titles:
            lines.append(f"- {t}")

    user_content = "\n".join(lines)

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode("utf-8")

    url = f"{API_BASE_URL.rstrip('/')}/v1/chat/completions"
    print(f"\n  → 调用 AI 分析 ({MODEL_NAME}) ... ", end="", flush=True)

    req = Request(url, data=payload, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })

    try:
        with urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
        if "choices" not in result or len(result["choices"]) == 0:
            print(f"✘ API 返回异常: {json.dumps(result, ensure_ascii=False)[:300]}")
            return None
        content = result["choices"][0]["message"]["content"]
        print(f"✔ 成功 (返回 {len(content)} 字符)")
        # 尝试解析 JSON，如果失败则尝试提取其中的 JSON 块
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取 JSON
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if m:
                parsed = json.loads(m.group(1).strip())
            else:
                # 尝试找第一个 { 到最后一个 }
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end > start:
                    parsed = json.loads(content[start:end+1])
                else:
                    raise
        print(f"  → 解析到: 国外 {len(parsed.get('international', []))} 条 + 国内 {len(parsed.get('china', []))} 条")
        return parsed
    except Exception as e:
        print(f"✘ 失败: {e}")
        return None


# ============================================================
# GitHub Trending 独立抓取（直接爬官方页面，不依赖第三方 API）
# ============================================================


# GitHub Trending 关键词 → 标签映射（模块级别，备用方案也能用）
TRENDING_TAG_MAP = {
    "transformer": "大模型底层", "attention": "大模型底层", "moe": "大模型底层",
    "flashattention": "大模型底层", "llm": "大模型底层", "large language model": "大模型底层",
    "deepseek": "大模型底层", "qwen": "大模型底层", "llama": "大模型底层",
    "foundation model": "大模型底层", "tabpfn": "大模型底层",
    "lora": "微调与训练", "qlora": "微调与训练", "llama-factory": "微调与训练",
    "unsloth": "微调与训练", "axolotl": "微调与训练", "fine-tuning": "微调与训练",
    "vllm": "推理与部署", "tgi": "推理与部署", "gptq": "推理与部署",
    "awq": "推理与部署", "inference": "推理与部署", "streaming": "推理与部署",
    "langchain": "Agent 框架", "langgraph": "Agent 框架", "autogpt": "Agent 框架",
    "crewai": "Agent 框架", "autogen": "Agent 框架", "metagpt": "Agent 框架",
    "dify": "Agent 框架", "agent": "Agent 框架", "swarm": "Agent 框架",
    "autonomous": "Agent 框架", "multi-agent": "Agent 框架",
    "mcp": "Agent 框架", "model context protocol": "Agent 框架", "openai agent": "Agent 框架",
    "llamaindex": "RAG", "ragflow": "RAG", "chroma": "RAG", "milvus": "RAG",
    "haystack": "RAG", "rag": "RAG", "retrieval": "RAG",
    "react": "提示工程", "cot": "提示工程", "function calling": "提示工程", "prompt": "提示工程",
    "vision language": "多模态与前沿", "vlm": "多模态与前沿", "multimodal": "多模态与前沿",
    "cursor": "多模态与前沿", "copilot": "多模态与前沿", "claude code": "多模态与前沿",
    "coding": "开发工具", "code generation": "开发工具",
}


def fetch_github_trending():
    """
    直接爬取 github.com/trending 官方页面，解析热门项目。
    不依赖任何第三方 API，稳定可靠。
    返回: [{"name":"","desc":"","stars":"","link":"","tag":""}, ...]
    """
    TAG_MAP = TRENDING_TAG_MAP

    # 尝试多个 URL：日榜 → 周榜
    urls = [
        "https://github.com/trending?since=daily",
        "https://github.com/trending?since=weekly",
    ]

    projects = []

    for url in urls:
        try:
            print(f"\n  → 抓取 GitHub Trending 官方页面 ({url.split('=')[-1]}) ... ", end="", flush=True)
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")

            # 用正则从 HTML 中提取项目信息
            # GitHub Trending 页面每个项目是一个 <article class="Box-row"> 块
            repo_blocks = re.findall(
                r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>([\s\S]*?)</article>',
                html, re.I
            )
            print(f"找到 {len(repo_blocks)} 个项目块 ... ", end="", flush=True)

            for block in repo_blocks:
                # 提取仓库名（user/repo 格式）
                name_m = re.search(
                    r'href="/([^/]+/[^/"]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<\s][^<]*)',
                    block
                )
                # 用更简单的方式：直接找 href="/user/repo"
                href_m = re.search(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', block)
                if not href_m:
                    continue
                full_name = href_m.group(1).strip()

                # 过滤掉非项目链接（带子路径的）
                if "/" in full_name.replace("/", "", 1):
                    continue

                # 提取描述
                desc_m = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>\s*([\s\S]*?)\s*</p>', block)
                if not desc_m:
                    # 备用：找任意 <p> 内容
                    desc_m = re.search(r'<p[^>]*>\s*([^<]{10,200})\s*</p>', block)
                desc = re.sub(r'\s+', ' ', desc_m.group(1).strip()) if desc_m else ""
                desc = re.sub(r'<[^>]+>', '', desc).strip()  # 去掉残留 HTML 标签

                # 提取今日新增 stars
                stars_today_m = re.search(r'([\d,]+)\s*stars?\s*today', block, re.I)
                # 提取总 stars
                stars_total_m = re.search(r'aria-label="([\d,]+)\s*users?\s*starred', block, re.I)
                if not stars_total_m:
                    stars_total_m = re.search(r'/(stargazers)[^>]*>\s*([\d,]+)', block)

                if stars_today_m:
                    stars_n = int(stars_today_m.group(1).replace(",", ""))
                    stars_str = f"⭐+{stars_n} today"
                else:
                    stars_str = "⭐N/A"
                    stars_n = 0

                # 关键词匹配
                text = f"{full_name} {desc}".lower()
                matched_tag = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        matched_tag = tag
                        break

                if matched_tag and len(desc) > 5 and full_name not in [p["name"] for p in projects]:
                    projects.append({
                        "name": full_name,
                        "desc": desc[:100],
                        "stars": stars_str,
                        "stars_n": stars_n,  # 用于排序
                        "link": f"https://github.com/{full_name}",
                        "tag": matched_tag,
                    })

            print(f"✔ 筛出 {len(projects)} 个相关项目")
            if projects:
                break  # 有结果就停，不需要周榜

        except Exception as e:
            print(f"✘ {e}")
            continue

    # 按今日新增 stars 排序，取前3
    projects.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    # 去掉内部排序字段
    for p in projects:
        p.pop("stars_n", None)

    # ---- 备用方案：GitHub Search API（不需要 token，匿名可用） ----
    if not projects:
        print(f"\n  → 备用：GitHub Search API ... ", end="", flush=True)
        try:
            # 搜索最近7天 stars 增长快的 AI/Agent 相关仓库
            from datetime import timedelta
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            search_url = (
                f"https://api.github.com/search/repositories"
                f"?q=topic:llm+topic:agent+created:>{week_ago}"
                f"&sort=stars&order=desc&per_page=10"
            )
            req2 = Request(search_url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            })
            with urlopen(req2, timeout=15) as r2:
                sdata = json.loads(r2.read().decode("utf-8"))

            for repo in (sdata.get("items") or []):
                full_name = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                stars_n = repo.get("stargazers_count", 0)
                stars_str = f"⭐{stars_n:,}"
                text = f"{full_name} {desc}".lower()
                matched_tag = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        matched_tag = tag
                        break
                if not matched_tag:
                    matched_tag = "Agent 框架"  # 通过 topic:agent 查到的默认标签
                if full_name and len(desc) > 5:
                    projects.append({
                        "name": full_name,
                        "desc": desc[:100],
                        "stars": stars_str,
                        "link": f"https://github.com/{full_name}",
                        "tag": matched_tag,
                    })
                if len(projects) >= 3:
                    break
            print(f"✔ 备用找到 {len(projects)} 个")
        except Exception as e2:
            print(f"✘ {e2}")

    return projects[:3]


# ============================================================
# 中文网站直接抓取（不依赖 RSS，直接爬取首页）
# ============================================================

CHINESE_SITES = [
    ("量子位", "https://www.qbitai.com/"),
    ("IT之家AI", "https://www.ithome.com/tag/AI"),
]


def scrape_chinese_news():
    """
    直接从中文科技网站首页抓取新闻标题和链接（不依赖 RSS）。
    用正则提取 HTML 中的文章链接。
    """
    all_items = []
    for name, url in CHINESE_SITES:
        try:
            print(f"\n  → 抓取 {name} ({url}) ... ", end="", flush=True)
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            with urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8", "ignore")

            # 提取文章标题和链接
            found = re.findall(
                r'<a[^>]*href="([^"]*)"[^>]*>([^<]{10,80})</a>',
                data, re.I
            )
            seen = set()
            count = 0
            for href, title in found:
                title = title.strip()
                # 过滤无意义链接
                if (len(title) < 10
                    or title in seen
                    or href.startswith("#")
                    or "javascript" in href
                    or "login" in href
                    or "wp-content" in href
                    or ".css" in href
                    or ".js" in href
                    or "page" in href.lower() and len(href) < 15
                ):
                    continue
                # 补全相对链接
                if href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                seen.add(title)
                all_items.append({
                    "title": title.strip(),
                    "desc": title.strip(),
                    "link": href,
                    "source": name,
                })
                count += 1
                if count >= 5:
                    break
            print(f"✔ {count} 条")
        except Exception as e:
            print(f"✘ {e}")

    print(f"\n  中文网站共抓取 {len(all_items)} 条")
    return all_items


# ============================================================
# 写入 HTML
# ============================================================

def write_html(news_items, daily_analysis="", projects=[]):
    if not os.path.exists(HTML_FILE):
        print(f"[错误] HTML 文件不存在: {HTML_FILE}")
        return False

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 替换新闻数据
    json_str = json.dumps(news_items, ensure_ascii=False, indent=4)
    lines = json_str.split("\n")
    indented = "\n".join("        " + line if line.strip() else line for line in lines)
    pattern = r'(const __NEWS_DATA__\s*=\s*)\[[^\]]*\](\s*;)'
    content = re.sub(pattern, r'\1' + indented + r'\2', content, count=1, flags=re.DOTALL)

    # 替换深度分析
    if daily_analysis:
        escaped = json.dumps(daily_analysis, ensure_ascii=False)
        content = re.sub(
            r'(const __DAILY_ANALYSIS__\s*=\s*)"[^"]*"(\s*;)',
            r'\1' + escaped + r'\2',
            content, count=1,
        )

    # 替换项目推荐
    projects_json = json.dumps(projects, ensure_ascii=False, indent=4)
    plines = projects_json.split("\n")
    pindented = "\n".join("        " + line if line.strip() else line for line in plines)
    content = re.sub(
        r'(const __PROJECTS__\s*=\s*)\[[^\]]*\](\s*;)',
        r'\1' + pindented + r'\2',
        content, count=1, flags=re.DOTALL,
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已更新 {len(news_items)} 条新闻 + {len(projects)} 个项目到 HTML")
    return True


# ============================================================
# 邮件 HTML 生成（纯静态，不含 JS，兼容邮箱客户端）
# ============================================================

def generate_email_html(news_items, daily_analysis="", projects=[]):
    """
    读取 email_template.html，填充占位符，生成 email_content.html。
    此操作调用第三方API（硅基流动），不消耗WorkBuddy积分。
    """
    if not os.path.exists(EMAIL_TEMPLATE):
        print(f"[警告] 邮件模板不存在: {EMAIL_TEMPLATE}")
        return False

    with open(EMAIL_TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()

    # 生成新闻卡片 HTML（按国内外分组）
    def make_card_html(items, start_no=1):
        html = []
        for i, item in enumerate(items, start_no):
            source_tag = f'<span style="font-size:10px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;">{item["source"]}</span>' if item.get("source") else ""
            html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:16px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {' ' + source_tag if source_tag else ''}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 10px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 14px 0;line-height:1.7;">{item["summary"]}</p>
              <a href="{item["link"]}" style="font-size:12px;font-weight:600;color:#1a1a1a;text-decoration:none;border-bottom:1.5px solid #1a1a1a;">阅读原文 →</a>
            </td>
          </tr>
        </table>""")
        return "\n".join(html)

    # 按 region 分组
    intl_items = [it for it in news_items if it.get("region") == "international"]
    cn_items = [it for it in news_items if it.get("region") == "china"]
    # 如果没有 region 字段（旧格式兼容），全部放国外
    if not intl_items and not cn_items:
        intl_items = news_items

    intl_section = ""
    if intl_items:
        intl_cards = make_card_html(intl_items, 1)
        intl_section = f"""
        <tr>
          <td style="padding-bottom:20px;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">🌐 国外科技</div>
            {intl_cards}
          </td>
        </tr>"""

    cn_section = ""
    if cn_items:
        cn_cards = make_card_html(cn_items, 1)
        cn_section = f"""
        <tr>
          <td style="padding-bottom:20px;border-top:1px dashed #ddd;padding-top:20px;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">🇨🇳 国内科技</div>
            {cn_cards}
          </td>
        </tr>"""

    # 生成深度分析 HTML
    if daily_analysis:
        analysis_section = f"""
        <tr>
          <td style="padding:24px 24px;background:#1a1a1a;border-radius:12px;">
            <div style="font-size:11px;color:#888;letter-spacing:1.2px;margin-bottom:12px;">📊 今日深度分析</div>
            <p style="font-size:13px;color:#ccc;line-height:1.8;margin:0;">{daily_analysis}</p>
          </td>
        </tr>"""
    else:
        analysis_section = ""

    # 生成项目推荐 HTML
    projects_section = ""
    if projects:
        proj_cards = []
        for p in projects:
            proj_cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;margin-bottom:14px;">
          <tr>
            <td style="padding:16px 20px;">
              <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:4px;">
                📌 <a href="{p.get("link","#")}" style="color:#1a1a1a;text-decoration:none;">{p.get("name","")}</a>
                <span style="font-size:12px;color:#888;margin-left:8px;">{p.get("stars","")}</span>
              </div>
              <p style="font-size:13px;color:#555;margin:4px 0 0 0;line-height:1.6;">{p.get("desc","")}</p>
              <span style="font-size:11px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;display:inline-block;margin-top:8px;">🏷️ {p.get("tag","")}</span>
            </td>
          </tr>
        </table>""")
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">📚 本周热门学习项目</div>
            {''.join(proj_cards)}
          </td>
        </tr>"""
    else:
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;color:#888;text-align:center;padding:20px 0;">📚 今日暂无推荐学习项目</div>
          </td>
        </tr>"""

    # 填充模板
    today = datetime.now()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"

    html = template.replace("{{date}}", date_str)
    html = html.replace("{{international_section}}", intl_section)
    html = html.replace("{{china_section}}", cn_section)
    html = html.replace("{{news_items}}", intl_section + cn_section)  # 向后兼容
    html = html.replace("{{daily_analysis_section}}", analysis_section)
    html = html.replace("{{projects_section}}", projects_section)

    with open(EMAIL_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[成功] 已生成邮件 HTML ({len(news_items)} 条)")
    return True


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  AI & Agent 开发者晨报 — 生成器")
    print(f"  RSS 源: {len(RSS_SOURCES)} 个 | 模型: {MODEL_NAME}")
    print("=" * 60)

    # ---- 1. 抓取 RSS ----
    all_items = []
    errors = []
    for name, url, lang in RSS_SOURCES:
        try:
            print(f"\n  → {name} ({lang}) ... ", end="", flush=True)
            limit = MAX_PER_SOURCE.get(name, 3)
            items = parse(fetch(url), name)[:limit]
            print(f"✔ {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            print(f"✘ {e}")
            errors.append(name)

    print(f"\n  共获取 {len(all_items)} 条原始新闻（RSS）")
    if not all_items:
        print("  [终止] 无可用数据，跳过")
        return

    # ---- 补充：抓取中文网站（不依赖 RSS） ----
    print(f"\n  ── 抓取中文网站 ──")
    chinese_items = scrape_chinese_news()
    all_items.extend(chinese_items)
    print(f"  总计 {len(all_items)} 条（RSS + 中文网站）")

    # ---- 传给 AI 的新闻量控制 ----
    # 按语言分桶，确保中英文均有代表，不被截断
    CHINESE_SOURCES = {"36氪", "少数派", "爱范儿", "极客公园", "Solidot 科技", "量子位", "IT之家AI"}
    zh_items = [it for it in all_items if it.get("source") in CHINESE_SOURCES]
    en_items = [it for it in all_items if it.get("source") not in CHINESE_SOURCES]
    # 中文最多10条，英文最多12条，总量控制在22条以内
    items_for_ai = en_items[:12] + zh_items[:10]
    print(f"\n  → 喂给 AI 的新闻: 英文 {len(en_items[:12])} 条 + 中文 {len(zh_items[:10])} 条 = {len(items_for_ai)} 条")

    # ---- 2. AI 分析 ----
    print("\n  ── AI 分析阶段 ──")
    ai_result = call_ai_analysis(items_for_ai)

    final_items = []
    daily_analysis = ""

    # 兼容新旧格式：新格式 international+china，旧格式 items
    if ai_result:
        daily_analysis = ai_result.get("daily_analysis", "")
        if "international" in ai_result and "china" in ai_result:
            # 新格式：分国内外两组
            for it in ai_result.get("international", []):
                final_items.append({
                    "title": it.get("title", ""),
                    "summary": it.get("summary", ""),
                    "link": it.get("link", ""),
                    "source": it.get("source", "AI"),
                    "region": "international",
                })
            for it in ai_result.get("china", []):
                final_items.append({
                    "title": it.get("title", ""),
                    "summary": it.get("summary", ""),
                    "link": it.get("link", ""),
                    "source": it.get("source", "AI"),
                    "region": "china",
                })
            print(f"\n  AI 筛选后: 国外 {len(ai_result.get('international',[]))} 条 + 国内 {len(ai_result.get('china',[]))} 条")
        elif "items" in ai_result:
            # 旧格式兼容
            for it in ai_result["items"]:
                final_items.append({
                    "title": it.get("title", ""),
                    "summary": it.get("summary", ""),
                    "link": it.get("link", ""),
                    "source": it.get("source", "AI"),
                })
            print(f"\n  AI 筛选后: {len(final_items)} 条新闻")
    else:
        # 降级：使用原始数据
        print("\n  [降级] AI 分析不可用，使用原始 RSS 数据")
        # 简单去重
        seen = set()
        for it in all_items:
            key = it["title"].lower().strip()[:40]
            if key not in seen:
                seen.add(key)
                final_items.append({
                    "title": it["title"],
                    "summary": (it["desc"] or "点击「阅读原文」查看完整报道")[:150],
                    "link": it["link"],
                    "source": it["source"],
                })
        final_items = final_items[:5]

    # ---- 3. 抓取 GitHub Trending 项目（独立数据源，不依赖 AI） ----
    print(f"\n  ── 抓取 GitHub Trending 项目 ──")
    trending_projects = fetch_github_trending()
    if trending_projects:
        print(f"  📚 本周热门学习项目: {len(trending_projects)} 个")
        for p in trending_projects:
            print(f"     📌 {p['name']} ({p['tag']})")
    else:
        print("  [信息] 今日暂无合适的 Trending 项目推荐")

    # ---- 4. 写入网页 HTML ----
    print(f"\n  ── 写入网页 HTML ──")
    write_html(final_items, daily_analysis, trending_projects)

    # ---- 5. 生成邮件 HTML（纯静态，不含 JS） ----
    print(f"\n  ── 生成邮件 HTML ──")
    generate_email_html(final_items, daily_analysis, trending_projects)

    if daily_analysis:
        print(f"\n  📊 今日深度分析:")
        print(f"     {daily_analysis[:200]}...")

    print(f"\n  ✅ 简报生成完毕 | {len(final_items)} 条新闻 | {len(trending_projects)} 个项目")
    print(f"     邮件: {EMAIL_OUTPUT}")
    print(f"     下次自动运行: 每天 09:00 (Cloudflare Workers)")


if __name__ == "__main__":
    main()
