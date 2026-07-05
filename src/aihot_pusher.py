#!/usr/bin/env python3
"""
aihot_pusher.py — AIHOT 日报补推

在每日 06:00 主流程完成后，于 08:30 抓取 AIHOT 当日精选，
与已发送的邮件内容排重，有新内容则补推邮件。

数据流：
  AIHOT API → 加载已发标题 → 过滤重复 → 有新的？→ 补推邮件
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime
from difflib import SequenceMatcher
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from urllib.request import Request, urlopen

from src import config
from src.logger import get_logger, log_structured
import logging

log = get_logger("aihot")

AIHOT_API = os.getenv("AIHOT_API", "https://aihot.virxact.com/api/curated")
SIMILARITY_THRESHOLD = 0.7  # 标题相似度超过此值视为重复


def fetch_aihot_curated() -> list[dict]:
    """从 AIHOT API 获取当日精选"""
    req = Request(AIHOT_API, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items") or data.get("data", {}).get("items") or []
        log.info("AIHOT API 返回 %d 条", len(items))
        return items
    except Exception as e:
        log.warning("AIHOT API 请求失败: %s", str(e)[:60])
        return []


def load_published_titles() -> list[str]:
    """从 tech-briefing.html 读取已发送的新闻标题（复用现有机制）"""
    try:
        from src.ai_analyzer import load_history_titles
        titles = load_history_titles()
        log.info("已发送简报标题: %d 条", len(titles))
        return titles
    except Exception as e:
        log.warning("读取已发送标题失败: %s", e)
        return []


def _is_duplicate(new_title: str, published_titles: list[str]) -> bool:
    """与已发送标题对比，判断是否重复（混合策略：SequenceMatcher + 关键词重叠）"""
    if not new_title or not published_titles:
        return False
    new_lower = new_title.lower().strip()
    for pub in published_titles:
        pub_lower = pub.lower().strip()
        if not pub_lower or not new_lower:
            continue
        # 完全匹配
        if new_lower == pub_lower:
            return True
        # SequenceMatcher 模糊匹配
        ratio = SequenceMatcher(None, new_lower, pub_lower).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            return True
        # 关键词重叠：提取两边的实义词（长度 >= 2 的中文或英文词）
        new_words = {w for w in re.split(r'[\s：:，,、()（）\[\]【】""''.!/\\-]', new_lower) if len(w) >= 2}
        pub_words = {w for w in re.split(r'[\s：:，,、()（）\[\]【】""''.!/\\-]', pub_lower) if len(w) >= 2}
        if new_words and pub_words:
            overlap = len(new_words & pub_words)
            smaller = min(len(new_words), len(pub_words))
            if overlap >= 2 and overlap / smaller >= 0.5:
                return True
    return False


def _is_today_briefing_missing() -> bool:
    """检查 tech-briefing.html 是否包含今天的数据"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read(2000)
        # 检查 HTML 中是否有今天的日期标记
        return today not in content
    except Exception:
        return True


