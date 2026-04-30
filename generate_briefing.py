#!/usr/bin/env python3
"""
generate_briefing.py — 每日科技早餐简报自动生成脚本

功能：
  1. 从多个 RSS 源抓取最新科技新闻
  2. 智能筛选与排版（标题、摘要、原文链接）
  3. 更新 tech-briefing.html 中的 __NEWS_DATA__ 数组
  4. 若所有 RSS 源均失败，保留现有数据不覆盖

运行方式：python generate_briefing.py
依赖：Python 3.7+ 标准库（无需 pip install）
"""

import re
import json
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError
import textwrap
import os

# ============================================================
# 配置区域
# ============================================================

# HTML 文件路径 (相对于脚本所在目录)
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tech-briefing.html")

# RSS 新闻源列表 (按优先级排列)
# 格式: (名称, RSS_URL, 语言)
RSS_SOURCES = [
    ("ArsTechnica","https://feeds.arstechnica.com/arstechnica/index", "en"),
    ("Solidot",    "https://www.solidot.org/index.rss", "zh"),
    ("HackerNews", "https://hnrss.org/frontpage?count=8", "en"),
    ("TheVerge",   "https://www.theverge.com/rss/index.xml", "en"),
]

# 每条新闻的最大摘要长度（字符数）
MAX_SUMMARY_LENGTH = 120

# 最终保留的新闻条数
MAX_NEWS_ITEMS = 5

# 每个 RSS 源最多取几条（保证多源混合）
MAX_PER_SOURCE = 3

# User-Agent 防止被拒
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


# ============================================================
# RSS 抓取与解析
# ============================================================

def fetch_rss(url, timeout=10):
    """从指定 URL 获取 RSS XML 内容"""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_rss_items(xml_data):
    """
    解析 RSS/Atom XML，返回 [{title, summary, link}] 列表
    同时支持 RSS 2.0 (<item>) 和 Atom (<entry>) 格式
    """
    root = ET.fromstring(xml_data)
    items = []

    # 尝试 RSS 2.0 格式
    for item in root.iter("item"):
        title = _get_text(item, "title")
        link  = _get_text(item, "link")
        # 摘要可能放在 description 或 content:encoded
        summary = _get_text(item, "description") or _get_text(item, "content:encoded") or ""
        summary = _clean_summary(summary)
        if title and link:
            items.append({"title": title.strip(), "summary": summary.strip(), "link": link.strip()})

    # 如果没找到 RSS 2.0 的 item，尝试 Atom 格式
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = _get_text(entry, "title", ns)
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            summary = _get_text(entry, "summary", ns) or _get_text(entry, "content", ns) or ""
            summary = _clean_summary(summary)
            if title and link:
                items.append({"title": title.strip(), "summary": summary.strip(), "link": link.strip()})

    return items


def _get_text(element, tag, ns=None):
    """安全地获取子元素的文本内容"""
    ns_map = ns or {}
    child = element.find(tag, ns_map)
    return child.text.strip() if child is not None and child.text else ""


def _clean_html(html_text):
    """去除 HTML 标签，保留纯文本"""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_summary(raw_text):
    """
    进一步清理摘要：
    - 去除 "Article URL: ..." / "Comments URL: ..." 等自动追加的元信息
    - 去除 HackerNews 特有的 "Points: ... Comments: ..." 评分行
    - 如果清理后为空，回退为标题
    """
    text = _clean_html(raw_text)
    # 去除 Article URL / Comments URL 行
    text = re.sub(r"(Article|Comments)\s*URL\s*:\s*https?://\S+", "", text)
    # 去除 HackerNews 的 Points / Comments 评分信息
    text = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 如果只剩下标点或太短，用标题代替
    if len(text) < 10:
        return ""
    return text


# ============================================================
# 摘要截断与质量优化
# ============================================================

def truncate_summary(text, max_len=MAX_SUMMARY_LENGTH):
    """截断摘要到指定字符数，尽量在句号处断开"""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    # 尝试在最后一个句号处断开
    last_period = max(truncated.rfind("。"), truncated.rfind("."), truncated.rfind("!"), truncated.rfind("！"))
    if last_period > max_len // 2:
        return truncated[:last_period + 1]
    return truncated + "……"


