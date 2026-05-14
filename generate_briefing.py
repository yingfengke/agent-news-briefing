#!/usr/bin/env python3
"""
generate_briefing.py — AI & Agent 开发者晨报 主流程编排器

职责：
  1. 调用采集层 → 获取原始新闻数据池
  2. 调用过滤层 → 去重/评分得到干净数据
  3. AI 智能筛选与摘要生成
  4. 写入 HTML + 生成邮件 + 发送

架构：
  collector.py (采集层)
    → deduplicator.py (过滤层)
      → 本文件 (AI分析 + HTML生成 + 邮件发送)

三层架构，每层独立模块，协同工作。
"""

import json
import os
import re
import sys
from datetime import datetime
from urllib.request import Request, urlopen

import config
from config import get_random_style, get_random_trivia
from models import NewsItem, FilterReport
from collector import collect_all
from deduplicator import run_pipeline


# ============================================================
# Markdown 链接清洗（用于邮件安全嵌入）
# ============================================================

def clean_links(text: str) -> str:
    """
    将 Markdown 格式的链接和裸 URL 转换为 HTML <a> 标签。
    包含清洗自检（发现遗留的 Markdown 链接会告警）。

    转换规则：
      - [文字](url) → <a href="url" target="_blank">文字</a>
      - 裸 URL (http/https) → <a href="url" target="_blank">url</a>
    """
    if not text:
        return text

    # 1. 转换 Markdown 内联链接
    cleaned = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        text,
    )

    # 2. 转换裸 URL（排除已包裹在 <a> 标签内的）
    #    用 (?![^<]*</a>) 确保不会重复包装已有 <a> 的 URL
    cleaned = re.sub(
        r'(https?://[^\s<>)\]】、，,]+)(?![^<]*</a>)',
        r'<a href="\1" target="_blank">\1</a>',
        cleaned,
    )

    # 3. 自检：是否还有未转换的 Markdown 链接
    remaining = re.findall(r'\[([^\]]+)\]\(', cleaned)
    if remaining:
        print(f"  [LINK-CHECK] ⚠ 发现 {len(remaining)} 个未转换的 Markdown 链接: {remaining}")

    return cleaned


# ============================================================
# AI 分析
# ============================================================

def load_history_titles():
    """
    从 tech-briefing.html 中读取 __NEWS_DATA__ 数组并提取标题，
    用于 AI 排重（避免每日重复报道相似内容）。
    """
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
        if not m:
            return []
        data = json.loads(m.group(1))
        titles = [item.get("title", "") for item in data if item.get("title")]
        return titles
    except Exception as e:
        print(f"  [警告] 读取历史简报用于排重时出错: {e}")
        return []


