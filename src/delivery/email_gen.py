"""email_gen.py - 分类邮件 HTML 生成。"""

import os
import re

from jinja2 import Environment, FileSystemLoader, TemplateError

from src import config
from src.config.sources import CATEGORY_ORDER
from src.core.logger import get_logger
from src.delivery.html_gen import TIME_DISCLAIMER

log = get_logger("html")

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
        log.debug("发现 %d 个未转换的 Markdown 链接: %s", len(remaining), remaining)

    return cleaned



def _get_category(item: dict) -> str:
    """
    取新闻分类（结果必为 CATEGORY_ORDER 之一）。

    优先级：
      1. item["category"]（由 main._resolve_category 已经校验为合法枚举）
      2. tags[0] 若属于合法枚举
      3. 仅按「标题」关键词匹配（不扫摘要，避免"其他动态"被二次拆散）
      4. 兜底 "其他动态"
    """
    cat = item.get("category")
    if cat in CATEGORY_ORDER:
        return cat

    tags = item.get("tags") or []
    if tags and isinstance(tags, list) and tags[0] in CATEGORY_ORDER:
        return tags[0]

    title = (item.get("title") or "")
    title_lower = title.lower()
    for pattern, category in TITLE_CATEGORY_MAP:
        if re.search(pattern, title_lower):
            return category
    return "其他动态"



def _merge_small_categories(groups: dict[str, list], min_size: int = 2) -> dict[str, list]:
    """
    将条目数 < min_size 的非"其他动态"分类合并进"其他动态"，
    避免邮件/网页出现大量只有 1 条新闻的零散板块。
    """
    merged = groups.get("其他动态", [])
    changed = False
    for cat in list(groups.keys()):
        if cat == "其他动态":
            continue
        if len(groups[cat]) < min_size:
            merged.extend(groups.pop(cat))
            changed = True
    if changed:
        groups["其他动态"] = merged
    return groups



def _render_email_tag_chips(item: dict) -> str:
    """把 item["tags"]（字符串数组）渲染为邮件内联样式的标签 chip。"""
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        return ""
    chips = []
    for t in tags:
        if not t:
            continue
        chips.append(
            f'<span style="font-size:10px;color:#534AB7;background:#EEEDFE;'
            f'padding:2px 10px;border-radius:20px;margin-left:4px;">{t}</span>'
        )
    return "".join(chips)



def _loose_urls(html: str) -> list:
    """
    检测「游离」链接（非 <a href> 中的链接），用于自检邮件正文是否漏出裸 URL。
    已包含在 href="..." 中的「阅读原文」等有意链接不计入。
    """
    body = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    body = re.sub(r'href="https?://[^"]*"', '', body)
    return re.findall(r'https?://[^\s<>"\'\]】、，,]+', body)



def _group_by_category(items: list) -> dict[str, list]:
    """将新闻按分类分组"""
    groups: dict[str, list] = {}
    for it in items:
        cat = _get_category(it)
        groups.setdefault(cat, []).append(it)
    return groups



