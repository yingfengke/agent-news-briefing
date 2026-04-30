#!/usr/bin/env python3
"""
generate_briefing.py — 每日科技早餐简报自动生成脚本
纯 RSS 驱动，零外部依赖（仅用 Python 标准库）。

数据流向：RSS 源 → XML 解析 → 摘要提取 → 写入 HTML
"""

import re
import json
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError
import os

# ============================================================
# 配置
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "tech-briefing.html")

# RSS 源列表 — 聚焦 AI / Agent / 大模型 / 前沿科技
# (名称, RSS_URL, 语言)
RSS_SOURCES = [
    ("ArsTechnica AI",   "https://feeds.arstechnica.com/arstechnica/index",        "en"),
    ("TechCrunch AI",    "https://techcrunch.com/category/artificial-intelligence/feed/", "en"),
    ("VentureBeat AI",   "https://venturebeat.com/category/ai/feed/",              "en"),
    ("HackerNews",       "https://hnrss.org/frontpage?count=10",                   "en"),
    ("Solidot 科技",     "https://www.solidot.org/index.rss",                      "zh"),
]

MAX_ITEMS = 5              # 最终保留条数
MAX_PER_SOURCE = 3         # 每源最多条数
MAX_SUMMARY = 150          # 摘要最大字符数
TIMEOUT = 15               # 请求超时(秒)
USER_AGENT = "Mozilla/5.0 (compatible; BriefingBot/1.0; +https://github.com/songguyingfengke/tech-breakfast)"


# ============================================================
# RSS 抓取与解析
# ============================================================

def fetch(url):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse(xml_data, source_name):
    """解析 RSS 2.0 或 Atom 格式，返回 [{title, summary, link, source}]"""
    root = ET.fromstring(xml_data)
    items = []

    # --- RSS 2.0 ---
    for item in root.iter("item"):
        title = _text(item, "title")
        link  = _text(item, "link")
        desc  = _text(item, "description") or _text(item, "content:encoded") or ""
        if title and link:
            items.append({
                "title": title.strip(),
                "summary": _clean(desc),
                "link": link.strip(),
                "source": source_name,
            })

    # --- Atom ---
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = _text(entry, "title", ns)
            href  = entry.find("a:link", ns)
            link  = href.get("href") if href is not None else ""
            desc  = _text(entry, "summary", ns) or _text(entry, "content", ns) or ""
            if title and link:
                items.append({
                    "title": title.strip(),
                    "summary": _clean(desc),
                    "link": link.strip(),
                    "source": source_name,
                })

    return items


def _text(el, tag, ns=None):
    child = el.find(tag, ns or {})
    return child.text.strip() if child is not None and child.text else ""


def _clean(raw):
    """从 HTML 标签中提取纯文本，过滤 RSS 元信息，截断"""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"(Article|Comments)\s*URL\s*:\s*https?://\S+", "", text, flags=re.I)
    text = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    # 太短说明没有有效摘要，用占位
    if len(text) < 15:
        return ""
    # 截断
    if len(text) > MAX_SUMMARY:
        cut = max(text.rfind("。", 0, MAX_SUMMARY), text.rfind(".", 0, MAX_SUMMARY),
                   text.rfind("！", 0, MAX_SUMMARY), text.rfind("!", 0, MAX_SUMMARY))
        text = text[:cut + 1] if cut > MAX_SUMMARY // 2 else text[:MAX_SUMMARY] + "……"
    return text


# ============================================================
# 写入 HTML
# ============================================================

def write_html(news_items):
    if not os.path.exists(HTML_FILE):
        print(f"[错误] HTML 文件不存在: {HTML_FILE}")
        return False

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 格式化 JSON，缩进与 HTML 对齐（8 空格）
    json_str = json.dumps(news_items, ensure_ascii=False, indent=4)
    lines = json_str.split("\n")
    indented = "\n".join("        " + line if line.strip() else line for line in lines)

    pattern = r'(const __NEWS_DATA__\s*=\s*)\[[^\]]*\](\s*;)'
    repl = r'\1' + indented + r'\2'
    new_content = re.sub(pattern, repl, content, count=1, flags=re.DOTALL)

    if new_content == content:
        print("[警告] 未找到 __NEWS_DATA__ 标记，HTML 格式可能已变")
        return False

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[成功] 已更新 {len(news_items)} 条新闻到 HTML")
    return True


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 55)
    print("  每日科技早餐简报 — RSS 新闻抓取")
    print(f"  来源: {len(RSS_SOURCES)} 个, 目标: {MAX_ITEMS} 条")
    print("=" * 55)

    all_items, errors = [], []

    for name, url, lang in RSS_SOURCES:
        try:
            print(f"\n  → {name} ({lang}) ... ", end="", flush=True)
            items = parse(fetch(url), name)
            items = items[:MAX_PER_SOURCE]
            print(f"✔ {len(items)} 条")
            all_items.extend(items)
        except ET.ParseError:
            print("✘ XML 解析失败")
            errors.append(name)
        except URLError as e:
            print(f"✘ 网络错误: {e.reason}")
            errors.append(name)
        except Exception as e:
            print(f"✘ {e}")
            errors.append(name)

    print(f"\n{'=' * 55}")
    print(f"  共获取 {len(all_items)} 条原始新闻")

    if not all_items:
        print("\n  [结果] 所有 RSS 源均失败，跳过 HTML 更新")
        print("  页面将显示空状态提示")
        return

    # 去重（标题相似度去重）
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"].lower().strip()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    final = unique[:MAX_ITEMS]

    print(f"  去重后: {len(unique)} 条 | 最终选取: {len(final)} 条")
    print()

    for i, it in enumerate(final, 1):
        print(f"  {i:02d}. [{it['source']}] {it['title']}")
        print(f"      摘要: {(it['summary'] or '（无摘要）')[:60]}")
        print(f"      链接: {it['link']}")
        print()

    if write_html(final):
        print("[完成] 简报已更新，下次自动运行: 每天 09:00")
    else:
        print("[失败] HTML 更新失败")


if __name__ == "__main__":
    main()
