# AI & Agent 开发者晨报 ☕

自动抓取 AI/Agent 领域最新新闻，通过大模型（硅基流动 DeepSeek-V4-Flash）分析筛选，生成每日简报，发送邮件 + 更新 GitHub Pages。每天早 9:00 由 Cloudflare Workers 准时触发，无需依赖不可靠的 GitHub Actions 定时器。还附带每日 GitHub 热门 AI/Agent/RAG 开源项目推荐。

## 触发方式

本项目使用 **Cloudflare Workers Cron 触发器** 作为主要定时机制，比 GitHub Actions 自带的 `schedule` 更可靠（不会延迟/跳过）。工作流：

```
Cloudflare Workers (每天 09:00 BJT)
  → 调用 GitHub API → 触发 workflow_dispatch
    → GitHub Actions 执行：抓取 RSS → AI 分析 → 发邮件 → 更新 Pages
```

## 快速部署（5 分钟）

### 1. Fork 本项目

点击右上角 `Fork` 按钮，将项目复制到你的 GitHub 账号下。

### 2. 配置 GitHub Secrets

进入你 Fork 后的仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，逐一添加以下 8 个 Secrets：

| Secret 名称 | 说明 | 如何获取 |
| :--- | :--- | :--- |
| `API_BASE_URL` | 硅基流动 API 地址 | 默认 `https://api.siliconflow.cn` |
| `API_KEY` | 硅基流动 API 密钥 | 注册 [硅基流动](https://siliconflow.cn)，在 API 管理页面创建 |
| `MODEL_NAME` | AI 模型名 | 默认 `deepseek-ai/DeepSeek-V4-Flash` |
| `SENDER_EMAIL` | 发件人 QQ 邮箱 | 你的 QQ 邮箱完整地址，如 `123456@qq.com` |
| `AUTH_CODE` | QQ 邮箱授权码 | 登录 QQ 邮箱 → 设置 → 账户 → 开启 SMTP 服务 → 生成授权码 |
| `RECEIVER_EMAIL` | 收件人邮箱 | 你想接收简报的邮箱 |
| `SMTP_SERVER` | SMTP 服务器 | 默认 `smtp.qq.com` |
| `SMTP_PORT` | SMTP 端口 | 默认 `465` |

> ⚠️ **安全提醒**：切勿将真实 API Key 或授权码直接写入代码并提交到公开仓库。
> 所有敏感信息只存放在 GitHub Secrets 或本地 `.env` 文件中。
> 
> ⚠️**注意**:上述操作仅为本人操作方式，可以根据自己的实际情况添加对应的模型API和邮箱

### 3. 启用 GitHub Actions

进入 **Actions** 标签页，点击 **"I understand my workflows, go ahead and enable them"** 启用工作流。

工作流默认在 **北京时间每天早 9:00** 自动运行（cron: `0 1 * * *` UTC）。

### 4. 手动测试

进入 **Actions** → **每日科技早餐简报** → **Run workflow** → 点击绿色按钮，手动触发一次。

等待约 2-3 分钟，查看：
- 📧 邮箱是否收到邮件
- 🌐 [GitHub Pages 页面](https://songguyingfengke.github.io/tech-breakfast/) 是否更新

### 5. 本地测试（可选）

```bash
# 安装依赖
pip install python-dotenv

# 复制配置
cp .env.example .env
# 编辑 .env，填入真实 API Key 和邮箱授权码

# 生成简报
python generate_briefing.py

# 发送邮件
python send_email.py

# 查看网页效果
# 用浏览器打开 tech-briefing.html
```

## 自定义配置

| 配置项 | 位置 | 说明 |
| :--- | :--- | :--- |
| RSS 数据源 | `generate_briefing.py` 中的 `RSS_SOURCES` 列表 | 增删你想关注的新闻源 |
| AI 分析指令 | `generate_briefing.py` 中的 `SYSTEM_PROMPT` | 修改 prompt 改变筛选逻辑 |
| 推送时间 | `.github/workflows/daily-briefing.yml` 中的 `cron` | 注意使用 UTC 时间 |
| AI 模型 | 同上 workflow 文件，或 `.env` 中的 `MODEL_NAME` | 可换成其他 SiliconFlow 支持的模型 |
| 收件邮箱 | 本地 `.env` 或 GitHub Secrets 中的 `RECEIVER_EMAIL` | 可设置多个收件人（逗号分隔需改代码） |

## 数据源阵容（11 个）

### 国际新闻
| 源 | 领域 |
| :--- | :--- |
| TechCrunch AI | AI 创投 / 产品发布 |
| VentureBeat AI | AI 产业动态 |
| ArsTechnica | 技术深度 / 政策 |
| HackerNews | 社区热帖 |
| DEV Community | 开发者博客 |

### 中文新闻
| 源 | 领域 |
| :--- | :--- |
| Solidot | 开源 / 科技资讯 |
| InfoQ | 开发者技术社区 |
| 36氪 | 科技商业资讯 |

### GitHub 项目 Release 推送
| 项目 | 说明 |
| :--- | :--- |
| LangChain | Agent 框架 |
| CrewAI | 多 Agent 编排 |
| AutoGen | 微软多 Agent 框架 |

## 技术架构

```
RSS 源 (11个)  ──→  Python 抓取  ──→  硅基流动 API (DeepSeek-V4-Flash)
                                           │
                                     AI 筛选/排序/摘要
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                         GitHub Pages   HTML 邮件   深度分析卡片
                              ↑
                     每天 9:00 自动更新
```

## 项目结构

```
├── .env.example          # 配置模板（复制为 .env 并填入真实值）
├── .github/
│   └── workflows/
│       └── daily-briefing.yml   # GitHub Actions 工作流
├── generate_briefing.py  # RSS 抓取 + AI 分析 + HTML生成
├── send_email.py         # QQ邮箱 SMTP 发送
├── email_template.html   # 邮件 HTML 模板（纯静态，无JS）
├── tech-briefing.html    # GitHub Pages 展示页面
├── index.html            # Pages 入口（由工作流自动生成）
└── 项目配置说明.txt       # 详细配置指南
```

## 常见问题

**Q: 早上 9 点没有收到邮件？**
A: 新仓库的 cron 调度可能需要 24-48 小时才能稳定生效。在此期间可手动触发 workflow 测试，或向 `main` 分支推送一次代码触发运行。

**Q: RSS 源抓取失败？**
A: 部分境外 RSS 源可能因网络问题间歇性超时（尤其在国内服务器上）。脚本会自动跳过失败源，不影响整体运行。

**Q: 想换别的 AI 模型？**
A: 硅基流动支持多种模型，修改 `.env` 中的 `MODEL_NAME` 即可，例如 `Qwen/Qwen2.5-72B-Instruct`。

---

*☕ 每天早上 9:00，为 AI 开发者精选当天最重要的技术动态*
