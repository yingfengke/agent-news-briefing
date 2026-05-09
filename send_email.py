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

from dotenv import load_dotenv

# ============================================================
# 加载 .env
# ============================================================
load_dotenv()

SMTP_SERVER   = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "465"))
SENDER_EMAIL  = os.getenv("SENDER_EMAIL", "")
AUTH_CODE     = os.getenv("AUTH_CODE", "")    # QQ邮箱授权码非登录密码
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "email_content.html")


def get_html_content():
    """读取最终的 HTML 文件内容作为邮件正文"""
    if not os.path.exists(HTML_FILE):
        print(f"[错误] HTML 文件不存在: {HTML_FILE}")
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
        print("[错误] 邮箱配置不完整，请检查 .env 文件中的 SENDER_EMAIL / AUTH_CODE / RECEIVER_EMAIL")
        return False

    html = get_html_content()
    if not html:
        return False

    # 生成纯文本版本
    plain_text = html_to_plain(html)
    plain_path = os.path.join(BASE_DIR, "email_content.txt")
    with open(plain_path, "w", encoding="utf-8") as f:
        f.write(plain_text)
    print(f"  ✔ 已生成纯文本备份 ({len(plain_text)} 字符)")

    # 主题
    today = datetime.now()
    subject = f"【AI Agent 晨报】{today.year}年{today.month:02d}月{today.day:02d}日"

    # multipart/alternative 邮件
    msg = MIMEMultipart("alternative")
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER_EMAIL
    msg["Subject"] = Header(subject, "utf-8")

    # 先加纯文本版本（邮件客户端按顺序选择渲染格式）
    part_plain = MIMEText(plain_text, "plain", "utf-8")
    msg.attach(part_plain)

    # 再加 HTML 版本
    part_html = MIMEText(html, "html", "utf-8")
    msg.attach(part_html)

    try:
        print(f"  连接 SMTP 服务器 {SMTP_SERVER}:{SMTP_PORT} ...", end=" ", flush=True)
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(SENDER_EMAIL, AUTH_CODE)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        print("✔ 发送成功")
        return True
    except smtplib.SMTPAuthenticationError:
        print("✘ 认证失败，请检查邮箱地址和授权码是否正确")
        return False
    except smtplib.SMTPException as e:
        print(f"✘ SMTP 错误: {e}")
        return False
    except Exception as e:
        print(f"✘ 发送失败: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("  每日简报邮件发送")
    print("=" * 50)
    print(f"  发件人: {SENDER_EMAIL}")
    print(f"  收件人: {RECEIVER_EMAIL}")
    send()
