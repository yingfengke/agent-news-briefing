#!/usr/bin/env python3
"""
html_writer.py — HTML 写入与邮件 HTML 生成
"""

import json
import os
import re
from datetime import datetime

from src import config


def clean_links(text: str) -> str:
    """
    将 Markdown 格式的链接和裸 URL 转换为 HTML <a> 标签。
    """
    if not text:
        return text

    cleaned = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        text,
    )
    cleaned = re.sub(
        r'(https?://[^\s<>)\]】、，,]+)(?![^<]*</a>)',
        r'<a href="\1" target="_blank">\1</a>',
        cleaned,
    )

    remaining = re.findall(r'\[([^\]]+)\]\(', cleaned)
    if remaining:
        print(f"  [LINK-CHECK] 发现 {len(remaining)} 个未转换的 Markdown 链接: {remaining}")

    return cleaned


def _replace_array_var(content: str, var_name: str, new_json_str: str) -> str:
    """替换 HTML 中 JavaScript 数组变量的内容。"""
    key = f"const {var_name} ="
    start = content.find(key)
    if start < 0:
        print(f"  [警告] 未找到 {key}")
        return content

    search_from = start + len(key)
    bracket_pos = content.find("[", search_from)
    if bracket_pos < 0:
        print(f"  [警告] 未找到 [")
        return content

    array_end = content.find("];", bracket_pos)
    if array_end < 0:
        print(f"  [警告] 未找到数组结束 ];")
        return content

    return content[:bracket_pos] + new_json_str + ";" + content[array_end + 2:]


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
    content = _replace_array_var(content, "__NEWS_DATA__", indented)

    if daily_analysis:
        escaped = json.dumps(daily_analysis, ensure_ascii=False)
        key = 'const __DAILY_ANALYSIS__ = "'
        da_start = content.find(key)
        if da_start >= 0:
            val_start = da_start + len(key)
            val_end = content.find('"', val_start)
            if val_end > val_start:
                content = content[:val_start] + escaped.strip('"') + content[val_end:]

    projects_json = json.dumps(projects, ensure_ascii=False, indent=4)
    plines = projects_json.split("\n")
    pindented = "\n".join("        " + line if line.strip() else line for line in plines)
    content = _replace_array_var(content, "__PROJECTS__", pindented)

    with open(config.HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已更新 {len(news_items)} 条新闻 + {len(projects)} 个项目到 HTML")

    index_path = os.path.join(config.BASE_DIR, "web", "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已同步更新 index.html")

    _find = content.find("__NEWS_DATA__")
    if _find >= 0:
        _b = content.find("[", _find)
        _e = content.find("];", _b)
        if _e > _b:
            try:
                _data = json.loads(content[_b:_e + 1])
                print(f"  [Pages验证] index.html 已更新，新闻条数: {len(_data)} 条")
                if _data:
                    print(f"    第一条: {_data[0].get('title','')[:50]}")
            except Exception as e:
                print(f"  [Pages验证] JSON 解析失败: {e}")

    return True


def generate_email_html(news_items, daily_analysis="", projects=None,
                        filter_report=None, style_name="", trivia=""):
    if not projects:
        projects = []
    if not os.path.exists(config.EMAIL_TEMPLATE):
        print(f"[警告] 邮件模板不存在: {config.EMAIL_TEMPLATE}")
        return False

    with open(config.EMAIL_TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()

    total_input = filter_report.total_input if filter_report else 0
    total_output = filter_report.total_output if filter_report else len(news_items)
    filter_tagline = f"今日从 {total_input} 条新闻中精选 {total_output} 条"

    def make_card_html(items_list, start_no=1):
        html = []
        for i, item in enumerate(items_list, start_no):
            source_tag = (f'<span style="font-size:10px;color:#888;background:#f0f0ee;'
                          f'padding:2px 10px;border-radius:20px;">{item["source"]}</span>'
                          ) if item.get("source") else ""
            score = item.get("score", 0)
            tag = item.get("tag", "")
            stars = "star" * score if score else ""
            tag_html = (f'<span style="font-size:10px;color:#555;background:#f0f0ee;'
                        f'padding:2px 10px;border-radius:20px;margin-left:4px;">{tag}</span>'
                        ) if tag else ''
            score_html = (f'<span style="font-size:10px;color:#e67e22;margin-left:4px;">{stars}</span>'
                         ) if stars else ''
            html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:16px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {' ' + source_tag if source_tag else ''}{tag_html}{score_html}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 10px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 14px 0;line-height:1.7;">{clean_links(item["summary"])}</p>
            </td>
          </tr>
        </table>""")
        return "\n".join(html)

    news_items_html = make_card_html(news_items)
    news_sections = news_items_html

    analysis_section = ""
    if daily_analysis:
        analysis_section = f"""
        <tr>
          <td style="padding:24px 24px;background:#1a1a1a;border-radius:12px;">
            <div style="font-size:11px;color:#888;letter-spacing:1.2px;margin-bottom:12px;">Data 今日深度分析</div>
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
                <a href="{p.get("link","#")}" target="_blank" style="color:#1a1a1a;text-decoration:none;">{p.get("name","")}</a>
                <span style="font-size:12px;color:#888;margin-left:8px;">{p.get("stars","")}</span>
              </div>
              <p style="font-size:13px;color:#555;margin:4px 0 0 0;line-height:1.6;">{p.get("desc","")}</p>
              <span style="font-size:11px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;display:inline-block;margin-top:8px;">{p.get("tag","")}</span>
            </td>
          </tr>
        </table>""")
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">Data 本周热门学习项目</div>
            {''.join(proj_cards)}
          </td>
        </tr>"""
    else:
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;color:#888;text-align:center;padding:20px 0;">Data 今日暂无推荐学习项目</div>
          </td>
        </tr>"""

    filter_report_section = ""
    if filter_report:
        filter_report_section = filter_report.to_email_html()

    trivia_section = ""
    if trivia:
        trivia_section = f"""
        <tr>
          <td style="padding:16px 20px;background:#f8f8f6;border:1px solid #e5e5e5;border-radius:10px;margin-bottom:0;">
            <div style="font-size:11px;color:#888;letter-spacing:1px;margin-bottom:6px;">Data 彩蛋角落</div>
            <p style="font-size:12px;color:#666;line-height:1.7;margin:0;font-style:italic;">{clean_links(trivia)}</p>
          </td>
        </tr>"""

    web_link_section = f"""
        <tr>
          <td style="padding:24px 20px;border-top:2px dashed #ddd;border-bottom:2px dashed #ddd;">
            <div style="font-size:12px;color:#888;line-height:1.8;text-align:center;">
              <span style="font-size:14px;font-weight:700;color:#555;">Data 查看原文链接</span><br/>
              请在浏览器中打开网页版查看所有新闻原文链接及项目详情<br/>
              <span style="color:#999;font-size:11px;">yingfengke.github.io/agent-news-briefing</span>
            </div>
          </td>
        </tr>"""

    today = datetime.now()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"

    html = template.replace("{{date}}", date_str)
    html = html.replace("{{filter_tagline}}", filter_tagline)
    html = html.replace("{{news_items}}", news_sections)
    html = html.replace("{{daily_analysis_section}}", analysis_section)
    html = html.replace("{{projects_section}}", projects_section)
    html = html.replace("{{filter_report_section}}", filter_report_section)
    html = html.replace("{{trivia_section}}", trivia_section)
    html = html.replace("{{link_list_section}}", web_link_section)
    html = html.replace('href="{{repo_url}}"', 'style="color:#888;text-decoration:none;"')
    html = html.replace("{{repo_url}}", "GitHub: yingfengke/agent-news-briefing")
    if style_name:
        html = html.replace("{{style_tag}}", f" · 今日风格：{style_name}")
    else:
        html = html.replace("{{style_tag}}", "")

    with open(config.EMAIL_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[成功] 已生成邮件 HTML ({len(news_items)} 条)")

    body_only = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    loose_urls = re.findall(r'https?://[^\s<>"\'\]】、，,]+', body_only)
    if loose_urls:
        for url in loose_urls[:5]:
            print(f"  [LINK-CHECK] 发现未清理的链接: {url[:80]}")
        if len(loose_urls) > 5:
            print(f"  [LINK-CHECK] ... 还有 {len(loose_urls)-5} 个")
    else:
        print(f"  [LINK-CHECK] 邮件中无任何链接，通过")
    return True
