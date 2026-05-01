#!/usr/bin/env python3
"""
send_email.py — 通过 QQ 邮箱 SMTP 发送每日科技简报

依赖: python-dotenv, smtplib (标准库), email (标准库)
"""

import os
import smtplib
from datetime import datetime
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


def send():
    """发送简报邮件"""
    if not all([SENDER_EMAIL, AUTH_CODE, RECEIVER_EMAIL]):
        print("[错误] 邮箱配置不完整，请检查 .env 文件中的 SENDER_EMAIL / AUTH_CODE / RECEIVER_EMAIL")
        return False

    html = get_html_content()
    if not html:
        return False

    # 主题：【科技早餐简报】2026年04月30日
    today = datetime.now()
    subject = f"【科技早餐简报】{today.year}年{today.month:02d}月{today.day:02d}日"

    # 构造邮件（HTML 格式）
    msg = MIMEText(html, "html", "utf-8")
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER_EMAIL
    msg["Subject"] = Header(subject, "utf-8")

    try:
        print(f"  连接 SMTP 服务器 {SMTP_SERVER}:{SMTP_PORT} ...", end=" ", flush=True)
        # QQ邮箱使用 SSL
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
