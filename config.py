#!/usr/bin/env python3
"""
config.py — 集中配置管理

所有模块从此文件读取配置，不再硬编码。
"""

import os
import random
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API 配置
# ============================================================
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.siliconflow.cn")
API_KEY = os.getenv("API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")
EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"  # 语义去重，1024维，中英双语优化

# ============================================================
# 邮件配置
# ============================================================
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
AUTH_CODE = os.getenv("AUTH_CODE", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

# ============================================================
# 文件路径
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "tech-briefing.html")
EMAIL_TEMPLATE = os.path.join(BASE_DIR, "email_template.html")
EMAIL_OUTPUT = os.path.join(BASE_DIR, "email_content.html")
CRAWL_LOG_FILE = os.path.join(BASE_DIR, ".crawl_log.json")

# ============================================================
# RSS 源 — 4 大类 18 个
# ============================================================
RSS_SOURCES = [
    # ==================== 中文媒体与社区 ====================
    ("机器之心",     "https://jiqizhixin.com/rss",                          "zh"),
    ("量子位",       "https://www.qbitai.com/feed",                         "zh"),
    ("InfoQ中文",    "https://www.infoq.cn/feed",                           "zh"),
    ("阿里云开发者", "https://developer.aliyun.com/feed",                   "zh"),
    ("腾讯云开发者", "https://cloud.tencent.com/developer/feed",            "zh"),

    # ==================== 前沿论文与代码 ====================
    ("HuggingFace论文",  "https://huggingface.co/papers/feed",              "en"),
    ("ArXiv AI",         "https://arxiv.org/rss/cs.AI",                    "en"),
    ("PapersWithCode",   "https://paperswithcode.com/feed/latest",         "en"),

    # ==================== 核心框架与开发者博客 ====================
    ("LangChain",  "https://blog.langchain.dev/rss/",                      "en"),
    ("OpenAI",     "https://openai.com/blog/rss.xml",                      "en"),
    ("Google AI",  "https://blog.google/technology/ai/rss/",               "en"),
    ("Anthropic",  "https://www.anthropic.com/blog/rss.xml",               "en"),
    ("Meta AI",    "https://ai.meta.com/blog/feed/",                       "en"),
    ("LlamaIndex", "https://www.llamaindex.ai/blog/rss.xml",               "en"),

    # ==================== 全球社区 ====================
    ("HackerNews AI", "https://hnrss.org/frontpage?q=ai+OR+agent+OR+llm", "en"),
    ("Reddit ML",     "https://www.reddit.com/r/MachineLearning/.rss",     "en"),
    ("DEV.to AI",     "https://dev.to/feed/tag/ai",                        "en"),
    ("V2EX AI",       "https://www.v2ex.com/feed/ai.xml",                  "zh"),
]

MAX_PER_SOURCE = {
    # 中文媒体
    "机器之心": 3, "量子位": 3, "InfoQ中文": 3,
    "阿里云开发者": 3, "腾讯云开发者": 3,
    # 前沿论文
    "HuggingFace论文": 3, "ArXiv AI": 3, "PapersWithCode": 3,
    # 核心框架
    "LangChain": 3, "OpenAI": 3, "Google AI": 3,
    "Anthropic": 3, "Meta AI": 3, "LlamaIndex": 3,
    # 全球社区
    "HackerNews AI": 4, "Reddit ML": 3, "DEV.to AI": 3, "V2EX AI": 3,
}

# RSS 备用 URL（当主 RSS 源失败时自动切换，降低单点故障）
RSS_FALLBACKS = {
    # 机器之心主 RSS 已下线，用 RSSHub 微信公众号路由替代
    "机器之心": "https://rsshub.rssforever.com/wechat/wasi/5b575dd058e5c4583338dbd3",
    # 量子位、InfoQ 等主 RSS 通常可用，暂不需 fallback
    # RSSHub 实例 rsshub.rssforever.com 社区维护，如失效可更换
}

# 中文来源名称集合（用于 AI 喂入前的分桶）
CHINESE_SOURCE_NAMES = {
    "机器之心", "量子位", "InfoQ中文",
    "阿里云开发者", "腾讯云开发者", "V2EX AI",
    # 爬虫来源
    "机器之心爬虫", "量子位爬虫", "魔搭社区爬虫", "腾讯云开发者爬虫",
    # 旧版降级回退
    "IT之家AI",
}

