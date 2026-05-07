# AI & Agent 开发者晨报 ☕

每天早 6:00 自动推送 AI/Agent 领域最新技术动态。由 **Cloudflare Workers + GitHub Actions** 双重定时保障。

三层架构：**多模态采集 → 智能去重过滤 → AI 分析与简报生成**，全自动 serverless 运行。

---

## 架构一览

```
多模态数据采集层 (collector.py)
  ├─ RSS 源 18 个（4 大类）
  └─ 动态网页爬虫 4 站（Playwright）
       ↓ 原始数据池
智能过滤与去重层 (deduplicator.py)
  ├─ URL 去重（SHA256 数据库）
  ├─ 内容指纹去重（datasketch MinHash+LSH + jieba 分词，阈值 0.8）
  ├─ 语义去重（BAAI/bge-large-zh-v1.5 + Union-Find 聚类，阈值 0.92）
  └─ 来源可信度过滤（白名单 38 个域名 + 信号评分，阈值 0.40）
       ↓ 干净数据
AI 分析与简报生成层 (generate_briefing.py)
  ├─ 随机三套语气：极简风 / 毒舌吐槽风 / 技术深度风
  ├─ 失败自动重试 3 次
  ├─ 生成 HTML + multipart 邮件
  └─ GitHub Pages 同步更新
```

## 邮件内容板块

```
☕ AI & Agent 开发者晨报 · 今日风格：深度风
   今日从 85 条新闻中精选 30 条

⚡ 今日速览（Top 8）
🌐 国外科技
🇨🇳 国内科技
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

### 4. 部署 Cloudflare Worker（可选，推荐）

详见 [CLOUDFLARE_DEPLOY.md](./CLOUDFLARE_DEPLOY.md)。部署后 Worker 每 30 分钟检查一次，确保不漏发。

### 5. 本地测试

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # 填入真实 API Key 和邮箱授权码
python generate_briefing.py
python send_email.py
```

## 数据源阵容

### 中文媒体（5 个）
| 源 | 说明 |
|:---|:---|
| 机器之心 | 头部 AI 媒体，论文解读强 |
| 量子位 | AI 资讯平台，更新快 |
| InfoQ 中文 | AI 架构与工程实践 |
| 阿里云开发者社区 | 国内云原生动向 |
| 腾讯云开发者社区 | AI 工程实践 |

### 前沿论文（3 个）
| 源 | 说明 |
|:---|:---|
| HuggingFace 每日论文 | HF 社区精选 |
| ArXiv AI | AI 预印本 |
| PapersWithCode | 论文+代码 |

### 核心框架（6 个）
| 源 | 说明 |
|:---|:---|
| LangChain | Agent 框架官方 |
| OpenAI 博客 | 最新发布 |
| Google AI | Gemini / DeepMind |
| Anthropic | Claude 系列 |
| Meta AI | Llama 系列 |
| LlamaIndex | RAG 框架官方 |

### 全球社区（4 个）
| 源 | 说明 |
|:---|:---|
| HackerNews AI | 社区热帖 |
| Reddit ML | 社区讨论 |
| DEV.to AI | 开发者博客 |
| V2EX AI | 中文社区 |

### 动态爬虫（4 站）
| 站 | 说明 |
|:---|:---|
| 机器之心 | 官网首页 |
| 量子位 | 官网首页 |
| 魔搭社区 | 阿里模型社区 |
| OSChina | 开源技术动态 |

## 项目结构

```
├── config.py             # 集中配置（RSS源 / 爬虫 / 阈值 / AI参数 / 语气 / 彩蛋）
├── models.py             # 统一数据结构（NewsItem / FilterReport）
├── collector.py          # 采集层（RSS + 爬虫 → 数据池）
├── deduplicator.py       # 过滤层（4 阶段串联去重）
├── generate_briefing.py  # 主流程编排器
├── send_email.py         # 邮件发送（multipart/alternative）
├── advanced_crawler.py   # 旧爬虫模块（保留引用）
├── email_template.html   # 邮件模板
├── worker.js             # Cloudflare Worker 触发器
├── requirements.txt      # Python 依赖
└── .env.example          # 环境变量模板
```

## 技术参数

| 参数 | 值 |
|:---|:---|
| AI 模型 | DeepSeek-V4-Flash（硅基流动） |
| Embedding 模型 | BAAI/bge-large-zh-v1.5（1024 维） |
| MinHash 阈值 | 0.8（128 perm，jieba 分词 + 词级 3-gram） |
| 语义去重阈值 | 0.92（余弦相似度） |
| 可信度阈值 | 0.40（信号评分制） |
| 白名单域名 | 38 个 |
| 黑名单域名 | 7 个 |
| 随机语气 | 极简风 / 毒舌吐槽风 / 技术深度风 |
| 彩蛋库 | 20 条 AI 冷知识 |
| 爬虫间隔 | 10-30 秒 |
| 爬虫重试 | 3 次，递增 10/20/30 秒 |

## 触发机制

```
Cloudflare Worker (Cron */30 * * * *, 每30分钟)
  └─ checkTodayRan() → 未发则触发 workflow_dispatch
     └─ GitHub Actions (同时有 schedule 06:00 BJT 双重保障)
        ├─ 安装依赖 → Playwright + datasketch + jieba
        ├─ generate_briefing.py → 采集 → 过滤 → AI分析 → 生成
        ├─ send_email.py → multipart 邮件
        └─ 提交更新 → GitHub Pages
```

## 自定义配置

| 配置项 | 位置 |
|:---|:---|
| RSS 源列表 | `config.py` → `RSS_SOURCES` |
| 爬虫目标站 | `config.py` → `CRAWLER_TARGETS` |
| 去重阈值 | `config.py` → `DEDUP_*` |
| 白/黑名单 | `config.py` → `CREDIBILITY_*` |
| AI 语气 | `config.py` → `SYSTEM_PROMPT_*` |
| 彩蛋内容 | `config.py` → `AI_TRIVIA` |
| 推送时间 | `.github/workflows/daily-briefing.yml` → `cron` |

---

*☕ 每天早上 6:00，为 AI 开发者精选当天最重要的技术动态*
