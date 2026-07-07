"""
阈值常量与默认配置

不包含：RSS 源、System Prompt、Trending 标签（分属 sources/prompts/trending_tags）
"""

import os

# API 配置
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.siliconflow.cn")
API_KEY = os.getenv("API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"  # 语义去重，1024维，中英双语优化

# 邮件配置
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
AUTH_CODE = os.getenv("AUTH_CODE", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

# 文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML_FILE = os.path.join(BASE_DIR, "web", "tech-briefing.html")
EMAIL_TEMPLATE = os.path.join(BASE_DIR, "web", "email_template.html")
EMAIL_OUTPUT = os.path.join(BASE_DIR, "web", "email_content.html")
CRAWL_LOG_FILE = os.path.join(BASE_DIR, ".crawl_log.json")

# 内容截断
SUMMARY_MAX_LENGTH = 500  # content 字段最大长度（字符）

# RSS 源健康跟踪
SOURCE_HEALTH_FILE = os.path.join(BASE_DIR, ".source_health.json")
SOURCE_HEALTH_MAX_FAILURES = 7  # 连续失败超过此次数则自动跳过

# 过滤层阈值
DEDUP_MINHASH_THRESHOLD = 0.8       # MinHash Jaccard 相似度阈值
DEDUP_SEMANTIC_THRESHOLD = 0.92     # 语义余弦相似度阈值
DEDUP_EMBEDDING_BATCH = 10          # 批量 Embedding 大小

# 文件路径（去重相关）
URL_DB_FILE = os.path.join(BASE_DIR, ".url_dedup_db.json")
EMBEDDING_CACHE_FILE = os.path.join(BASE_DIR, ".embedding_cache.json")

# 可信度过滤
CREDIBILITY_SCORE_THRESHOLD = 0.40  # 低于此阈值直接丢弃
