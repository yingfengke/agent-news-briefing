"""
阈值常量与默认配置

不包含：RSS 源、System Prompt、Trending 标签（分属 sources/prompts/trending_tags）
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

# API 配置
# 统一用 `os.getenv(X) or 默认值`：workflow 里未配置的变量会以空串传入，
# 而 getenv 的第二个参数只在变量「不存在」时生效，空串会直接把配置置空。
API_BASE_URL = os.getenv("API_BASE_URL") or "https://api.siliconflow.cn"
API_KEY = os.getenv("API_KEY", "")
# 主模型：DeepSeek 官方 API。模型名 deepseek-flash 当前指向 DeepSeek-V4.1-Flash-1017
# （2026-10-17 快照）；旧名 deepseek-v4-flash 仍可调用，会被路由到同一模型。
MODEL_NAME = os.getenv("MODEL_NAME") or "deepseek-flash"
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL") or "https://api.deepseek.com"
# 主模型专用密钥。为空时回落到通用 API_KEY（聚合网关），保证旧部署仍可运行。
MODEL_API_KEY = os.getenv("MODEL_API_KEY") or ""
# 兜底模型：默认关闭（2026-10-18 移除 Pro/zai-org/GLM-5.1）。
# 该模型依赖硅基付费额度，赠金到期后不再续费，故不再设置默认兜底。
# 如需恢复，用环境变量 FALLBACK_MODEL_NAME 配置即可，调用逻辑仍然保留。
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL_NAME") or ""
# 语义去重向量模型。bge-m3 在硅基流动免费、1024 维，实测响应 0.4s；
# 原 Qwen3-Embedding-4B 为付费且实际输出 2560 维（不是注释曾写的 1024）。
# 换模型后相似度分布会平移，阈值必须靠日志重新标定，不能沿用旧值。
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "BAAI/bge-m3"

# 送 AI 的上下文 token 预算（输入侧）。主模型与兜底模型共用，
# 应取两者中较小的输入窗口；换供应商时改这里或环境变量即可，避免超窗口被 400 拒。
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS") or "32000")

# 邮件配置
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
AUTH_CODE = os.getenv("AUTH_CODE", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")
SMTP_SERVER = os.getenv("SMTP_SERVER") or "smtp.qq.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or "465")

# 文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML_FILE = os.path.join(BASE_DIR, "web", "tech-briefing.html")
HTML_TEMPLATE = os.path.join(BASE_DIR, "web", "tech-briefing.template.html")
EMAIL_TEMPLATE = os.path.join(BASE_DIR, "web", "email_template.html")
EMAIL_OUTPUT = os.path.join(BASE_DIR, "web", "email_content.html")
CRAWL_LOG_FILE = os.path.join(BASE_DIR, ".crawl_log.json")

# 站点地址（GitHub Pages）
SITE_URL = "https://yingfengke.github.io/agent-news-briefing"

# 内容截断
SUMMARY_MAX_LENGTH = 500  # content 字段最大长度（字符）

# RSS 源健康跟踪
SOURCE_HEALTH_FILE = os.path.join(BASE_DIR, ".source_health.json")
SOURCE_HEALTH_MAX_FAILURES = 7  # 连续失败超过此次数则自动跳过
# 跳过满 N 天后强制复采一次（成功即归零、失败则再封禁 N 天），
# 否则被跳过的源不再进入采集循环、计数永不归零，会跨天永久封禁
SOURCE_HEALTH_COOLDOWN_DAYS = 7

# 过滤层阈值
DEDUP_MINHASH_THRESHOLD = 0.8       # MinHash Jaccard 相似度阈值
DEDUP_SEMANTIC_THRESHOLD = 0.92     # 语义余弦相似度阈值
DEDUP_EMBEDDING_BATCH = 10          # 批量 Embedding 大小

# 文件路径（去重相关）
URL_DB_FILE = os.path.join(BASE_DIR, ".url_dedup_db.json")
EMBEDDING_CACHE_FILE = os.path.join(BASE_DIR, ".embedding_cache.json")
# 同日重跑复用缓存：保存「已去重、未过 AI」的原始数据池，
# 重跑时直接加载并跳过采集+去重（位于 web/ 下，被 *.json gitignore 忽略）。
RAW_CACHE_FILE = os.path.join(BASE_DIR, "web", ".raw_pool_cache.json")

# 可信度过滤
CREDIBILITY_SCORE_THRESHOLD = 0.40  # 低于此阈值直接丢弃

# 简报条数硬上限。提示词里的「输出 12-18 条」是给模型的软约束，
# 实际会超出（历史出现过 21/25/27 条），此处做代码级兜底截断。
MAX_NEWS_ITEMS = 18
# 内容不足时的放宽底线：过滤后少于该条数则放宽时效窗口重试
MIN_NEWS_ITEMS = 12

# 新闻时效窗口（小时）：发布时间早于「当前时刻 - 该时长」的条目视为旧闻丢弃。
# 用于阻断跨天重复推送（某事件发布数日后被另一源转载又进新一期）。
NEWS_MAX_AGE_HOURS = 72

# 跨天历史标题库：记录近 N 天的标题与摘要，供次日事件级去重使用。
# 保留 14 天：窗口过短挡不住慢热话题，过长会让状态文件持续膨胀。
RECENT_TITLES_FILE = os.path.join(BASE_DIR, "web", ".recent_titles.json")
RECENT_TITLES_DAYS = 14

# 正文条数上限：超出部分不丢弃，压缩为简讯后单独展示
BRIEF_MAX_ITEMS = 24
# 简讯压缩用的轻量模型（与主模型分开计费，失败时本地截断兜底）
# 用 or 而非 getenv 默认值：Secrets 未配置时环境变量为空串，需回落到默认模型。
# 必须选非推理模型：Qwen3.5-4B 这类会先输出大段思考（实测 40s / 2100 token），
# 把 max_tokens 吃光后 JSON 为空，简讯整批退化成 60 字截断。
SUMMARY_MODEL_NAME = os.getenv("SUMMARY_MODEL_NAME") or "THUDM/GLM-4-9B-0414"
SUMMARY_TIMEOUT = 90
# Twitter 精选用的轻量模型。同样避开推理模型：Z1 系列思考会占满 max_tokens=128，
# 拿不到编号只能回退前 3 条。
TWITTER_FILTER_MODEL_NAME = (os.getenv("TWITTER_FILTER_MODEL_NAME")
                             or "THUDM/GLM-4-9B-0414")

# 时区：北京时间（UTC+8）。统一用此函数取"当前时间"，
# 避免 GitHub Actions runner（默认 UTC）上 datetime.now() 导致日期偏移一天。
def now_bjt():
    """返回北京时间（UTC+8）的当前时刻，供日期标签与生成时间戳使用。"""
    return datetime.now(ZoneInfo("Asia/Shanghai"))