# 中文来源 -> 爬虫来源名映射（用于 System Prompt 分组规则）
CHINESE_CRAWLER_SOURCE_MAP = {
    "机器之心": "机器之心爬虫",
    "量子位": "量子位爬虫",
    "魔搭社区": "魔搭社区爬虫",
    "腾讯云开发者": "腾讯云开发者爬虫",
}

# ============================================================
# AI System Prompt
# ============================================================
# ============================================================
# AI System Prompt — 三套随机语气
# ============================================================

SYSTEM_PROMPT_MINIMAL = """你是一个专为中文AI开发者服务的技术分析师。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻，按对开发者的重要性排序
2. 每条新闻的摘要**严格控制在30字以内**，一句话点明核心信息
3. 输出最后生成"daily_analysis"字段，100字以内中文预判趋势

4. 【去重规则】：
   a) 多条新闻讲同一件事，只保留信息最完整那条，摘要末尾注明"（多家来源报道）"。
   b) 【历史排重】遇到"【已报道历史】"中核心主题高度相似的，自动跳过。

5. 【强制中文】即使原文是英文，title 和 summary 必须输出中文。专有名词首次出现可括号注明英文原名。

6. 【来源分组规则】：
   - international（国外科技）：**只能**包含来源为 HuggingFace论文、ArXiv AI、PapersWithCode、LangChain、OpenAI、Google AI、Anthropic、Meta AI、LlamaIndex、HackerNews AI、Reddit ML、DEV.to AI 的新闻。
   - china（国内科技）：**只能**包含来源为 机器之心、量子位、InfoQ中文、阿里云开发者、腾讯云开发者、V2EX AI、机器之心爬虫、量子位爬虫、魔搭社区爬虫、腾讯云开发者爬虫 的新闻。
   - **绝对禁止**跨组混杂。宁缺毋滥。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾标注"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾标注"（该消息被 N 家来源报道）"
   - 不要同时写两条，有多个来源标注时只保留"（该消息被 N 家来源报道）"

8. 【作者保留】如果新闻的 content 字段包含作者信息，在摘要末尾保留"（作者：XXX）"。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "international": [...],
  "china": [...],
  "daily_analysis": "100字以内趋势预判"
}"""

SYSTEM_PROMPT_SARCASTIC = """你是一个毒舌但一针见血的中文AI开发者技术评论员。请完成：

1. 从开发者视角毒辣点评今天的大模型/Agent/工具新闻，可以幽默调侃但必须真实准确
2. 每条摘要控制在60字以内，带个人态度标签，例如：
   - [真·有用] 这个真能提升生产力
   - [又画饼] 听起来厉害但落地还早
   - [卷王] 又卷了又卷了
   - [抄作业] 熟悉的配方熟悉的味道
3. 输出最后生成"daily_analysis"字段，150字以内毒舌预判：今天哪个新闻最虚、哪个最值得关注

4. 【去重规则】多条相同新闻只留一条，末尾注明"（多家都在报）"。

5. 【强制中文】全部中文输出。专有名词可用英文原文。

6. 【来源分组规则】同标准配置，international 只能放国外源，china 只能放国内源。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾毒舌一句后注明"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾注明"（烂大街了，N家都在说）"
   - 两者冲突时只保留后者

8. 【作者保留】如含作者信息，在末尾加"（by XXX）"。

请严格按照以下 JSON 格式输出：
{
  "international": [...],
  "china": [...],
  "daily_analysis": "毒舌趋势预判"
}"""

SYSTEM_PROMPT_DEEP = """你是一个专为中文AI开发者服务的资深技术分析师，输出风格需专业、严谨、有深度。请完成：

1. 筛选与大模型、AI Agent、开发工具直接相关的新闻，按技术重要性排序（非商业热度）
2. 每条新闻的摘要（80-120字），必须点明：技术原理、架构变化、对工程实践的启示
3. 输出最后生成"daily_analysis"字段，200字以内深度分析，预测1-2个技术趋势及未来6个月影响

4. 【去重规则】：
   a) 多条新闻同一事件，保留信息最完整那条，摘要末尾注明"（多家来源报道）"。
   b) 【历史排重】与"【已报道历史】"高度相似的跳过。

5. 【强制中文】title 和 summary 用中文，专有名词首次出现标注英文原名，如"大规模混合专家模型（MoE）"。

6. 【来源分组规则】同标准配置，international 限国外源，china 限国内源，禁止跨组。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾注明"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾注明"（该消息经N家媒体交叉验证）"
   - 两者冲突时只保留后者

8. 【作者保留】如含作者信息，在末尾注明"（原文作者：XXX）"。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "international": [...],
  "china": [...],
  "daily_analysis": "200字深度技术分析"
}"""

