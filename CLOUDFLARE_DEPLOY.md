# Cloudflare Workers 部署指南

## 前置条件
- 已注册并登录 [Cloudflare](https://dash.cloudflare.com/)
- 已生成只有 `workflow` 权限的 GitHub Token

## 第一步：创建 GitHub Token（限 workflow 权限）

1. 打开 https://github.com/settings/tokens
2. 点击 **Generate new token (classic)**
3. 填写：
   - **Note**: `cloudflare-workers-触发专用`
   - **Expiration**: 选 `No expiration`（或选 1 年）
   - **Scopes**: **只勾选 `workflow`**，其他全部不勾
4. 点击 **Generate token**
5. **立即复制** 生成的 `ghp_` 开头的 Token，存到 `.env` 文件的 `CF_TRIGGER_TOKEN` 变量中

## 第二步：部署 Worker

1. 打开 [Cloudflare 控制台](https://dash.cloudflare.com/)
2. 进入 **Workers & Pages**
3. 点 **创建** → **创建 Worker**
4. 给 Worker 起名（例如 `tech-breakfast-trigger`）
5. 把项目根目录下的 `worker.js` 代码全选粘贴进去
6. 点 **部署**

## 第三步：配置环境变量

1. 进入刚创建的 Worker → **设置** → **变量和机密**
2. 添加以下变量（注意 `GITHUB_TRIGGER_TOKEN` 要选 **加密**）：

| 变量名 | 值 | 加密 |
|--------|----|------|
| `GITHUB_USERNAME` | `songguyingfengke` | ❌ |
| `GITHUB_REPO` | `agent-news-briefing` | ❌ |
| `GITHUB_WORKFLOW_FILE` | `daily-briefing.yml` | ❌ |
| `GITHUB_TRIGGER_TOKEN` | 你生成的 `ghp_` Token | ✅ **必选** |

## 第四步：添加 Cron 触发器

1. 进入 Worker → **设置** → **触发器**
2. 点 **添加 Cron 触发器**
3. 填写 Cron 表达式：`0 1 * * *`
4. ✅ 注意：Cloudflare Cron 使用 **UTC 时间**，`0 1 * * *` 即 **北京时间每天 09:00**
5. 点 **保存**

## 第五步：测试

1. 进入 Worker 的 **快速编辑** 页面
2. 点 **测试** 按钮（模拟 scheduled 事件）
3. 期望返回：`GitHub Actions triggered. Status: 204`
4. 若返回 204，说明配置成功
5. 去 https://github.com/songguyingfengke/agent-news-briefing/actions 查看是否有新运行

## 工作原理

```
Cloudflare Cron (每天 09:00 BJT)
  → Worker 脚本
    → POST 请求 GitHub API（Token 只有 workflow 权限）
      → 触发 workflow_dispatch
        → GitHub Actions 执行抓取+分析+发邮件+部署 Pages
```

## 常见问题

**Q: 返回 401/403 错误？**
A: Token 可能过期或权限不足。重新生成一个，确保只勾选 `workflow`。

**Q: 如何查看 Worker 日志？**
A: 进入 Worker → **快速编辑** → 点 **日志** 标签查看每次触发的记录。

**Q: Token 泄露了怎么办？**
A: 立即去 https://github.com/settings/tokens 删除该 Token，重新生成一个。因为该 Token 只有 `workflow` 权限，即使泄露也无法读写你的代码。
