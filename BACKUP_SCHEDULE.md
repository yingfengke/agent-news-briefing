# ⏰ 备用定时触发器 — cron-job.org

## 为什么需要这个？

GitHub Actions 的 `schedule`（cron）触发**不保证准时**，高峰期可能延迟数小时甚至跳过。  
cron-job.org 是一个**免费**的外部定时服务，可以作为备用方案，确保每天 9:00 准时触发。

## 工作原理

```
cron-job.org (09:00 BJT)
    → POST 请求 → GitHub API
        → 触发 workflow_dispatch
            → GitHub Actions 执行（发邮件+更新Pages）
```

**配置一次后完全无人值守，不需要打开任何页面。**

---

## 配置步骤

### 第一步：创建 GitHub Personal Access Token

1. 打开 https://github.com/settings/tokens
2. 点击 **"Generate new token (classic)"**
3. 设置以下参数：
   - **Note**: `cron-job-briefing`
   - **Expiration**: 选 **No expiration**（或者选 1 年，到期前你邮箱会收到提醒）
   - **Scopes**: 勾选 **`repo`**（全选）和 **`workflow`**
4. 点击底部 **Generate token**
5. **⚠️ 立即复制**页面上显示的 Token（以 `ghp_` 开头），关闭后就看不到了
6. 把 Token 粘贴到下面的命令中备用

### 第二步：验证 Token 有效

打开终端（CMD / PowerShell），执行：

```bash
curl -X POST ^
  -H "Authorization: Bearer 你的TOKEN" ^
  -H "Accept: application/vnd.github+json" ^
  https://api.github.com/repos/songguyingfengke/tech-breakfast/actions/workflows/daily-briefing.yml/dispatches ^
  -d "{\"ref\":\"main\"}"
```

如果返回 HTTP 204（无内容），说明成功。  
稍等几秒去 Actions 页面看是否触发：https://github.com/songguyingfengke/tech-breakfast/actions

### 第三步：注册 cron-job.org 并创建任务

1. 打开 https://cron-job.org 点击 **Sign Up Free** 注册账号
2. 登录后点击 **Cronjobs** → **Create Cronjob**
3. 填写以下参数：

| 字段 | 值 |
|---|---|
| **Title** | `科技早餐简报` |
| **URL** | `https://api.github.com/repos/songguyingfengke/tech-breakfast/actions/workflows/daily-briefing.yml/dispatches` |
| **Request Method** | `POST` |
| **Content Type** | `application/json` |
| **Post Body** | `{"ref":"main"}` |
| **Custom Headers** | 添加一行：`Authorization: Bearer 你的TOKEN` |
| **Schedule** | `Every day at 09:00`（或自定义 `0 1 * * *`） |
| **Execution Timezone** | `Asia/Shanghai` |

4. 点击 **Create** 完成

### 第四步：验证

- 等第二天 09:00 到了以后，检查：
  - 📧 收件箱是否收到简报邮件
  - 🌐 [GitHub Actions](https://github.com/songguyingfengke/tech-breakfast/actions) 是否有运行记录

---

## 常见问题

**Q: Token 泄露了怎么办？**
A: 立即去 https://github.com/settings/tokens 删除该 Token，重新生成一个。

**Q: 能设置多个通知渠道吗？**
A: cron-job.org 支持失败时发邮件通知。在 Cronjob 详情页的 **Notification** 里开启即可。

**Q: cron-job.org 免费计划够用吗？**
A: 够。免费计划支持每天创建多个任务，对一天一次的需求绰绰有余。
