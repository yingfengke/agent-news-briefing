# AI & Agent 开发者晨报

每天推送 AI/Agent 领域最新技术动态。定时设为北京时间 6:30，但 GitHub Actions 的 schedule 存在排队延迟——实测从未准点执行，多数在 8-9 点，偶尔 10-11 点。

四层架构：**多源采集 → 时效与去重过滤 → 规则预筛 → AI 分析与简报生成**，全自动 serverless 运行。

---

## 架构一览

```
多模态数据采集层 (src/collect/collector.py)
  └─ RSS 源 41 个（并发 8 线程 + 指数退避重试）
       ↓ 原始数据池
时效与去重过滤层 (src/dedupe/)
  ├─ 时效过滤（发布时间超过 72 小时丢弃；过滤后不足 12 条时窗口翻倍重试）
  ├─ URL 去重（SHA256 跨天库 + 当日去重）
  ├─ 内容指纹去重（datasketch MinHash+LSH + jieba 分词，阈值 0.8）
  ├─ 语义去重（BAAI/bge-m3 向量 + numpy 矩阵批量计算，阈值 0.92）
  └─ 来源可信度过滤（白名单 50 个域名 + 信号评分，阈值 0.40）
       ↓ 干净数据
规则预筛层 (src/analysis/context.py)
  ├─ 过滤正文 < 10 字的垃圾内容与提示词注入
  └─ Twitter 源间去重（同标题推文保留最完整的一条）
       ↓ 配额制选 40 条（每源保底 2 条，覆盖 >=5 个源）
AI 分析层 (src/analysis/)
  ├─ Twitter 专用精选：轻量模型 GLM-4-9B（失败改用主模型）
  ├─ 跨天事件排重（近 14 天标题+摘要，整句/关键词/稀有实体/内容重合四条路径）
  ├─ 跨天续报标注（语义筛候选 + 重排模型判同事件，命中则标题加「进展：」）
  ├─ 精确 tiktoken 估算 + 安全系数（防 400 错误）
  ├─ 六套语气按日期轮换（相邻两天不重复）：极简资讯 / 工程实战派 / 深度解读 / 极客观点 / 微博热搜 / 产品经理
  ├─ 主模型 deepseek-flash（DeepSeek 官方 API，显式关闭 thinking）
  ├─ 评分按三步决策树：定基础档 → 升降档 → 档内微调（0-5 分）
  └─ 生成 HTML + 分类邮件 + RSS Feed
       ↓ 正文 18 条 + 简讯（超出部分由轻量模型压成一句话；同一事件正文最多 2 条）
GitHub Pages 自动部署（从 main branch 构建）
```

## 邮件内容板块

```
DAILY BRIEFING · 今日风格：深度解读
AI & Agent 开发者晨报
─────────────────────
2026年10月18日 · 今日从 84 条新闻中精选 18 条（另有 N 条简讯）

大模型 (3条)       ── 按板块分类展示
  ── [来源] 新闻卡片（评分 4.2）...
Agent框架 (2条)
  ── [来源] 新闻卡片（评分 3.8）...
...
📌 更多要闻（未进正文的条目，一句话简讯）
📊 今日深度分析（AI 生成趋势预判）
🚀 本周热门学习项目（GitHub Trending）
🎲 彩蛋角落（AI 冷知识 / 编程笑话）
📋 今日过滤摘要（各层去重统计）
---
本简报由 AI 自动生成 · 内容仅供参考
GitHub: yingfengke/agent-news-briefing
```

## 快速部署

### 1. Fork 本项目

点击右上角 `Fork` 按钮复制到你的 GitHub 账号下。

### 2. 配置 GitHub Secrets 与 Variables

进入仓库 → **Settings** → **Secrets and variables** → **Actions**。

**Secrets（密钥与个人信息，必填）**

