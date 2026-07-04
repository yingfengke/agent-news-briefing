# AI & Agent 开发者晨报

每天早 6:00 自动推送 AI/Agent 领域最新技术动态。由 **GitHub Actions** 定时触发。

三层架构：**多模态采集 → 智能去重过滤 → AI 分析与简报生成**，全自动 serverless 运行。

---

## 架构一览

```
多模态数据采集层 (src/collector.py)
  └─ RSS 源 29 个（4 大类，约 20 个有效）
       ↓ 原始数据池
智能过滤与去重层 (src/deduplicator.py)
  ├─ URL 去重（SHA256 数据库，当日）
  ├─ 内容指纹去重（datasketch MinHash+LSH + jieba 分词，阈值 0.8）
  ├─ 语义去重（Qwen/Qwen3-Embedding-4B + Union-Find 聚类，阈值 0.92）
  └─ 来源可信度过滤（白名单 40 个域名 + 信号评分，阈值 0.40）
       ↓ 干净数据（来源配额制：每源保底 2 条，覆盖 >=5 个源）
AI 分析层 (src/ai_analyzer.py)
  ├─ 跨天历史排重（SequenceMatcher + 关键词模糊匹配，基于已发布简报）
  ├─ 精确 tiktoken 估算 + 安全系数（防 400 错误）
  ├─ 随机六套语气：极简风 / 毒舌风 / 深度风 / 极客风 / 微博热搜风 / 产品经理风
  ├─ 失败自动重试 3 次（step 1 + 2 各自独立重试）
  ├─ AI 主分析直接输出新闻评分（1-5 星 + 标签分类）
  └─ 生成 HTML + 邮件 + GitHub API 推送网页
       ↓ 写入 web/tech-briefing.html → 历史闭环，供次日排重使用
GitHub Pages 自动部署（从 main branch 构建）
```

## 邮件内容板块

```
☕ AI & Agent 开发者晨报 · 今日风格：深度风
  今日从 85 条新闻中精选 30 条

📌 今日新闻（按评分高→低排序）
📊 今日深度分析（AI 生成趋势预判）
📚 本周热门学习项目（GitHub Trending）
🎲 彩蛋角落（AI 冷知识 / 编程笑话）
📋 今日过滤摘要（各层去重统计）
---
本简报由 AI 自动生成 · 内容仅供参考
github.com/yingfengke/agent-news-briefing
```

## 快速部署

### 1. Fork 本项目

点击右上角 `Fork` 按钮复制到你的 GitHub 账号下。

### 2. 配置 GitHub Secrets

进入仓库 → **Settings** → **Secrets and variables** → **Actions**，添加以下 8 个 Secrets：

