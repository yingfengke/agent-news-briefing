#!/usr/bin/env python3
"""
send_email.py — 通过 QQ 邮箱 SMTP 发送每日科技简报

支持 multipart/alternative（text/plain + text/html），
兼容纯文本邮件客户端降级显示。

依赖: python-dotenv, smtplib (标准库), email (标准库)
"""

import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from src import config
from src.logger import get_logger, log_structured, LOGS_DIR
import logging

log = get_logger("email")

SMTP_SERVER   = config.SMTP_SERVER
SMTP_PORT     = config.SMTP_PORT
SENDER_EMAIL  = config.SENDER_EMAIL
AUTH_CODE     = config.AUTH_CODE
RECEIVER_EMAIL = config.RECEIVER_EMAIL

HTML_FILE = config.EMAIL_OUTPUT


def get_html_content():
    """读取最终的 HTML 文件内容作为邮件正文"""
    if not os.path.exists(HTML_FILE):
        log.error("HTML 文件不存在: %s", HTML_FILE)
        return None
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        return f.read()


def html_to_plain(html: str) -> str:
    """将 HTML 转为纯文本，保留链接信息"""
    # 1. 提取 <a href> 链接并内联化
    def _inline_link(m):
        url = m.group(1) or ""
        text = m.group(2) or url
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            text = url
        if url and url != text and not text.startswith("http"):
            return f"{text} ({url})"
        return text

    # 处理 <a href="URL">text</a>
    text = re.sub(
        r'<a\s[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>',
        _inline_link, html, flags=re.IGNORECASE
    )

    # 2. 去掉 style/script 块
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", text, flags=re.IGNORECASE)

    # 3. 去掉剩余 HTML 标签
    text = re.sub(r"<[^>]+>", "\n", text)

    # 4. 清理空白
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&[a-zA-Z]+;", "", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send():
    """发送 multipart/alternative 简报邮件"""
    if not all([SENDER_EMAIL, AUTH_CODE, RECEIVER_EMAIL]):
        log.error("邮箱配置不完整，请检查 .env 文件")
        return False

    html = get_html_content()
    if not html:
        return False

    # 生成纯文本版本
    plain_text = html_to_plain(html)
    plain_path = os.path.join(config.BASE_DIR, "web", "email_content.txt")
    with open(plain_path, "w", encoding="utf-8") as f:
        f.write(plain_text)
    log.info("已生成纯文本备份 (%d 字符)", len(plain_text))

    # 主题
    today = datetime.now()
    subject = f"【AI Agent 晨报】{today.year}年{today.month:02d}月{today.day:02d}日"

    # multipart/alternative 邮件
    msg = MIMEMultipart("alternative")
    msg["From"]    = formataddr(("AI Agent 开发者晨报", SENDER_EMAIL))
    msg["To"]      = RECEIVER_EMAIL
    msg["Subject"] = Header(subject, "utf-8")
    # 标准化的 Message-ID，提升邮件信誉
    msg_id_suffix = SENDER_EMAIL.split("@")[1] if "@" in SENDER_EMAIL else "qq.com"
    msg["Message-ID"] = f"<{today.strftime('%Y%m%d%H%M%S')}.agent-news@{msg_id_suffix}>"

    # 先加纯文本版本（邮件客户端按顺序选择渲染格式）
    part_plain = MIMEText(plain_text, "plain", "utf-8")
    msg.attach(part_plain)

    # 再加 HTML 版本
    part_html = MIMEText(html, "html", "utf-8")
    msg.attach(part_html)

    try:
        log.info("连接 SMTP 服务器 %s:%d ...", SMTP_SERVER, SMTP_PORT)
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(SENDER_EMAIL, AUTH_CODE)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        log.info("发送成功")
        log_structured(log, logging.INFO, "email_send_success",
                       sender=SENDER_EMAIL, receiver=RECEIVER_EMAIL,
                       chars=len(plain_text))
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("认证失败，请检查邮箱地址和授权码是否正确")
        return False
    except smtplib.SMTPException as e:
        log.error("SMTP 错误: %s", e)
        return False
    except Exception as e:
        log.error("发送失败: %s", e)
        return False


def _strip_urls(text: str) -> str:
    """去掉 http(s) 链接，避免 QQ 邮箱因可点击链接屏蔽告警邮件。"""
    return re.sub(r'https?://\S+', '(链接已省略)', text)


def send_failure_alert(error: Exception, phase: str = "") -> bool:
    """
    简报生成失败时的主动告警（best-effort，纯文本）。

    - 不发 HTML、不附链接，规避 QQ 邮箱对可点击 URL 的屏蔽
    - 当日 marker 文件去重，避免 workflow retry 重复发信
    - 任何异常都吞掉，绝不影响主流程退出码
    """
    if not all([SENDER_EMAIL, AUTH_CODE, RECEIVER_EMAIL]):
        log.warning("邮箱配置不完整，跳过失败告警")
        return False

    today = datetime.now()
    os.makedirs(LOGS_DIR, exist_ok=True)
    marker = os.path.join(LOGS_DIR, f"alert-{today.strftime('%Y%m%d')}.sent")
    if os.path.exists(marker):
        log.info("今日失败告警已发送过，跳过重复发送")
        return False

    subject = f"【告警】AI Agent 晨报生成失败 {today.strftime('%Y-%m-%d')}"
    lines = [
        "AI Agent 开发者晨报生成失败",
        f"时间: {today.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if phase:
        lines.append(f"失败阶段: {phase}")
    err_text = f"{type(error).__name__}: {error}"
    lines.append(f"错误信息: {err_text}")
    lines.append("")
    lines.append("请到 GitHub Actions 运行日志查看完整堆栈。")
    plain = _strip_urls("\n".join(lines))

    msg = MIMEText(plain, "plain", "utf-8")
    msg["From"] = formataddr(("AI Agent 开发者晨报", SENDER_EMAIL))
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = Header(subject, "utf-8")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(SENDER_EMAIL, AUTH_CODE)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        # 仅发送成功后才写 marker，避免发信失败却误判为已告警
        with open(marker, "w", encoding="utf-8") as f:
            f.write(today.strftime("%Y-%m-%d %H:%M:%S"))
        log.info("已发送失败告警邮件")
        log_structured(log, logging.INFO, "failure_alert_sent", error=err_text)
        return True
    except Exception as e:
        log.error("失败告警邮件发送失败: %s", e)
        return False


if __name__ == "__main__":
    log.info("%s", "=" * 50)
    log.info("  每日简报邮件发送")
    log.info("%s", "=" * 50)
    log.info("  发件人: %s", SENDER_EMAIL)
    log.info("  收件人: %s", RECEIVER_EMAIL)
    send()
