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

# RSS 源 — 严格限定 AI / 大模型 / Agent / 开发工具
RSS_SOURCES = [
    ("TechCrunch AI",    "https://techcrunch.com/category/artificial-intelligence/feed/",              "en"),
    ("VentureBeat AI",   "https://venturebeat.com/category/ai/feed/",                                 "en"),
    ("ArsTechnica",      "https://feeds.arstechnica.com/arstechnica/index",                           "en"),
    ("HackerNews",       "https://hnrss.org/frontpage?count=12",                                      "en"),
    ("Solidot 科技",     "https://www.solidot.org/index.rss",                                         "zh"),
]

MAX_PER_SOURCE = 3         # 每源取前 N 条
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/2.0)"

# AI 分析的 system prompt（用户指定）
SYSTEM_PROMPT = """你是一个专为AI开发者服务的资深技术分析师。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻
2. 按对开发者的重要性排序，而不是商业热度
3. 每条新闻的摘要，必须点明：为什么这个更新对开发者重要
4. 最后的"今日深度分析"，要预判这项技术动向未来半年可能带来的影响

请严格按照以下 JSON 格式输出（不要加 markdown 代码块标记）：
{
  "items": [
    {"title": "标题", "summary": "摘要（50-100字）", "link": "原文链接", "source": "来源名称"}
  ],
  "daily_analysis": "今日深度分析（200-300字）"
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
            title = _text(entry, "title", ns)
            href  = entry.find("a:link", ns)
            link  = href.get("href") if href is not None else ""
            desc  = _text(entry, "summary", ns) or _text(entry, "content", ns) or ""
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
# 写入 HTML
# ============================================================

def write_html(news_items, daily_analysis=""):
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

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已更新 {len(news_items)} 条新闻到 HTML")
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
            items = parse(fetch(url), name)[:MAX_PER_SOURCE]
            print(f"✔ {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            print(f"✘ {e}")
            errors.append(name)

    print(f"\n  共获取 {len(all_items)} 条原始新闻")
    if not all_items:
        print("  [终止] 无可用数据，跳过")
        return

    # 传给 AI 的新闻量控制（减少可加速响应）
    items_for_ai = all_items[:10]

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
        print(f"\n  AI 筛选后: {len(final_items)} 条")
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

    # ---- 3. 写入 HTML ----
    print(f"\n  ── 写入 HTML ──")
    write_html(final_items, daily_analysis)

    if daily_analysis:
        print(f"\n  📊 今日深度分析:")
        print(f"     {daily_analysis[:200]}...")

    print(f"\n  ✅ 简报生成完毕 | {len(final_items)} 条新闻")
    print(f"     下次自动运行: 每天 09:00")


if __name__ == "__main__":
    main()
