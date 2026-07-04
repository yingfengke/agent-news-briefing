#!/bin/sh
# 检查是否有 .env 文件被 git 暂存（即将提交）

STAGED_ENV=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^\.env$' || true)

if [ -n "$STAGED_ENV" ]; then
    echo ""
    echo "⚠️  [安全拦截] 检测到 .env 文件即将被提交！"
    echo "   .env 文件包含 API Key 和邮箱授权码等敏感凭证。"
    echo "   请检查是否误操作。如果确实需要提交，请使用 --no-verify 跳过。"
    echo ""
    exit 1
fi