def make_email_with_categories(news_items, daily_analysis="", projects=None,
                                filter_report=None, style_name="", trivia="",
                                generated_at=None):
    """
    生成带分类分组的邮件 HTML（新闻按板块渲染）。
    """
    if not projects:
        projects = []
    if not os.path.exists(config.EMAIL_TEMPLATE):
        log.warning("邮件模板不存在: %s", config.EMAIL_TEMPLATE)
        return False

    template_dir = os.path.dirname(config.EMAIL_TEMPLATE)
    template_file = os.path.basename(config.EMAIL_TEMPLATE)
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    template = env.get_template(template_file)

    total_input = filter_report.total_input if filter_report else 0
    total_output = filter_report.total_output if filter_report else len(news_items)
    filter_tagline = f"今日从 {total_input} 条新闻中精选 {total_output} 条"

    # 按分类分组
    groups = _group_by_category(news_items)
    # 合并条目过少（<2）的零散分类，避免板块过于分散
    groups = _merge_small_categories(groups, min_size=2)

    def make_card_html(items_list, start_no=1):
        html = []
        for i, item in enumerate(items_list, start_no):
            source_tag = (f'<span style="font-size:10px;color:#888;background:#f0f0ee;'
                          f'padding:2px 10px;border-radius:20px;">{item["source"]}</span>'
                          ) if item.get("source") else ""
            pub_disp = item.get("published_at_disp")
            pub_tag = (f'<span style="font-size:10px;color:#aaa;background:#f0f0ee;'
                       f'padding:2px 10px;border-radius:20px;">发布于 {pub_disp}</span>'
                       ) if pub_disp else ""
            score = item.get("score", 0)
            score_val = float(score) if isinstance(score, (int, float)) else 0
            tag_html = _render_email_tag_chips(item)
            score_text = f"{score_val:.1f}分"
            # 颜色按分数高低：高(绿) > 中(橙) > 低(灰)
            if score_val >= 4.0:
                score_color = "#2e7d32"
                score_bg = "#e8f5e9"
            elif score_val >= 3.0:
                score_color = "#e65100"
                score_bg = "#fff3e0"
            else:
                score_color = "#757575"
                score_bg = "#f5f5f5"
            score_html = (f'<span style="font-size:10px;font-weight:600;color:{score_color};'
                          f'background:{score_bg};padding:1px 8px;border-radius:10px;'
                          f'margin-left:4px;">{score_text}</span>'
                         ) if score_val > 0 else ''
            html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:10px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {' ' + source_tag if source_tag else ''}{pub_tag}{tag_html}{score_html}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 8px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 10px 0;line-height:1.7;">{clean_links(item["summary"])}</p>
              {f'<a href="{item["link"]}" style="font-size:12px;font-weight:600;color:#1a1a1a;text-decoration:none;border-bottom:1.5px solid #1a1a1a;padding-bottom:1px;" target="_blank">阅读原文</a>' if item.get("link") else ''}
            </td>
          </tr>
        </table>""")
        return "\n".join(html)

    # 按固定顺序渲染分类区块（全局连续编号，与网页版一致）
    section_parts = []
    global_index = 0
    for cat in CATEGORY_ORDER:
        if cat in groups:
            items_html = make_card_html(groups[cat], global_index + 1)
            global_index += len(groups[cat])
            section_parts.append(f"""
        <tr>
          <td style="padding:16px 0 10px 0;">
            <div style="font-size:14px;font-weight:700;color:#1a1a1a;letter-spacing:0.5px;padding-bottom:6px;border-bottom:2px solid #1a1a1a;display:inline-block;">{cat}（{len(groups[cat])}条）</div>
          </td>
        </tr>
        <tr>
          <td style="padding-bottom:10px;">{items_html}</td>
        </tr>""")

    # 未归类的
    for cat in groups:
        if cat not in CATEGORY_ORDER:
            items_html = make_card_html(groups[cat], global_index + 1)
            global_index += len(groups[cat])
            section_parts.append(f"""
        <tr>
          <td style="padding:16px 0 10px 0;">
            <div style="font-size:14px;font-weight:700;color:#1a1a1a;letter-spacing:0.5px;padding-bottom:6px;border-bottom:2px solid #1a1a1a;display:inline-block;">{cat}（{len(groups[cat])}条）</div>
          </td>
        </tr>
        <tr>
          <td style="padding-bottom:16px;">{items_html}</td>
        </tr>""")

    news_sections = "\n".join(section_parts)

    analysis_section = ""
    if daily_analysis:
        analysis_section = f"""
        <tr>
          <td style="padding:24px 24px;background:#1a1a1a;border-radius:12px;">
            <div style="font-size:11px;color:#888;letter-spacing:1.2px;margin-bottom:12px;">今日深度分析</div>
            <p style="font-size:13px;color:#ccc;line-height:1.8;margin:0;">{clean_links(daily_analysis)}</p>
          </td>
        </tr>"""

    projects_section = ""
    if projects:
        proj_cards = []
        for p in projects:
            name_html = (
                f'<a href="{p.get("link","")}" target="_blank" '
                f'style="color:#1a1a1a;text-decoration:none;'
                f'border-bottom:1px solid #1a1a1a;">{p.get("name","")}</a>'
            ) if p.get("link") else f'<span style="color:#1a1a1a;">{p.get("name","")}</span>'
            proj_cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:10px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="font-size:15px;font-weight:700;color:#111;margin-bottom:6px;">
                {name_html}
                <span style="font-size:12px;color:#888;margin-left:8px;font-weight:400;">{p.get("stars","")}</span>
              </div>
              <p style="font-size:13px;color:#555;margin:8px 0 0 0;line-height:1.7;">{p.get("desc","")}</p>
              <span style="font-size:11px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;display:inline-block;margin-top:10px;">{p.get("tag","")}</span>
            </td>
          </tr>
        </table>""")
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">本周热门学习项目</div>
            {''.join(proj_cards)}
          </td>
        </tr>"""
    else:
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;color:#888;text-align:center;padding:20px 0;">今日暂无推荐学习项目</div>
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
            <div style="font-size:11px;color:#888;letter-spacing:1px;margin-bottom:6px;">彩蛋角落</div>
            <p style="font-size:12px;color:#666;line-height:1.7;margin:0;font-style:italic;">{clean_links(trivia)}</p>
          </td>
        </tr>"""

    today = config.now_bjt()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"
    if generated_at is None:
        generated_at = today.strftime("%Y-%m-%d %H:%M（北京时间）")
    style_tag = f" · 今日风格：{style_name}" if style_name else ""

    context = {
        "date": date_str,
        "filter_tagline": filter_tagline,
        "news_items": news_sections,
        "daily_analysis_section": analysis_section,
        "projects_section": projects_section,
        "filter_report_section": filter_report_section,
        "trivia_section": trivia_section,
        "style_tag": style_tag,
        "generated_at": generated_at,
        "repo_url": "GitHub: yingfengke/agent-news-briefing",
        "time_disclaimer": TIME_DISCLAIMER,
    }

    try:
        html = template.render(**context)
    except TemplateError as e:
        log.error("Jinja2 模板渲染失败: %s", e)
        return False

    with open(config.EMAIL_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("已生成邮件 HTML（分类版，%d 条，%d 个板块）", len(news_items), len(groups))

    loose_urls = _loose_urls(html)
    if loose_urls:
        for url in loose_urls[:5]:
            log.warning("发现未清理的链接: %s", url[:80])
        if len(loose_urls) > 5:
            log.warning("... 还有 %d 个", len(loose_urls) - 5)
    else:
        log.info("邮件中无任何链接，通过")
    return True
