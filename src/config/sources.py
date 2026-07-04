"""
RSS 源配置、来源配额、可信度黑白名单
"""

RSS_SOURCES = [
    # ==================== 中文媒体与社区 ====================
    ("量子位",       "https://www.qbitai.com/feed",                         "zh"),
    ("InfoQ中文",    "https://www.infoq.cn/feed",                           "zh"),
    # 阿里云开发者 — 永久 404 已于 2026-05 确认
    # ("阿里云开发者", "https://developer.aliyun.com/feed",                   "zh"),
    # 腾讯云开发者 — 永久 404 已于 2026-05 确认
    # ("腾讯云开发者", "https://cloud.tencent.com/developer/feed",            "zh"),
    # 稀土掘金AI — 原 JSON API 非 RSS，改用 juejin.cn/rss
    ("稀土掘金AI",   "https://juejin.cn/rss",                              "zh"),
    ("少数派",       "https://sspai.com/feed",                              "zh"),
    # 新增中文源：极客公园、爱范儿（弥补阿里云/腾讯云删除后的空缺）
    # ("极客公园",     "https://www.geekpark.net/rss",                        "zh"),  # 2026-06 临时不可用，保留备用
    # ("爱范儿",       "https://www.ifanr.com/feed",                          "zh"),  # 内容偏消费电子，保留备用
    # 新增中文源：36氪（AI 创业报道，与量子位技术向互补）
    ("36氪",         "https://36kr.com/feed",                               "zh"),

    # ==================== 前沿论文与代码 ====================
    # HuggingFace论文 — 需付费 API Key (401)，改用 HuggingFace Blog
    # ("HuggingFace论文",  "https://huggingface.co/papers/feed",              "en"),
    ("ArXiv AI",         "https://arxiv.org/rss/cs.AI",                    "en"),
    ("ArXiv CL",         "https://arxiv.org/rss/cs.CL",                    "en"),
    ("HuggingFace Blog", "https://huggingface.co/blog/feed.xml",           "en"),

    # ==================== 核心框架与开发者博客 ====================
    # ("LangChain",  "https://langchain-blog.ghost.io/rss/",                 "en"),  # 域名迁移后不稳定，保留备用
    ("OpenAI",     "https://openai.com/blog/rss.xml",                      "en"),
    ("Google AI",  "https://blog.google/technology/ai/rss/",               "en"),
    # 新增大厂技术博客
    ("Anthropic News", "https://rsshub.bestblogs.dev/anthropic/news",         "en"),
    ("Google DeepMind", "https://deepmind.com/blog/feed/basic/",             "en"),
    ("AI at Meta",      "https://rsshub.bestblogs.dev/meta/ai/blog",         "en"),
    ("AWS ML Blog",     "https://aws.amazon.com/blogs/amazon-ai/feed/",      "en"),
    ("GitHub Blog",     "https://github.blog/feed/",                         "en"),
    ("Vercel News",     "https://vercel.com/atom",                           "en"),
    # Anthropic / Meta AI / LlamaIndex — 永久 404 已于 2026-05 确认
    # ("Anthropic",  "https://www.anthropic.com/blog/rss.xml",               "en"),
    # ("Meta AI",    "https://ai.meta.com/blog/feed/",                       "en"),
    # ("LlamaIndex", "https://www.llamaindex.ai/blog/rss.xml",               "en"),
    # 新增英文替代源
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/",        "en"),
    # 新增英文源
    ("MIT Tech Review", "https://www.technologyreview.com/feed/",          "en"),
    ("The Verge AI",    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "en"),

    # ==================== 全球社区 ====================
    ("HackerNews AI", "https://hnrss.org/frontpage?q=ai+OR+agent+OR+llm", "en"),
    ("Reddit ML",     "https://www.reddit.com/r/MachineLearning/.rss",     "en"),
    ("DEV.to AI",     "https://dev.to/feed/tag/ai",                        "en"),
    ("Product Hunt",  "https://www.producthunt.com/feed",                  "en"),
    # ==================== Twitter 大佬（xgo.ing RSS 桥接） ====================
    ("Twitter @karpathy",   "https://api.xgo.ing/rss/user/edf707b5c0b248579085f66d7a3c5524", "en"),
    ("Twitter @_akhaliq",   "https://api.xgo.ing/rss/user/341f7b9f8d9b477e8bb200caa7f32c6e", "en"),
    ("Twitter @AndrewYNg",  "https://api.xgo.ing/rss/user/08b5488b20bc437c8bfc317a52e5c26d", "en"),
    ("Twitter @AlexAlbert__", "https://api.xgo.ing/rss/user/524525de0d69407b80f0a7d891fdc8df", "en"),
    ("Twitter @AIatMeta",   "https://api.xgo.ing/rss/user/ef7c70f9568d45f4915169fef4ce90b4", "en"),
    ("Twitter @aiDotEngineer", "https://api.xgo.ing/rss/user/7d19a619a1cc4a9896129211269d2c85", "en"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "en"),
]

