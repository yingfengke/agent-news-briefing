#!/usr/bin/env python3
"""
github_api_push.py — 通过 GitHub Contents API 更新网页文件

在 generate_briefing.py 生成 tech-briefing.html 和 index.html 后调用。
彻底绕过 git push 冲突问题。

用法:
  python github_api_push.py

环境变量:
  GITHUB_TOKEN   — 有 repo 权限的 GitHub Token
  GITHUB_REPO    — 仓库名（默认: yingfengke/agent-news-briefing）
"""

import base64
import json
import os
import sys
import urllib.request
import urllib.error

REPO = os.environ.get("GITHUB_REPO", "yingfengke/agent-news-briefing")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FILES = ["tech-briefing.html", "index.html"]


def api_call(method: str, path: str, data: dict | None = None) -> dict:
    """调用 GitHub API，返回 JSON 响应"""
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "daily-briefing-bot",
    }
    body = json.dumps(data).encode() if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:200]
        print(f"  ❌ API {method} {path} 失败: {e.code} {e.reason}")
        print(f"     {err_body}")
        return {"error": True, "code": e.code, "detail": err_body}


def update_file(filename: str) -> bool:
    """通过 GitHub Contents API 更新一个文件"""
    filepath = os.path.join(BASE_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  ⚠ 文件不存在: {filepath}")
        return False

    with open(filepath, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    # 获取当前文件的 SHA
    info = api_call("GET", filename)
    if info.get("error"):
        if info.get("code") == 404:
            sha = ""
            print(f"  ℹ {filename} 尚不存在，将新建")
        else:
            return False
    else:
        sha = info.get("sha", "")

    # 上传新内容
    update_data = {
        "message": f"🤖 每日简报自动更新 {filename.split('.')[0]}",
        "content": content_b64,
        "sha": sha,
    }
    result = api_call("PUT", filename, update_data)
    if result.get("error"):
        return False

    print(f"  ✅ {filename} 已更新 (SHA: {result.get('content', {}).get('sha', 'N/A')[:12]}...)")
    return True


def main():
    if not TOKEN:
        print("❌ 未设置 GITHUB_TOKEN 环境变量")
        sys.exit(1)

    print(f"\n  ── 通过 GitHub API 推送网页文件 ──")
    print(f"  仓库: {REPO}")

    success = True
    for fname in FILES:
        if not update_file(fname):
            success = False

    if success:
        print(f"  ✅ 全部文件更新成功")
    else:
        print(f"  ⚠ 部分文件更新失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