def send_supplementary_email(new_items: list[dict], morning_failed: bool = False):
    """发送补推邮件"""
    if not new_items:
        log.info("无新增内容，跳过补推")
        return False

    if not all([config.SENDER_EMAIL, config.AUTH_CODE, config.RECEIVER_EMAIL]):
        log.error("邮箱配置不完整，跳过补推")
        return False

    today = datetime.now()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"

    # 根据早间是否失败调整文案
    if morning_failed:
        subtitle = f"AIHOT 精选 {len(new_items)} 条（早间简报未生成，此为今日完整推送）"
        intro = "今日早间 AI 分析未成功，以下为 AIHOT 精选的今日 AI 资讯："
        subject_prefix = "【AIHOT 今日推送】"
    else:
        subtitle = f"AIHOT 精选 {len(new_items)} 条补充"
        intro = "以下为 AIHOT 今日精选，与早间简报不重复："
        subject_prefix = "【AIHOT 补推】"

    # 生成邮件正文
    items_html = []
    for item in new_items[:10]:
        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "AIHOT")
        score_val = item.get("score", 0)
        score_str = f"{score_val:.1f}" if isinstance(score_val, (int, float)) else ""

        items_html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:16px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">AIHOT 补推</span>
                <span style="font-size:10px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;margin-left:4px;">{source}</span>
                {f'<span style="font-size:10px;font-weight:600;color:#2e7d32;background:#e8f5e9;padding:1px 8px;border-radius:10px;margin-left:4px;">{score_str}</span>' if score_str else ''}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 10px 0;line-height:1.5;">{title}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 14px 0;line-height:1.7;">{summary}</p>
            </td>
          </tr>
        </table>""")

    html_body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background-color:#f5f4f0;font-family:'Helvetica Neue','PingFang SC','Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f4f0;padding:30px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
<tr>
<td style="background:#ffffff;border-radius:12px;border:1px solid #e0e0e0;padding:24px;">
<div style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:11px;color:#999;letter-spacing:0.5px;margin-bottom:4px;">AIHOT 补推</div>
<h1 style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:22px;font-weight:600;color:#1a1a1a;margin:0 0 2px 0;">AI &amp; Agent 开发者晨报</h1>
<div style="width:40px;height:2px;background:#1a1a1a;margin:12px 0;"></div>
<p style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:12px;color:#888;margin:0;">{date_str} · {subtitle}</p>
</td>
</tr>
<tr><td style="padding:16px 0;">
<p style="font-size:12px;color:#888;line-height:1.6;">{intro}</p>
</td></tr>
{''.join(items_html)}
<tr>
<td style="padding:20px 0 0 0;border-top:1px solid #e0e0e0;">
<p style="font-size:11px;color:#bbb;margin:0;text-align:center;">数据来源: <a href="https://aihot.virxact.com" style="color:#888;">AIHOT</a></p>
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    # 纯文本版本
    plain_parts = [f"AIHOT 补推 - {date_str}"]
    for item in new_items[:10]:
        plain_parts.append(f"\n- {item.get('title','')}")
    plain_text = "\n".join(plain_parts)

    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("AI Agent 开发者晨报", config.SENDER_EMAIL))
    msg["To"] = config.RECEIVER_EMAIL
    msg["Subject"] = Header(f"{subject_prefix}{date_str} {len(new_items)} 条补充资讯", "utf-8")
    msg_id_suffix = config.SENDER_EMAIL.split("@")[1] if "@" in config.SENDER_EMAIL else "qq.com"
    msg["Message-ID"] = f"<{today.strftime('%Y%m%d%H%M%S')}.aihot-supplement@{msg_id_suffix}>"

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT, timeout=30) as server:
            server.login(config.SENDER_EMAIL, config.AUTH_CODE)
            server.sendmail(config.SENDER_EMAIL, [config.RECEIVER_EMAIL], msg.as_string())
        log.info("补推邮件发送成功 (%d 条)", len(new_items))
        log_structured(log, logging.INFO, "aihot_push_success",
                       count=len(new_items))
        return True
    except Exception as e:
        log.error("补推邮件发送失败: %s", e)
        return False


def main():
    log.info("=" * 50)
    log.info("  AIHOT 日报补推")
    log.info("=" * 50)

    # 1. 抓取 AIHOT 精选
    all_items = fetch_aihot_curated()
    if not all_items:
        log.info("AIHOT 无数据，跳过")
        return

    # 2. 加载已发送标题
    published_titles = load_published_titles()

    # 3. 过滤重复
    new_items = []
    for item in all_items:
        title = item.get("title", "") or item.get("name", "")
        if not title:
            continue
        if not _is_duplicate(title, published_titles):
            new_items.append(item)

    log.info("排重后: %d / %d 条为新增", len(new_items), len(all_items))

    # 4. 检测早间简报是否失败
    morning_failed = _is_today_briefing_missing()
    if morning_failed:
        log.warning("早间简报未生成（tech-briefing.html 无今日数据），AIHOT 将作为完整推送")

    # 5. 有新的就补推
    if new_items:
        send_supplementary_email(new_items[:10], morning_failed=morning_failed)
        # 记录补推标题到历史文件，供次日排重使用
        try:
            history = []
            if os.path.exists(config.AIHOT_HISTORY_FILE):
                with open(config.AIHOT_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f).get("items", [])
            new_titles = [it.get("title", "") for it in new_items[:10] if it.get("title")]
            history.extend(new_titles)
            # 保留最近 30 天
            if len(history) > 100:
                history = history[-100:]
            with open(config.AIHOT_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"updated": today.isoformat(), "items": history}, f, ensure_ascii=False)
            log.info("  AIHOT 历史已记录 %d 条标题", len(new_titles))
        except Exception as e:
            log.warning("记录 AIHOT 历史失败: %s", e)
    else:
        # 也更新网页版
        try:
            from src.html_writer import generate_rss_feed
            # 注：这里只是更新一下日志，实际 RSS 的完整内容由主流程生成
        except ImportError:
            pass
    else:
        log.info("无新增内容，无需补推")


if __name__ == "__main__":
    main()