def call_ai_analysis(items: list[NewsItem], max_retries: int = 3):
    """
    将过滤后的干净新闻发给大模型。

    特性：
      - 每天随机一种语气（极简/毒舌/深度）
      - 失败自动重试，最多 3 次，间隔 5 秒
      - 解析新 JSON 格式（含 top_news + international + china）

    返回:
      (style_name, parsed_json)  成功
      (style_name, None)          全部失败
    """
    if not config.API_KEY:
        print("[警告] 未配置 API_KEY，跳过 AI 分析")
        return ("", None)

    # 随机选择语气
    style_name, system_prompt = get_random_style()
    print(f"\n  → 今日风格: [{style_name}]")

    # 按语言分桶
    zh_items = [it for it in items if it.lang == "zh"]
    en_items = [it for it in items if it.lang == "en"]
    items_for_ai = en_items[:12] + zh_items[:10]
    print(f"  → 喂给 AI: 英文 {len(en_items[:12])} 条 + 中文 {len(zh_items[:10])} 条 = {len(items_for_ai)} 条")

    # 构建用户消息
    lines = ["以下是今日抓取的科技新闻，请按你的系统指令处理：\n"]
    for i, item in enumerate(items_for_ai, 1):
        content_short = (item.content or "无描述")[:80]
        # 附带发布时间（如有）
        time_info = f" ({item.published_at[:10]})" if item.published_at else ""
        lines.append(f"{i}. [{item.source}]{time_info} {item.title}")
        lines.append(f"   简介: {content_short}")
        lines.append(f"   链接: {item.url}\n")

    # 历史排重
    history_titles = load_history_titles()
    if history_titles:
        lines.append("\n---\n【已报道历史】过去几天已推送过的新闻标题（遇到核心主题相似的请跳过）：\n")
        for t in history_titles:
            lines.append(f"- {t}")

    user_content = "\n".join(lines)

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"

    # 重试循环
    for attempt in range(1, max_retries + 1):
        print(f"\n  → 调用 AI 分析 ({config.MODEL_NAME}) ... ", end="", flush=True)

        payload = json.dumps({
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode("utf-8")

        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        try:
            with urlopen(req, timeout=180) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
            if "choices" not in result or len(result["choices"]) == 0:
                raise ValueError(f"API 返回异常: {str(result)[:200]}")

            content = result["choices"][0]["message"]["content"]
            print(f"✔ 成功 ({len(content)} 字符)")

            # 解析 JSON
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
                if m:
                    parsed = json.loads(m.group(1).strip())
                else:
                    start = content.find("{")
                    end = content.rfind("}")
                    if start != -1 and end > start:
                        parsed = json.loads(content[start:end+1])
                    else:
                        raise

            intl = len(parsed.get("international", []))
            cn = len(parsed.get("china", []))
            print(f"  → AI 筛选: 国外 {intl} 条 + 国内 {cn} 条")
            return (style_name, parsed)

        except Exception as e:
            if attempt < max_retries:
                print(f"✘ 第{attempt}次失败 ({str(e)[:60]})，5秒后重试...")
                import time
                time.sleep(5)
            else:
                print(f"✘ 全部 {max_retries} 次重试均失败: {str(e)[:80]}")
                return (style_name, None)


# ============================================================
# GitHub Trending（独立数据源，不经过过滤层和 AI）
# ============================================================

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
            print(f"\n  → 抓取 GitHub Trending 官方页面 ({url.split('=')[-1]}) ... ", end="", flush=True)
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
                        "name": full_name, "desc": desc[:100],
                        "stars": stars_str, "stars_n": stars_n,
                        "link": f"https://github.com/{full_name}", "tag": matched_tag,
                    })

            print(f"✔ 筛出 {len(projects)} 个")
            if projects:
                break
        except Exception as e:
            print(f"✘ {e}")
            continue

    # 备用：GitHub Search API
    if not projects:
        print(f"\n  → 备用：GitHub Search API ... ", end="", flush=True)
        try:
            from datetime import timedelta
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
                        "stars": f"⭐{sn:,}", "link": f"https://github.com/{fn}", "tag": mt,
                    })
                if len(projects) >= 3:
                    break
            print(f"✔ 备用找到 {len(projects)} 个")
        except Exception as e2:
            print(f"✘ {e2}")

    projects.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    for p in projects:
        p.pop("stars_n", None)
    return projects[:3]


# ============================================================
# 写入 HTML
# ============================================================