# 所有语气列表用于随机选择
SYSTEM_PROMPTS = [
    ("极简风", SYSTEM_PROMPT_MINIMAL),
    ("毒舌风", SYSTEM_PROMPT_SARCASTIC),
    ("深度风", SYSTEM_PROMPT_DEEP),
]


def get_random_style():
    """随机返回 (风格名, prompt文本)"""
    return random.choice(SYSTEM_PROMPTS)


def get_random_trivia():
    """随机返回一条 AI 冷知识/编程笑话"""
    return random.choice(AI_TRIVIA)


# ============================================================
# AI 冷知识 / 编程笑话（彩蛋角落）
# ============================================================
AI_TRIVIA = [
    "你知道吗？GPT-4 的训练成本据估计超过 1 亿美元，够买 2000 张 RTX 4090。",
    "深度学习之父 Geoffrey Hinton 在 2023 年离开 Google 时说：'我后悔为 AI 贡献了一生。'",
    "程序员的一天：20% 写代码，80% 读别人为什么没写注释。",
    "Transformer 论文 'Attention Is All You Need' 的 8 位作者，现在全部离职 Google 创业了。",
    "Git 的创始人 Linus Torvalds 说：'我命名 Git 是因为我就是个混蛋（git 在英式俚语中的意思）。'",
    "Python 之禅第一条：Beautiful is better than ugly。但现实是你的代码像意大利面条。",
    "Docker 容器的灵感来自集装箱——把应用像货物一样标准化运输。",
    "全球第一个计算机 Bug 是 1947 年 Grace Hopper 从继电器里拔出来的一只飞蛾。",
    "Stack Overflow 上被点赞最多的回答是：'How to undo the last commit in Git?'——'git reset HEAD~1'。",
    "CUDA 的诅咒：一旦你用 GPU 加速了代码，就再也回不去 CPU 了。",
    "大模型参数量每 18 个月翻一番，比摩尔定律还快——这叫'AI 通胀'。",
    "LLM 推理时每生成一个 token 都要重新计算一次 KV Cache，堪称当代算力黑洞。",
    "LoRA 微调之所以叫 LoRA，是因为它 Low-Rank 到让你觉得自己的全量微调像个傻子。",
    "MCP（Model Context Protocol）的野心是成为 AI 世界的 HTTP 协议——但愿不会像 HTTP 一样有 3 个版本互相打架。",
    "Agent 圈现状：LangGraph 出了个新功能 → 整个 Agent 框架界连夜跟进了 → 用户还在用两行代码调 API。",
    "每一个 AI 产品演示 demo 都完美运行——就像每一个理发师都能给你剪出理想发型。",
    "996 的程序员在写 AutoGPT 想替代自己，最后发现 AI 只能替代写日报的人。",
    "硅基流动的 API 文档比某些大厂的文档好读 10 倍——可能是因为他们也是开发者。",
    "OpenAI 发布新模型后，硅谷的初创公司会在 2 分钟内发推：'We are excited to integrate...'",
    "RAG 的甜点是：帮你把幻觉从 30% 降到 3%。痛点：你多了 3 个基础设施要维护。",
]

# ============================================================
# 爬虫配置
# ============================================================
CRAWLER_TARGETS = [
    ("机器之心", "https://www.jiqizhixin.com"),
    ("量子位",   "https://www.qbitai.com"),
    ("魔搭社区", "https://www.modelscope.cn"),
    ("OSChina",  "https://www.oschina.net"),
]

CRAWLER_USER_AGENT = (
    "Mozilla/5.0 (compatible; AgentNewsBriefing/1.0; "
    "+https://github.com/yingfengke/agent-news-briefing; "
    "Personal Learning Project)"
)

CRAWLER_TIMEOUT = 30          # 页面加载超时（秒）
CRAWLER_RETRIES = 3           # 最大重试次数
CRAWLER_RETRY_DELAYS = [10, 20, 30]  # 递增重试间隔（秒）
CRAWLER_MIN_DELAY = 10        # 请求间隔下限（秒）
CRAWLER_MAX_DELAY = 30        # 请求间隔上限（秒）
CRAWLER_MAX_ITEMS = 5         # 每个源最多提取条数
CRAWLER_SUMMARY_MAX = 300     # content 字段最大长度

