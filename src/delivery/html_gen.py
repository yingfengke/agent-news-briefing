#!/usr/bin/env python3
"""html_gen.py - 网页 HTML 生成（tech-briefing.html + index 重定向占位）。"""

import json
import os

from jinja2 import Environment, FileSystemLoader, TemplateError

from src import config
from src.core.logger import get_logger

log = get_logger("html")

# 时间换算免责声明：摘要括号内日期由 AI 按发布日推算，可能不准，原文才是基准
TIME_DISCLAIMER = (
    "注：摘要中括号内的日期由 AI 按发布日推算，仅供参考、可能不准，"
    "请以每条「发布于」时间为准。"
)

def _json_to_js(data) -> str:
    """将 Python 对象序列化为可安全嵌入 <script> 的 JSON 字符串。

    把 '<' 转义为 '\\u003c'，防止新闻内容中的 '</script>' 提前闭合脚本标签。
    """
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")



def _render_index_redirect() -> str:
    """
    生成 web/index.html 的占位内容：仅做 0 秒重定向到 tech-briefing.html。

    真实新闻数据只写一份到 tech-briefing.html（analysis.orchestrator 也从中读历史标题），
    index.html 只作为 GitHub Pages 默认入口的跳转页，避免两份大段 HTML 重复维护。
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta http-equiv="refresh" content="0; url=tech-briefing.html">\n'
        "  <title>AI &amp; Agent 开发者晨报</title>\n"
        "</head>\n"
        "<body>\n"
        '  <p style="font-family:sans-serif;text-align:center;margin-top:48px;color:#555;">\n'
        '    正在加载今日简报… 若未自动跳转，请\n'
        '    <a href="tech-briefing.html">点击此处查看</a>。\n'
        "  </p>\n"
        "</body>\n"
        "</html>\n"
    )



def write_html(news_items, daily_analysis="", projects=None, generated_at=None):
    if not projects:
        projects = []
    if not os.path.exists(config.HTML_TEMPLATE):
        log.error("网页模板不存在: %s", config.HTML_TEMPLATE)
        return False

    if generated_at is None:
        generated_at = config.now_bjt().strftime("%Y-%m-%d %H:%M（北京时间）")
    briefing_date = config.now_bjt().strftime("%Y年%m月%d日")

    template_dir = os.path.dirname(config.HTML_TEMPLATE)
    template_file = os.path.basename(config.HTML_TEMPLATE)
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    try:
        template = env.get_template(template_file)
    except TemplateError as e:
        log.error("网页模板加载失败: %s", e)
        return False

    context = {
        "news_data_json": _json_to_js(news_items),
        "daily_analysis_json": _json_to_js(daily_analysis),
        "projects_json": _json_to_js(projects),
        "generated_at": generated_at,
        "briefing_date": briefing_date,
        "time_disclaimer": TIME_DISCLAIMER,
    }
    try:
        content = template.render(**context)
    except TemplateError as e:
        log.error("网页模板渲染失败: %s", e)
        return False

    with open(config.HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("已更新 %d 条新闻 + %d 个项目到 %s", len(news_items), len(projects),
             os.path.basename(config.HTML_FILE))

    # index.html 只写固定重定向占位，不再重复写入完整新闻内容
    index_path = os.path.join(config.BASE_DIR, "web", "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(_render_index_redirect())
    log.info("已写入 index.html 重定向占位 -> tech-briefing.html")

    if news_items:
        log.info("  第一条: %s", news_items[0].get("title", "")[:50])
    return True