def write_html(news_items, daily_analysis="", projects=None):
    if not projects:
        projects = []
    if not os.path.exists(config.HTML_FILE):
        print(f"[错误] HTML 文件不存在: {config.HTML_FILE}")
        return False

    with open(config.HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    json_str = json.dumps(news_items, ensure_ascii=False, indent=4)
    lines = json_str.split("\n")
    indented = "\n".join("        " + line if line.strip() else line for line in lines)
    pattern = r'(const __NEWS_DATA__\s*=\s*)\[[^\]]*\](\s*;)'
    content = re.sub(pattern, r'\1' + indented + r'\2', content, count=1, flags=re.DOTALL)

    if daily_analysis:
        escaped = json.dumps(daily_analysis, ensure_ascii=False)
        content = re.sub(
            r'(const __DAILY_ANALYSIS__\s*=\s*)"[^"]*"(\s*;)',
            r'\1' + escaped + r'\2', content, count=1,
        )

    projects_json = json.dumps(projects, ensure_ascii=False, indent=4)
    plines = projects_json.split("\n")
    pindented = "\n".join("        " + line if line.strip() else line for line in plines)
    content = re.sub(
        r'(const __PROJECTS__\s*=\s*)\[[^\]]*\](\s*;)',
        r'\1' + pindented + r'\2', content, count=1, flags=re.DOTALL,
    )

    with open(config.HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已更新 {len(news_items)} 条新闻 + {len(projects)} 个项目到 HTML")

    # 同步更新 index.html（GitHub Pages 默认入口）
    index_path = os.path.join(config.BASE_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已同步更新 index.html")

    return True


# ============================================================
# 邮件 HTML 生成
# ============================================================

def generate_email_html(news_items, daily_analysis="", projects=None,
                        filter_report=None, style_name="", trivia=""):
    if not projects:
        projects = []
    if not os.path.exists(config.EMAIL_TEMPLATE):
        print(f"[警告] 邮件模板不存在: {config.EMAIL_TEMPLATE}")
        return False

    with open(config.EMAIL_TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()

    # 顶部过滤统计（供模板使用）
    total_input = filter_report.total_input if filter_report else 0
    total_output = filter_report.total_output if filter_report else len(news_items)
    filter_tagline = f"今日从 {total_input} 条新闻中精选 {total_output} 条"

    def make_card_html(items_list, start_no=1):
        html = []
        for i, item in enumerate(items_list, start_no):
            source_tag = (f'<span style="font-size:10px;color:#888;background:#f0f0ee;'
                          f'padding:2px 10px;border-radius:20px;">{item["source"]}</span>'
                          ) if item.get("source") else ""
            html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:16px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {' ' + source_tag if source_tag else ''}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 10px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 14px 0;line-height:1.7;">{clean_links(item["summary"])}</p>
              <a href="{item["link"]}" target="_blank">阅读原文 →</a>
            </td>
          </tr>
        </table>""")
        return "\n".join(html)

    intl_items = [it for it in news_items if it.get("region") == "international"]
    cn_items = [it for it in news_items if it.get("region") == "china"]
    if not intl_items and not cn_items:
        intl_items = news_items

    intl_section = ""
    if intl_items:
        intl_cards = make_card_html(intl_items)
        intl_section = f"""
        <tr>
          <td style="padding-bottom:20px;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">🌐 国外科技</div>
            {intl_cards}
          </td>
        </tr>"""

    cn_section = ""
    if cn_items:
        cn_cards = make_card_html(cn_items)
        cn_section = f"""
        <tr>
          <td style="padding-bottom:20px;border-top:1px dashed #ddd;padding-top:20px;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:12px;">🇨🇳 国内科技</div>
            {cn_cards}
          </td>
        </tr>"""

    analysis_section = ""
    if daily_analysis:
        analysis_section = f"""
        <tr>
          <td style="padding:24px 24px;background:#1a1a1a;border-radius:12px;">
            <div style="font-size:11px;color:#888;letter-spacing:1.2px;margin-bottom:12px;">📊 今日深度分析</div>
            <p style="font-size:13px;color:#ccc;line-height:1.8;margin:0;">{clean_links(daily_analysis)}</p>
          </td>
        </tr>"""

    projects_section = ""
    if projects:
        proj_cards = []
        for p in projects:
            proj_cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;margin-bottom:14px;">
          <tr>
            <td style="padding:16px 20px;">
              <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:4px;">
                📌 <a href="{p.get("link","#")}" target="_blank">{p.get("name","")}</a>
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

    filter_report_section = ""
    if filter_report:
        filter_report_section = filter_report.to_email_html()

    # ---- 今日速览（全量排名，用于邮件顶部） ----
    top_news_section = ""
    if news_items:
        top_cards = []
        for i, item in enumerate(news_items[:8], 1):
            source_tag = (f'<span style="font-size:10px;color:#888;background:#f0f0ee;'
                          f'padding:2px 10px;border-radius:20px;">{item["source"]}</span>'
                          ) if item.get("source") else ""
            region_tag = ""
            if item.get("region") == "international":
                region_tag = '<span style="font-size:10px;color:#534AB7;background:#EEEDFE;padding:2px 10px;border-radius:20px;margin-left:4px;">🌐</span>'
            elif item.get("region") == "china":
                region_tag = '<span style="font-size:10px;color:#c0392b;background:#FAEEDA;padding:2px 10px;border-radius:20px;margin-left:4px;">🇨🇳</span>'
            top_cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:14px;">
          <tr>
            <td style="padding:16px 22px;">
              <div style="margin-bottom:6px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {source_tag}{region_tag}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 6px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 10px 0;line-height:1.6;">{clean_links(item["summary"])}</p>
              <a href="{item["link"]}" target="_blank">阅读原文 →</a>
            </td>
          </tr>
        </table>""")
        top_news_section = f"""
        <tr>
          <td style="padding-bottom:24px;">
            <div style="font-size:14px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">⚡ 今日速览</div>
            {''.join(top_cards)}
          </td>
        </tr>"""

    # ---- 彩蛋角落 ----
    trivia_section = ""
    if trivia:
        trivia_section = f"""
        <tr>
          <td style="padding:16px 20px;background:#f8f8f6;border:1px solid #e5e5e5;border-radius:10px;margin-bottom:0;">
            <div style="font-size:11px;color:#888;letter-spacing:1px;margin-bottom:6px;">🎲 彩蛋角落</div>
            <p style="font-size:12px;color:#666;line-height:1.7;margin:0;font-style:italic;">{clean_links(trivia)}</p>
          </td>
        </tr>"""

    # ---- 原文链接备份（绕过 QQ 邮箱过滤的问题，以纯文本形式列出所有 URL） ----
    link_list_section = ""
    if news_items:
        link_rows = []
        for i, item in enumerate(news_items, 1):
            link_url = item.get("link", "")
            link_title = item.get("title", "")
            if link_url:
                link_rows.append(f"""
        <tr>
          <td style="padding:8px 0;border-bottom:1px solid #eee;">
            <span style="font-size:12px;color:#888;font-weight:500;">No.{i:02d}</span>
            <span style="font-size:12px;color:#333;margin-left:6px;">{link_title}</span>
            <br/><span style="font-size:11px;color:#999;word-break:break-all;">{link_url}</span>
          </td>
        </tr>""")
        if link_rows:
            link_list_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">📎 原文链接备份</div>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              {''.join(link_rows)}
            </table>
          </td>
        </tr>"""

    today = datetime.now()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"

    html = template.replace("{{date}}", date_str)
    html = html.replace("{{filter_tagline}}", filter_tagline)
    html = html.replace("{{top_news_section}}", top_news_section)
    html = html.replace("{{international_section}}", intl_section)
    html = html.replace("{{china_section}}", cn_section)
    html = html.replace("{{news_items}}", intl_section + cn_section)
    html = html.replace("{{daily_analysis_section}}", analysis_section)
    html = html.replace("{{projects_section}}", projects_section)
    html = html.replace("{{filter_report_section}}", filter_report_section)
    html = html.replace("{{trivia_section}}", trivia_section)
    html = html.replace("{{link_list_section}}", link_list_section)
    # 底部免责声明和仓库链接
    html = html.replace("{{repo_url}}", "https://github.com/yingfengke/agent-news-briefing")
    if style_name:
        html = html.replace("{{style_tag}}", f" · 今日风格：{style_name}")
    else:
        html = html.replace("{{style_tag}}", "")

    with open(config.EMAIL_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[成功] 已生成邮件 HTML ({len(news_items)} 条)")

    # ---- 自检：扫描邮件 HTML 中是否还有未包裹的链接 ----
    # 排除 <a> 标签内和 <style> 内的内容
    body_only = re.sub(r'<a\s[^>]*>.*?</a>', '', html, flags=re.DOTALL)
    body_only = re.sub(r'<style[^>]*>.*?</style>', '', body_only, flags=re.DOTALL)
    loose_urls = re.findall(r'https?://[^\s<>"\'\]】、，,]+', body_only)
    if loose_urls:
        for url in loose_urls[:5]:
            print(f"  [LINK-CHECK] ⚠ 发现未包裹的链接: {url[:80]}")
        if len(loose_urls) > 5:
            print(f"  [LINK-CHECK] ⚠ ... 还有 {len(loose_urls)-5} 个")
    else:
        print(f"  [LINK-CHECK] ✅ 邮件中所有链接均已正确包裹")
    return True


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  AI & Agent 开发者晨报 — 三层架构 v2.0")
    print(f"  采集: {len(config.RSS_SOURCES)} 个RSS + {len(config.CRAWLER_TARGETS)} 个爬虫")
    print(f"  模型: {config.MODEL_NAME}")
    print("=" * 60)

    # ---- 1. 采集层 ----
    print(f"\n{'=' * 40}")
    print("  第 1 层：多模态数据采集")
    print(f"{'=' * 40}")
    raw_pool = collect_all()

    # ---- 2. 过滤层 ----
    print(f"\n{'=' * 40}")
    print("  第 2 层：智能过滤与去重")
    print(f"{'=' * 40}")
    if raw_pool:
        report = run_pipeline(raw_pool)
    else:
        report = FilterReport(total_input=0)
    report.print_report()
    clean_items = report.remaining_items

    # ---- 3. AI 分析层 ----
    print(f"\n{'=' * 40}")
    print("  第 3 层：AI 分析与简报生成")
    print(f"{'=' * 40}")

    # 随机彩蛋
    trivia = get_random_trivia()
    print(f"  🎲 今日彩蛋: {trivia}")

    final_items = []
    daily_analysis = ""
    ai_failed = False

    if not clean_items:
        print("  [信息] 过滤后无可用数据，发送空报告邮件")
        ai_failed = True
    else:
        style_name, ai_result = call_ai_analysis(clean_items)
        if ai_result:
            daily_analysis = ai_result.get("daily_analysis", "")

            def _extract_link(it: dict, summary: str = "") -> str:
                """从 AI 返回的条目中提取链接，尝试多个字段名 + 摘要兜底。"""
                link = it.get("link") or it.get("url") or ""
                if not link and summary:
                    # 从 summary 中提取第一个 URL 作为兜底
                    m = re.search(r'https?://[^\s<>)\]】、，,]+', summary)
                    if m:
                        link = m.group(0)
                        print(f"    [链接兜底] 从 summary 提取链接: {link[:60]}")
                return link

            if "international" in ai_result and "china" in ai_result:
                for it in ai_result.get("international", []):
                    summary = it.get("summary", "")
                    final_items.append({
                        "title": it.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(it, summary),
                        "source": it.get("source", "AI"),
                        "region": "international",
                    })
                for it in ai_result.get("china", []):
                    summary = it.get("summary", "")
                    final_items.append({
                        "title": it.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(it, summary),
                        "source": it.get("source", "AI"),
                        "region": "china",
                    })
                print(f"\n  AI 筛选后: 国外 {len(ai_result.get('international',[]))} 条 + "
                      f"国内 {len(ai_result.get('china',[]))} 条")
            elif "items" in ai_result:
                for it in ai_result["items"]:
                    summary = it.get("summary", "")
                    final_items.append({
                        "title": it.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(it, summary),
                        "source": it.get("source", "AI"),
                    })
                print(f"\n  AI 筛选后: {len(final_items)} 条")
        else:
            ai_failed = True

    # ---- 4. GitHub Trending 项目 ----
    print(f"\n  ── 抓取 GitHub Trending 项目 ──")
    trending_projects = fetch_github_trending()
    if trending_projects:
        print(f"  📚 本周热门学习项目: {len(trending_projects)} 个")
        for p in trending_projects:
            print(f"     📌 {p['name']} ({p['tag']})")
    else:
        print("  [信息] 今日暂无合适的 Trending 项目推荐")

    # ---- 5. 写入网页 HTML ----
    print(f"\n  ── 写入网页 HTML ──")
    write_html(final_items, daily_analysis, trending_projects)

    # ---- 6. 生成邮件 HTML ----
    print(f"\n  ── 生成邮件 HTML ──")
    if ai_failed and not final_items:
        # AI 失败且无降级数据 → 空报告
        generate_email_html(
            [], f"今日无可用新闻。过滤报告：采集 {report.total_input} 条 → "
                f"过滤后 {report.total_output} 条。",
            trending_projects, filter_report=report,
            style_name="", trivia=trivia,
        )
    else:
        generate_email_html(
            final_items, daily_analysis, trending_projects,
            filter_report=report,
            style_name=style_name if not ai_failed else "降级",
            trivia=trivia,
        )

    # ---- 7. 发送邮件 ----
    print(f"\n  ── 发送邮件 ──")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(config.BASE_DIR, "send_email.py")],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print("  ✔ send_email.py 执行成功")
        else:
            print(f"  ⚠ send_email.py 返回 {result.returncode}")
            if result.stderr:
                print(f"     stderr: {result.stderr[:200]}")
    except Exception as e:
        print(f"  ✘ 调用 send_email.py 失败: {e}")

    if daily_analysis:
        print(f"\n  📊 今日深度分析:")
        print(f"     {daily_analysis[:200]}...")

    print(f"\n  ✅ 简报生成完毕 | {len(final_items)} 条新闻 | {len(trending_projects)} 个项目")
    print(f"     邮件: {config.EMAIL_OUTPUT}")
    print(f"     过滤前: {report.total_input} 条 → 过滤后: {report.total_output} 条")


if __name__ == "__main__":
    main()
