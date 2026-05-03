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

# RSS 源 — 核心5个 + 补充2个高质量源
RSS_SOURCES = [
    ("TechCrunch AI",    "https://techcrunch.com/category/artificial-intelligence/feed/",              "en"),
    ("VentureBeat AI",   "https://venturebeat.com/category/ai/feed/",                                 "en"),
    ("ArsTechnica",      "https://feeds.arstechnica.com/arstechnica/index",                           "en"),
    ("HackerNews",       "https://hnrss.org/frontpage?count=12",                                      "en"),
    ("Solidot 科技",     "https://www.solidot.org/index.rss",                                         "zh"),
    ("MIT Tech Review",  "https://www.technologyreview.com/topic/artificial-intelligence/feed/",      "en"),
    ("Anthropic Blog",   "https://www.anthropic.com/feed.xml",                                        "en"),
]

MAX_PER_SOURCE = {
    "TechCrunch AI": 4, "VentureBeat AI": 4, "ArsTechnica": 4,
    "HackerNews": 4, "Solidot 科技": 4,
    "MIT Tech Review": 3, "Anthropic Blog": 3,
}
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/2.0)"

# AI 分析的 system prompt
SYSTEM_PROMPT = """你是一个专为中文AI开发者服务的资深技术分析师，请务必使用中文回复。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻
2. 按对开发者的重要性排序，而不是商业热度
3. 每条新闻的摘要（50-100字中文），必须点明：为什么这个更新对开发者重要
4. 输出最后，必须用 '---' 分隔线隔开，生成一个【今日深度分析】模块，用200字以内中文，预判今天最重要的1-2个技术趋势及其未来半年影响

请严格按照以下 JSON 格式输出（不要加 markdown 代码块标记）：
{
  "items": [
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
        print(f"  → 解析到 {len(parsed.get('items', []))} 条筛选结果")
        return parsed
    except Exception as e:
        print(f"✘ 失败: {e}")
        return None


# ============================================================
# GitHub Trending 独立抓取（不依赖 RSS / AI）
# ============================================================

# 用于筛选项目的技术方向关键词
TRENDING_KEYWORDS = [
    "transformer", "attention", "moe", "flashattention", "llm", "large language model",
    "lora", "qlora", "llama-factory", "unsloth", "axolotl", "vllm", "fine-tuning",
    "langchain", "langgraph", "autogpt", "crewai", "autogen", "metagpt", "dify", "agent",
    "llamaindex", "ragflow", "chroma", "milvus", "haystack", "rag", "retrieval",
    "react", "cot", "function calling", "prompt",
    "tgi", "gptq", "awq", "streaming", "inference",
    "vision language", "vlm", "multimodal", "cursor", "copilot", "claude code",
    "mcp", "model context protocol", "openai agent",
]


def fetch_github_trending():
    """
    从 GitHub Trending API 获取今日热门项目，按技术方向筛选。
    返回: [{"name":"","desc":"","stars":"","link":"","tag":""}, ...]
    """
    trending_url = "https://github-trending-api.vercel.app/repositories?since=daily&spoken_language_code=zh"
    fallback_url = "https://github-trending-api.vercel.app/repositories?since=weekly"

    projects = []
    seen_names = set()

    for url in [trending_url, fallback_url]:
        try:
            print(f"\n  → 抓取 GitHub Trending ({url.split('?')[0].rsplit('/',1)[-1]}) ... ", end="", flush=True)
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for repo in data:
                name = repo.get("fullname", "") or repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                lang = repo.get("language", "") or ""
                stars = repo.get("stars", 0) or repo.get("stargazers_count", 0)
                stars_str = f"⭐{stars//1000}万" if stars >= 1000 else f"⭐{stars}"

                # 去重
                if name in seen_names:
                    continue

                # 用名称+描述匹配技术方向
                text = f"{name} {desc}".lower()
                matched_tag = ""
                for kw in TRENDING_KEYWORDS:
                    if kw.lower() in text:
                        # 映射到友好标签名
                        tag_map = {
                            "transformer": "大模型底层", "attention": "大模型底层", "moe": "大模型底层",
                            "lora": "微调与训练", "qlora": "微调与训练", "fine-tuning": "微调与训练", "vllm": "推理与部署",
                            "langchain": "Agent 框架", "langgraph": "Agent 框架", "autogpt": "Agent 框架",
                            "crewai": "Agent 框架", "autogen": "Agent 框架", "metagpt": "Agent 框架", "dify": "Agent 框架",
                            "llamaindex": "RAG", "ragflow": "RAG", "chroma": "RAG", "milvus": "RAG", "haystack": "RAG", "rag": "RAG", "retrieval": "RAG",
                            "react": "提示工程", "cot": "提示工程", "function calling": "提示工程", "prompt": "提示工程",
                            "tgi": "推理与部署", "gptq": "推理与部署", "awq": "推理与部署", "inference": "推理与部署",
                            "vision language": "多模态与前沿", "vlm": "多模态与前沿", "multimodal": "多模态与前沿",
                            "cursor": "多模态与前沿", "copilot": "多模态与前沿", "claude code": "多模态与前沿",
                            "mcp": "Agent 框架", "model context protocol": "Agent 框架", "openai agent": "Agent 框架",
                            "llm": "大模型底层", "agent": "Agent 框架",
                        }
                        matched_tag = tag_map.get(kw, "其他")
                        break

                if matched_tag and len(desc) > 5:
                    seen_names.add(name)
                    projects.append({
                        "name": name,
                        "desc": desc[:80],
                        "stars": stars_str,
                        "link": f"https://github.com/{name}",
                        "tag": matched_tag,
                    })

            print(f"✔ 筛出 {len(projects)} 个相关项目")
            if projects:
                break  # 首次有结果就停

        except Exception as e:
            print(f"✘ {e}")
            continue

    # 按星数排序取前3
    projects.sort(key=lambda x: int(x["stars"].replace("⭐", "").replace("万", "000")), reverse=True)
    return projects[:3]


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

    # 生成新闻卡片 HTML
    cards_html = []
    for i, item in enumerate(news_items, 1):
        source_tag = f'<span style="font-size:10px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;">{item["source"]}</span>' if item.get("source") else ""
        cards_html.append(f"""
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
    html = html.replace("{{news_items}}", "\n".join(cards_html))
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

    print(f"\n  共获取 {len(all_items)} 条原始新闻")
    if not all_items:
        print("  [终止] 无可用数据，跳过")
        return

    # 传给 AI 的新闻量控制（增加捕获量以丰富内容）
    items_for_ai = all_items[:15]

    # ---- 2. AI 分析 ----
    print("\n  ── AI 分析阶段 ──")
    ai_result = call_ai_analysis(items_for_ai)

    final_items = []
    daily_analysis = ""

    if ai_result and "items" in ai_result:
        # 使用 AI 返回的筛选结果
        for it in ai_result["items"]:
            final_items.append({
                "title": it.get("title", ""),
                "summary": it.get("summary", ""),
                "link": it.get("link", ""),
                "source": it.get("source", "AI"),
            })
        daily_analysis = ai_result.get("daily_analysis", "")
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
