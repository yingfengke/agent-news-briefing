#!/usr/bin/env python3
"""
github_api_push.py — 通过 Git Data API 批量推送文件（单 commit）

将多个文件在一个 commit 中一次性推送到 main 分支，
避免 Contents API 每个文件单独 commit 触发多次 Pages 构建。

用法:
 python github_api_push.py

环境变量:
 GITHUB_TOKEN — 有 repo 权限的 GitHub Token
 GITHUB_REPO — 仓库名（默认: yingfengke/agent-news-briefing）
"""

import base64
import json
import os
import sys
import urllib.request
import urllib.error

REPO = os.environ.get("GITHUB_REPO", "yingfengke/agent-news-briefing")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = ["web/tech-briefing.html", "web/index.html", "web/rss.xml", ".url_dedup_db.json", ".source_health.json"]

API_BASE = f"https://api.github.com/repos/{REPO}"


def _headers():
    return {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "daily-briefing-bot",
    }


def _req(method: str, url: str, data: dict | None = None) -> dict:
    """安全调用 GitHub API，返回 JSON 响应"""
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:300]
        print(f"  API {method} {url.split('/repos/')[1]} 失败: {e.code} {e.reason}")
        print(f"  {err_body}")
        return {"error": True, "code": e.code, "detail": err_body}


def main():
    if not TOKEN:
        print("未设置 GITHUB_TOKEN 环境变量")
        sys.exit(1)

    print(f"\n ── Git Data API 单 commit 推送 ──")
    print(f" 仓库: {REPO}")

    # 1. 获取当前 HEAD
    ref = _req("GET", f"{API_BASE}/git/refs/heads/main")
    if ref.get("error"):
        print(" 获取 HEAD 失败")
        sys.exit(1)
    head_sha = ref["object"]["sha"]
    print(f" HEAD: {head_sha[:12]}...")

    # 2. 获取当前 tree
    commit = _req("GET", f"{API_BASE}/git/commits/{head_sha}")
    if commit.get("error"):
        print(" 获取 commit 失败")
        sys.exit(1)
    base_tree_sha = commit["tree"]["sha"]
    print(f" 基准 tree: {base_tree_sha[:12]}...")

    # 3. 为每个文件创建 blob
    blobs = []
    for fname in FILES:
        filepath = os.path.join(BASE_DIR, fname)
        if not os.path.exists(filepath):
            print(f" 跳过（不存在）: {fname}")
            continue
        with open(filepath, "rb") as f:
            content = f.read()
        blob = _req("POST", f"{API_BASE}/git/blobs", {
            "content": base64.b64encode(content).decode(),
            "encoding": "base64",
        })
        if blob.get("error"):
            print(f" 创建 blob 失败: {fname}")
            continue
        blobs.append({"path": fname, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f" blob {fname}: {blob['sha'][:12]}...")

    if not blobs:
        print(" 没有文件需要更新")
        return

    # 4. 创建新 tree（基于基准 tree + 新增 blob）
    new_tree = _req("POST", f"{API_BASE}/git/trees", {
        "base_tree": base_tree_sha,
        "tree": blobs,
    })
    if new_tree.get("error"):
        print(" 创建 tree 失败")
        sys.exit(1)
    tree_sha = new_tree["sha"]
    print(f" 新 tree: {tree_sha[:12]}...")

    # 5. 创建 commit
    new_commit = _req("POST", f"{API_BASE}/git/commits", {
        "message": "每日简报自动更新",
        "tree": tree_sha,
        "parents": [head_sha],
    })
    if new_commit.get("error"):
        print(" 创建 commit 失败")
        sys.exit(1)
    commit_sha = new_commit["sha"]
    print(f" 新 commit: {commit_sha[:12]}...")

    # 6. 更新分支引用（快速前进）
    update = _req("PATCH", f"{API_BASE}/git/refs/heads/main", {
        "sha": commit_sha,
        "force": False,
    })
    if update.get("error"):
        print(" 更新分支引用失败")
        sys.exit(1)

    print(f" 推送成功: {commit_sha[:12]}... ({len(blobs)} 个文件, 1 个 commit)")
    print(f"  Pages 将触发 1 次部署")


if __name__ == "__main__":
    main()