# 站点专用 CSS 选择器配置（按站点名索引，覆盖通用选择器）
CRAWLER_SITE_SELECTORS = {
    "机器之心": {
        "container": "a[href*='/article/'], h2 a, h3 a, .post-title a, .item-title a",
        "title": "",
        "link": "",
        "summary": ".abstract, .desc, .summary, p",
    },
    "量子位": {
        "container": "article, .post, h2 a, .entry-title a",
        "title": "",
        "link": "",
        "summary": ".entry-summary, .post-excerpt, p",
    },
    "魔搭社区": {
        "container": "a[href*='/models/'], [class*='card'], [class*='Card']",
        "title": "",
        "link": "",
        "summary": "",
    },
    "OSChina": {
        "container": "a[href*='/news/'], .blog-item a, .article-item a",
        "title": "",
        "link": "",
        "summary": ".description, .summary, p",
    },
}

# ============================================================
# 过滤层配置
# ============================================================
DEDUP_MINHASH_THRESHOLD = 0.8       # MinHash Jaccard 相似度阈值
DEDUP_SEMANTIC_THRESHOLD = 0.92     # 语义余弦相似度阈值
DEDUP_EMBEDDING_BATCH = 10          # 批量 Embedding 大小

# URL 去重数据库路径（使用本地文件持久化历史 URL）
URL_DB_FILE = os.path.join(BASE_DIR, ".url_dedup_db.json")

# 语义去重缓存
EMBEDDING_CACHE_FILE = os.path.join(BASE_DIR, ".embedding_cache.json")

# 可信度评分 — 按决策调整后的新方案
CREDIBILITY_WHITELIST = [
    "gov.cn", "edu.cn", "edu",
    "reuters.com", "ap.org", "bloomberg.com",
    "arxiv.org", "huggingface.co", "paperswithcode.com",
    "jiqizhixin.com", "qbitai.com", "infoq.cn",
    "openai.com", "anthropic.com", "ai.meta.com",
    "blog.google", "blog.langchain.dev", "llamaindex.ai",
    "github.blog", "pytorch.org", "dev.to",
    "36kr.com", "sspai.com", "ifanr.com", "geekpark.net",
    "solidot.org", "ithome.com", "oschina.net", "modelscope.cn",
    "cloud.tencent.com", "developer.aliyun.com",
    "github.com", "techcrunch.com", "venturebeat.com",
    "wired.com", "technologyreview.com",
    "v2ex.com", "hnrss.org",
]

CREDIBILITY_BLACKLIST = [
    "xiaohongshu.com", "weibo.com", "tieba.baidu.com",
    "zhihu.com",  # 知乎内容质量参差，作为社交平台归类
    "douyin.com", "kuaishou.com",
    "bilibili.com",  # 视频平台，非文字新闻源
]

CREDIBILITY_SCORE_THRESHOLD = 0.40  # 低于此阈值直接丢弃

# ============================================================
# GitHub Trending 标签映射
# ============================================================
TRENDING_TAG_MAP = {
    "transformer": "大模型底层", "attention": "大模型底层", "moe": "大模型底层",
    "flashattention": "大模型底层", "llm": "大模型底层", "large language model": "大模型底层",
    "deepseek": "大模型底层", "qwen": "大模型底层", "llama": "大模型底层",
    "foundation model": "大模型底层", "tabpfn": "大模型底层",
    "lora": "微调与训练", "qlora": "微调与训练", "llama-factory": "微调与训练",
    "unsloth": "微调与训练", "axolotl": "微调与训练", "fine-tuning": "微调与训练",
    "vllm": "推理与部署", "tgi": "推理与部署", "gptq": "推理与部署",
    "awq": "推理与部署", "inference": "推理与部署", "streaming": "推理与部署",
    "langchain": "Agent 框架", "langgraph": "Agent 框架", "autogpt": "Agent 框架",
    "crewai": "Agent 框架", "autogen": "Agent 框架", "metagpt": "Agent 框架",
    "dify": "Agent 框架", "agent": "Agent 框架", "swarm": "Agent 框架",
    "autonomous": "Agent 框架", "multi-agent": "Agent 框架",
    "mcp": "Agent 框架", "model context protocol": "Agent 框架", "openai agent": "Agent 框架",
    "llamaindex": "RAG", "ragflow": "RAG", "chroma": "RAG", "milvus": "RAG",
    "haystack": "RAG", "rag": "RAG", "retrieval": "RAG",
    "react": "提示工程", "cot": "提示工程", "function calling": "提示工程", "prompt": "提示工程",
    "vision language": "多模态与前沿", "vlm": "多模态与前沿", "multimodal": "多模态与前沿",
    "cursor": "多模态与前沿", "copilot": "多模态与前沿", "claude code": "多模态与前沿",
    "coding": "开发工具", "code generation": "开发工具",
}