| 名称 | 说明 | 获取方式 |
|:---|:---|:---|
| `MODEL_API_KEY` | DeepSeek 官方 API 密钥 | [DeepSeek 开放平台](https://platform.deepseek.com) → API keys |
| `API_KEY` | 硅基流动 API 密钥 | [硅基流动](https://siliconflow.cn) → API 管理 → 创建密钥 |
| `AUTH_CODE` | QQ 邮箱授权码 | 邮箱设置 → 账户 → 开启 SMTP → 生成授权码 |
| `SENDER_EMAIL` | 发件邮箱 | 你的 QQ 邮箱地址 |
| `RECEIVER_EMAIL` | 收件邮箱 | 接收简报的邮箱 |

**Variables（公开配置，可选；不配置则使用代码默认值）**

| 名称 | 默认值 | 说明 |
|:---|:---|:---|
| `MODEL_NAME` | `deepseek-flash` | 主模型，当前指向 DeepSeek-V4.1-Flash-1017 |
| `MODEL_BASE_URL` | `https://api.deepseek.com` | 主模型接入地址 |
| `API_BASE_URL` | `https://api.siliconflow.cn` | 向量与轻量模型接入地址 |
| `SUMMARY_MODEL_NAME` | `THUDM/GLM-4-9B-0414` | 简讯压缩模型 |
| `TWITTER_FILTER_MODEL_NAME` | `THUDM/GLM-4-9B-0414` | Twitter 精选模型 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 语义去重向量模型 |
| `FALLBACK_MODEL_NAME` | 空 | 兜底模型，默认不启用 |
| `SMTP_SERVER` / `SMTP_PORT` | `smtp.qq.com` / `465` | 邮件服务器 |
| `MAX_CONTEXT_TOKENS` | `32000` | 送审上下文预算 |

> **注**：工作流按模型拆分接入点——主模型走 DeepSeek 官方，向量与轻量模型走硅基流动。步骤③的 Git 提交作者邮箱由 `SENDER_EMAIL` 注入（须为 GitHub 账号已验证且用于贡献的邮箱，贡献图绿点才会计入），作者名取 `github.repository_owner`。该步骤显式设置 `TZ: Asia/Shanghai`，使北京时间 06:30 的提交时间戳为 `+0800` 并正确计入当天绿点（否则 Actions 服务器的 UTC 时间会将绿点记到前一天）。

### 3. 启用 Actions

进入 **Actions** 标签页，启用工作流。工作流设定每天 **北京时间 06:30** 触发；实际执行受 Actions 排队影响，多数在 08:00-09:00，偶尔 10:00-11:00。

### 4. 本地测试

```bash
pip install -r requirements.txt
python -m src.main
python -m src.delivery.send_email
```

## 数据源阵容

### 中文媒体（3 个）
| 源 | RSS |
|:---|:---|
| 量子位 | qbitai.com/feed |
| InfoQ 中文 | infoq.cn/feed |
| **36氪** | 36kr.com/feed |

### 前沿论文与 AI 媒体（16 个）
| 源 | RSS |
|:---|:---|
| ArXiv AI / CL / LG / CV | arxiv.org/rss/cs.AI / cs.CL / cs.LG / cs.CV |
| HuggingFace Blog | huggingface.co/blog/feed.xml |
| **The Decoder** | the-decoder.com/feed |
| **MarkTechPost** | marktechpost.com/feed |
| **TLDR AI** | tldr.tech/api/rss/ai |
| **Last Week in AI** | lastweekin.ai/feed |
| Import AI | importai.net/feed.xml |
| Simon Willison | simonwillison.net/atom/everything/ |
| BAIR Blog | bair.berkeley.edu/blog/feed.xml |
| Ahead of AI | magazine.sebastianraschka.com/feed |
| The Gradient | thegradient.pub/rss/ |
| Latent Space | latent.space/feed |
| Interconnects | interconnects.ai/feed |

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

> **注**：极客公园、爱范儿已临时停用（内容偏泛科技/AI 浓度低）；LangChain 域名迁移后不稳定；`PapersWithCode` 已被 Meta 关站；`V2EX AI` RSS 地址不可达。以上源已注释保留在 `src/config/sources.py` 中，待恢复后随时启用。

## 项目结构

```
├── src/                    # 源代码包
│   ├── __init__.py
│   ├── main.py             # 主流程编排（唯一入口，python -m src.main）
│   ├── core/               # 共享基建包
│   │   ├── models.py       # 统一数据模型
│   │   ├── logger.py       # 集中式日志系统 + 阶段计时器
│   │   ├── entities.py     # 产品型号提取与归一化（同事件归组）
│   │   ├── http_utils.py   # HTTP 异常详情提取
│   │   ├── history_titles.py # 近 14 天已推内容库（跨天排重）
│   │   └── rerun.py        # 同日重跑与缓存复用
│   ├── collect/            # 采集层包
│   │   ├── collector.py    # 采集层（RSS → 数据池，并发 8 线程）
│   │   └── trending_fetcher.py # GitHub Trending 抓取（BeautifulSoup）
│   ├── dedupe/             # 独立去重/过滤层包（5 阶段串联）
│   │   ├── pipeline.py     # 编排：run_pipeline 串联各阶段
│   │   ├── freshness.py    # 阶段 A0：时效过滤（72 小时窗口）
│   │   ├── url_dedup.py   # 阶段 A：URL 去重（SHA256 跨天库）
│   │   ├── minhash_dedup.py # 阶段 B：MinHash+LSH 内容指纹
│   │   ├── semantic_dedup.py # 阶段 C：Embedding 语义去重
│   │   └── credibility.py  # 阶段 D：来源可信度过滤
│   ├── analysis/           # AI 分析域包
│   │   ├── orchestrator.py # 编排 facade（重导出公共 API）
│   │   ├── context.py     # 上下文预组装：历史排重/预筛/配额/截断
│   │   ├── invoke.py       # 模型调用与重试（按接入点分发）
│   │   ├── postprocess.py  # AI 输出后处理 + 降级兜底
│   │   ├── summarize.py    # 正文/简讯拆分、简讯压缩、同事件配额
│   │   ├── event_cluster.py # 事件级判定：跨天续报标注 + 簇配额
│   │   ├── json_parse.py   # JSON 解析（5 层兜底 + 截断抢救）
│   │   ├── twitter_filter.py # Twitter 精选（GLM-4-9B，失败转主模型）
│   │   └── translate.py    # 英文标题翻译兜底
│   ├── delivery/           # 输出/邮件层包
│   │   ├── html_gen.py    # 网页 HTML 生成（tech-briefing.html）
│   │   ├── email_gen.py   # 分类邮件 HTML 生成
│   │   ├── rss_gen.py     # RSS 2.0 Feed 生成
│   │   ├── send_email.py   # 邮件发送（multipart/alternative）
│   │   └── timefmt.py     # 发布时间格式化（UTC → 北京时间）
│   └── config/             # 配置子包
│       ├── __init__.py
│       ├── constants.py    # API/邮件/阈值常量
│       ├── sources.py      # RSS 源 + 配额 + 黑白名单
│       ├── prompts.py      # 6 套 AI System Prompt
│       ├── trending_tags.py
│       ├── trivia.py / trivia.json
│   └── tools/              # 诊断工具
│       └── check_models.py # 模型可用性探测（手动运行）
├── scripts/
│   └── github_api_push.py  # 历史脚本，已停用（现由 git push 提交网页）
├── web/                    # 网页 & 邮件模板 & RSS Feed
│   ├── tech-briefing.html
│   ├── index.html
│   ├── rss.xml             # 运行时生成（RSS 2.0 Feed）
│   ├── email_template.html
│   └── email_content.html  # 运行时生成（已 gitignore）
├── logs/                   # 运行时日志（已 gitignore）
├── .githooks/              # git 安全钩子
├── .github/workflows/      # CI/CD
├── tests/                  # 单元测试（236 个，覆盖全部核心模块）
├── requirements.txt        # Python 依赖（已锁定版本）
└── .env.example            # 环境变量模板
```

> **运行方式**: `python -m src.main`（从项目根目录执行）

## 技术参数

| 参数 | 值 |
|:---|:---|
| 主模型 | deepseek-flash（DeepSeek 官方 API，当前指向 V4.1-Flash-1017） |
| 轻量模型 | THUDM/GLM-4-9B-0414（简讯压缩 / Twitter 精选） |
| Embedding 模型 | BAAI/bge-m3（1024 维） |
| MinHash 阈值 | 0.8（128 perm，jieba 分词 + 词级 3-gram） |
| 语义去重阈值 | 0.92（余弦相似度） |
| 事件判定 | embedding 筛候选（≥0.65）+ 重排模型双向判同一事件（≥0.45） |
| 可信度阈值 | 0.40（信号评分制） |
| 时效窗口 | 72 小时（过滤后不足 12 条时窗口翻倍重试） |
| 跨天内容库 | 近 14 天（标题 + 摘要） |
| 白名单域名 | 50 个 |
| 黑名单域名 | 7 个 |
| 正文条数 | 18 条（同一型号最多 2 条，超出转入简讯） |
| 简讯条数 | 最多 24 条 |
| 每日语气（轮换） | 极简资讯 / 工程实战派 / 深度解读 / 极客观点 / 微博热搜 / 产品经理 |
| 彩蛋库 | 40 条 AI 冷知识 |
| 采集配额 | 中文媒体3条 / 论文3条 / AI媒体3条 / 大厂博客2条 / Twitter大佬4条 / 社区3条 |
| 送审配额 | 来源平衡制：每源保底2条，最多送审40条 |
| 自动化测试 | 236 个 |

## 触发机制

```
GitHub Actions (schedule 设定 06:30 BJT；实际 08-09 点居多，偶有 10-11 点；支持手动触发)
  ├─ 步骤①: python -m src.main → 采集 → 过滤 → 规则预筛 → AI分析 → 生成 HTML
  ├─ 步骤②: python -m src.delivery.send_email → multipart 邮件
  ├─ 步骤③: git push → 提交并推送网页文件（贡献图计数）
  └─ GitHub Pages 自动从 main branch 部署
```

## 自定义配置

| 配置项 | 位置 |
|:---|:---|
| RSS 源列表 | `src/config/sources.py` → `RSS_SOURCES` |
| 去重阈值 | `src/config/constants.py` → `DEDUP_*` |
| 时效窗口 | `src/config/constants.py` → `NEWS_MAX_AGE_HOURS` |
| 跨天内容保留期 | `src/config/constants.py` → `RECENT_TITLES_DAYS` |
| 正文条数与简讯上限 | `src/config/constants.py` → `MAX_NEWS_ITEMS` / `BRIEF_MAX_ITEMS` |
| 同事件正文配额 | `src/analysis/summarize.py` → `SAME_EVENT_MAX_IN_BODY` |
| 事件判定阈值 | `src/analysis/event_cluster.py` → `EMBED_CANDIDATE_THRESHOLD` / `SAME_EVENT_THRESHOLD` |
| 模型接入点 | `src/config/constants.py` → `MODEL_*` / `API_*` |
| 白/黑名单 | `src/config/sources.py` → `CREDIBILITY_*` |
| 新闻分类配置 | `src/config/sources.py` → `CATEGORY_ORDER` / `TITLE_CATEGORY_MAP` |
| AI 语气 | `src/config/prompts.py` → `SYSTEM_PROMPT_*` |
| 彩蛋内容 | `src/config/trivia.json` |
| 推送时间 | `.github/workflows/daily-briefing.yml` → `cron` |
| 安全钩子 | `.githooks/` → 克隆后执行 `git config core.hooksPath .githooks` 启用 |

---

*每天早间，为 AI 开发者精选当天最重要的技术动态（定时 6:30，实际多在 8-9 点执行）*