MAX_PER_SOURCE = {
    # 中文媒体（放宽到 5 条保证素材）
    "量子位": 3, "InfoQ中文": 3,
    "稀土掘金AI": 3, "少数派": 3,
    # "极客公园": 5, "爱范儿": 5,  # 已注释
    # 前沿论文
    "ArXiv AI": 3, "ArXiv CL": 3,
    "HuggingFace Blog": 3,
    # 核心框架
    # "LangChain": 3,  # 已注释
    "OpenAI": 2, "Google AI": 2,
    # 大厂技术博客
    "Anthropic News": 2, "Google DeepMind": 2,
    "AI at Meta": 2, "AWS ML Blog": 2, "GitHub Blog": 2, "Vercel News": 2,
    "VentureBeat AI": 3,
    # Twitter 大佬（调高配额，xgo.ing 稳定性好）
    "Twitter @karpathy": 4, "Twitter @_akhaliq": 4,
    "Twitter @AndrewYNg": 4, "Twitter @AlexAlbert__": 4, "Twitter @AIatMeta": 4,
    "Twitter @aiDotEngineer": 4,
    # 全球社区（高频更新源放宽到 6 条）
    "HackerNews AI": 3, "Reddit ML": 3,
    "DEV.to AI": 3,
    "Product Hunt": 3, "TechCrunch AI": 3,
    # 新增源
    "36氪": 3, "MIT Tech Review": 3, "The Verge AI": 3,
}

# RSS 备用 URL（当主 RSS 源失败时自动切换，降低单点故障）
RSS_FALLBACKS = {
    # 预留：后续如有可用的 RSSHub 实例可在此添加
}

# 中文来源名称集合（用于 AI 喂入前的分桶）
CHINESE_SOURCE_NAMES = {
    "量子位", "InfoQ中文",
    "稀土掘金AI", "少数派", "极客公园", "爱范儿", "36氪",
    # 爬虫来源
    "量子位爬虫", "魔搭社区爬虫", "腾讯云开发者爬虫",
    # 旧版降级回退
    "IT之家AI",
    # V2EX AI 已于 2026-06 确认不可用，已移除
}

# 中文来源 -> 爬虫来源名映射（用于 System Prompt 分组规则）
CHINESE_CRAWLER_SOURCE_MAP = {
    "量子位": "量子位爬虫",
    "魔搭社区": "魔搭社区爬虫",
    "腾讯云开发者": "腾讯云开发者爬虫",
}

# 可信度评分
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
    "theverge.com",
    "v2ex.com", "hnrss.org", "api.xgo.ing",
]

CREDIBILITY_BLACKLIST = [
    "xiaohongshu.com", "weibo.com", "tieba.baidu.com",
    "zhihu.com",  # 知乎内容质量参差，作为社交平台归类
    "douyin.com", "kuaishou.com",
    "bilibili.com",  # 视频平台，非文字新闻源
]