| Secret 名称 | 说明 | 获取方式 |
|:---|:---|:---|
| `API_BASE_URL` | 硅基流动 API 地址 | 默认 `https://api.siliconflow.cn` |
| `API_KEY` | 硅基流动 API 密钥 | [硅基流动](https://siliconflow.cn) → API 管理 → 创建密钥 |
| `MODEL_NAME` | AI 模型名 | 默认 `deepseek-ai/DeepSeek-V4-Flash` |
| `SENDER_EMAIL` | 发件人邮箱 | 你的 QQ 邮箱地址 |
| `AUTH_CODE` | QQ 邮箱授权码 | 邮箱设置 → 账户 → 开启 SMTP → 生成授权码 |
| `RECEIVER_EMAIL` | 收件邮箱 | 接收简报的邮箱 |
| `SMTP_SERVER` | SMTP 服务器 | 默认 `smtp.qq.com` |
| `SMTP_PORT` | SMTP 端口 | 默认 `465` |

### 3. 启用 Actions

进入 **Actions** 标签页，启用工作流。工作流在每天 **北京时间 06:00** 自动运行。

### 4. 本地测试

```bash
pip install -r requirements.txt
python -m src.main
python -m src.send_email
```

## 数据源阵容

### 中文媒体（5 个）
| 源 | RSS |
|:---|:---|
| 量子位 | qbitai.com/feed |
| InfoQ 中文 | infoq.cn/feed |
| 稀土掘金 AI | juejin.cn/rss |
| 少数派 | sspai.com/feed |
| **36氪** | 36kr.com/feed |

### 前沿论文（3 个）
| 源 | RSS |
|:---|:---|
| ArXiv AI / CL | arxiv.org/rss/cs.AI / cs.CL |
| HuggingFace Blog | huggingface.co/blog/feed.xml |

### 核心框架 & 大厂博客（11 个）
| 源 | RSS |
|:---|:---|
| ~~LangChain~~ | ~~langchain-blog.ghost.io/rss~~（已失效） |
| OpenAI | openai.com/blog/rss.xml |
| Google AI | blog.google/technology/ai/rss |
| VentureBeat AI | venturebeat.com/category/ai/feed |
| Anthropic News | rsshub.bestblogs.dev/anthropic/news |
| Google DeepMind | deepmind.com/blog/feed/basic/ |
| AI at Meta | rsshub.bestblogs.dev/meta/ai/blog |
| AWS ML Blog | aws.amazon.com/blogs/amazon-ai/feed/ |
| GitHub Blog | github.blog/feed/ |
| Vercel News | vercel.com/atom |
| **MIT Tech Review / The Verge AI** | technologyreview.com / theverge.com |

### Twitter 大佬 & 全球社区（11 个）
| 源 | RSS |
|:---|:---|
| HackerNews AI | hnrss.org/frontpage?q=ai+OR+agent |
| Reddit ML | reddit.com/r/MachineLearning/.rss |
| DEV.to AI | dev.to/feed/tag/ai |
| Product Hunt | producthunt.com/feed |
| **Twitter @karpathy** | xgo.ing（AI 教育/LLM 深度思考） |
| **Twitter @_akhaliq** | xgo.ing（AI 论文速递） |
| **Twitter @AndrewYNg** | xgo.ing（AI 趋势风向标） |
| **Twitter @AlexAlbert__** | xgo.ing（Anthropic 内部视角） |
| **Twitter @AIatMeta** | xgo.ing（Meta AI 官方发布） |
| **Twitter @aiDotEngineer** | xgo.ing（AI Engineer 社区） |
| TechCrunch AI | techcrunch.com/category/artificial-intelligence/feed |

> **注**：极客公园、爱范儿已临时停用（内容偏泛科技/AI 浓度低）；LangChain 域名迁移后不稳定；`PapersWithCode` 已被 Meta 关站；`V2EX AI` RSS 地址不可达。以上源已注释保留在 `config.py` 中，待恢复后随时启用。

## 项目结构

```
├── src/                    # 源代码包
│   ├── __init__.py
│   ├── main.py             # 主流程编排
│   ├── collector.py        # 采集层（RSS → 数据池）
│   ├── deduplicator.py     # 过滤层（4 阶段串联去重）
│   ├── ai_analyzer.py      # AI 分析 + Token 估算 + 质量监控
│   ├── html_writer.py      # HTML / 邮件生成
│   ├── trending_fetcher.py # GitHub Trending 抓取
│   ├── send_email.py       # 邮件发送（multipart/alternative）
│   ├── models.py           # 统一数据模型
│   └── config/             # 配置子包
│       ├── __init__.py
│       ├── constants.py    # API/邮件/阈值常量
│       ├── sources.py      # RSS 源 + 配额 + 黑白名单
│       ├── prompts.py      # 6 套 AI System Prompt
│       ├── trending_tags.py
│       ├── trivia.py / trivia.json
├── scripts/
│   └── github_api_push.py  # GitHub API 文件推送
├── web/                    # 网页 & 邮件模板
│   ├── tech-briefing.html
│   ├── index.html
│   ├── email_template.html
│   └── email_content.html  # 运行时生成（已 gitignore）
├── .githooks/              # git 安全钩子
├── .github/workflows/      # CI/CD
├── requirements.txt        # Python 依赖（已锁定版本）
└── .env.example            # 环境变量模板
```

> **运行方式**: `python -m src.main`（从项目根目录执行）

## 技术参数

| 参数 | 值 |
|:---|:---|
| AI 模型 | DeepSeek-V4-Flash（硅基流动） |
| Embedding 模型 | Qwen/Qwen3-Embedding-4B |
| MinHash 阈值 | 0.8（128 perm，jieba 分词 + 词级 3-gram） |
| 语义去重阈值 | 0.92（余弦相似度） |
| 可信度阈值 | 0.40（信号评分制） |
| 白名单域名 | 40 个 |
| 黑名单域名 | 7 个 |
| 随机语气 | 极简风 / 毒舌风 / 深度风 / 极客风 / 微博热搜风 / 产品经理风 |
| 彩蛋库 | 40 条 AI 冷知识 |
| 采集配额 | 中文媒体3条 / 论文3条 / 大厂博客2条 / Twitter大佬4条 / 社区3条 |
| 送审配额 | 来源平衡制：每源保底2条，最多送审30条 |

## 触发机制

```
GitHub Actions (schedule 06:00 BJT + 手动触发)
  ├─ 安装依赖 + pip check
  ├─ python -m src.main → 采集 → 过滤 → AI分析 → 生成 HTML
  ├─ python -m src.send_email → multipart 邮件
  └─ python scripts/github_api_push.py → API 更新网页文件
       └─ GitHub Pages 自动从 main branch 部署
```

## 自定义配置

| 配置项 | 位置 |
|:---|:---|
| RSS 源列表 | `src/config/sources.py` → `RSS_SOURCES` |
| 去重阈值 | `src/config/constants.py` → `DEDUP_*` |
| 白/黑名单 | `src/config/sources.py` → `CREDIBILITY_*` |
| AI 语气 | `src/config/prompts.py` → `SYSTEM_PROMPT_*` |
| 彩蛋内容 | `src/config/trivia.json` |
| 推送时间 | `.github/workflows/daily-briefing.yml` → `cron` |
| 安全钩子 | `.githooks/` → 克隆后执行 `git config core.hooksPath .githooks` 启用 |

---

*每天早上 6:00，为 AI 开发者精选当天最重要的技术动态*
