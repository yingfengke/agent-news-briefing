#!/usr/bin/env python3
"""
config.py — 集中配置管理

所有模块从此文件读取配置，不再硬编码。
"""

import os
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
SYSTEM_PROMPT = """你是一个专为中文AI开发者服务的资深技术分析师，请务必使用中文回复。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻
2. 按对开发者的重要性排序，而不是商业热度
3. 每条新闻的摘要（50-100字中文），必须点明：为什么这个更新对开发者重要
4. 输出最后生成"daily_analysis"字段，200字以内中文，预判今天最重要的1-2个技术趋势及其未来半年影响

5. 【去重规则 — 严格遵守】：
   a) 如果多条新闻讲的是同一件事（例如多家媒体报道同一次发布会），只保留信息最完整的那条，并在摘要末尾注明"（多家来源报道）"。
   b) 优先分析发布时间更近的新闻。
   c) 【历史排重】我会在用户消息末尾附上"【已报道历史】"列表，列出了过去几天已推送过的新闻标题。遇到核心主题高度相似的，自动跳过，确保每天都有新信息。

6. 【强制中文 — 非常重要】即使原文是英文，**所有 title 和 summary 字段必须输出中文**。论文名称、专有名词（如模型名/框架名）第一次出现时可以括号注明英文原名。

7. 【来源分组规则 — 严格遵守，这是最重要的规则】：
   - international（国外科技）：**只能**包含来源为 HuggingFace论文、ArXiv AI、PapersWithCode、LangChain、OpenAI、Google AI、Anthropic、Meta AI、LlamaIndex、HackerNews AI、Reddit ML、DEV.to AI 的新闻。
   - china（国内科技）：**只能**包含来源为 机器之心、量子位、InfoQ中文、阿里云开发者、腾讯云开发者、V2EX AI、机器之心爬虫、量子位爬虫、魔搭社区爬虫、腾讯云开发者爬虫 的新闻。
   - **绝对禁止**把中国来源的新闻放进 international，也禁止把国外来源的新闻放进 china。
   - 如果某个分组的新闻不够3条，就保留能找到的，宁缺毋滥。

请严格按照以下 JSON 格式输出（不要加 markdown 代码块标记，不要有任何多余的文字）：
{
  "international": [
    {"title": "标题（中文）", "summary": "摘要（50-100字中文）", "link": "原文链接", "source": "来源名称"}
  ],
  "china": [
    {"title": "标题（中文）", "summary": "摘要（50-100字中文）", "link": "原文链接", "source": "来源名称"}
  ],
  "daily_analysis": "今日深度分析（200字以内中文，预判1-2个趋势）"
}"""

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
CRAWLER_RETRY_DELAY = 5       # 重试间隔（秒）
CRAWLER_MIN_DELAY = 5         # 请求间隔下限（秒）
CRAWLER_MAX_DELAY = 15        # 请求间隔上限（秒）
CRAWLER_MAX_ITEMS = 5         # 每个源最多提取条数
CRAWLER_SUMMARY_MAX = 300     # content 字段最大长度

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