def deduplicate(items):
    """简单的去重：相同标题只保留第一条"""
    seen = set()
    unique = []
    for item in items:
        key = item["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ============================================================
# 更新 HTML 中的新闻数据
# ============================================================

def update_html(news_items):
    """
    读取 HTML 文件，定位 __NEWS_DATA__ = [...] 行，
    用新的 JSON 数组替换方括号内的内容。
    """
    if not os.path.exists(HTML_FILE):
        print(f"[错误] HTML 文件不存在: {HTML_FILE}")
        return False

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 生成格式化的 JSON 数组字符串
    json_str = json.dumps(news_items, ensure_ascii=False, indent=4)
    # 缩进调整为与 HTML 一致：8 空格
    lines = json_str.split("\n")
    indented_lines = ["        " + line if line.strip() else line for line in lines]
    indented_json = "\n".join(indented_lines).rstrip()

    # 替换 __NEWS_DATA__ 的方括号内容
    # 匹配模式: const __NEWS_DATA__ = [ ... ];
    pattern = r'(const __NEWS_DATA__\s*=\s*)\[[^\]]*\](\s*;)'
    replacement = r'\1' + indented_json + r'\2'

    new_content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)

    if new_content == content:
        print("[警告] 未找到 __NEWS_DATA__ 标记，HTML 可能已损坏或格式有变")
        return False

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[成功] 已更新 {len(news_items)} 条新闻到 HTML 文件")
    return True


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 50)
    print("  每日科技早餐简报 — 新闻抓取脚本")
    print("=" * 50)

    all_items = []
    errors = []

    for name, url, lang in RSS_SOURCES:
        try:
            print(f"\n[抓取] {name} ({lang}) ... ", end="", flush=True)
            xml_data = fetch_rss(url)
            items = parse_rss_items(xml_data)
            # 每源最多取 MAX_PER_SOURCE 条，保证多源混合
            items = items[:MAX_PER_SOURCE]
            print(f"成功，获取 {len(items)} 条")
            all_items.extend(items)
        except URLError as e:
            msg = f"网络错误: {e.reason}"
            print(f"失败 - {msg}")
            errors.append(f"{name}: {msg}")
        except ET.ParseError as e:
            msg = f"XML 解析错误: {e}"
            print(f"失败 - {msg}")
            errors.append(f"{name}: {msg}")
        except Exception as e:
            msg = f"未知错误: {e}"
            print(f"失败 - {msg}")
            errors.append(f"{name}: {msg}")

    # 汇总结果
    print("\n" + "=" * 50)
    print(f"  共获取 {len(all_items)} 条原始新闻")

    if not all_items:
        print("\n[结果] 所有 RSS 源均失败，跳过 HTML 更新")
        print("  保留页面上次生成的数据不变")
        if errors:
            print("\n  错误详情:")
            for e in errors:
                print(f"    - {e}")
        return

    # 去重 + 截断摘要 + 限制数量
    unique_items = deduplicate(all_items)
    for item in unique_items:
        summary = truncate_summary(item["summary"])
        # 如果摘要为空（如 HackerNews 无描述），使用替代文本
        if not summary:
            summary = "点击「阅读原文」查看完整报道"
        item["summary"] = summary

    final_items = unique_items[:MAX_NEWS_ITEMS]

    print(f"  去重后: {len(unique_items)} 条")
    print(f"  最终选取: {len(final_items)} 条")
    print()

    # 预览
    for i, item in enumerate(final_items, 1):
        print(f"  {i:02d}. {item['title']}")
        print(f"      摘要: {item['summary'][:50]}...")
        print(f"      链接: {item['link']}")
        print()

    # 更新 HTML
    if update_html(final_items):
        print("[成功] 简报已更新完毕")
    else:
        print("[失败] HTML 更新失败，请检查文件")
        if errors:
            print("\n  RSS 错误详情:")
            for e in errors:
                print(f"    - {e}")


if __name__ == "__main__":
    main()
