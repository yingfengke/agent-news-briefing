#!/usr/bin/env python3
"""
config.py — 集中配置管理

所有模块从此文件读取配置，不再硬编码。
"""

import os
import json
import random
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API 配置
# ============================================================
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.siliconflow.cn")
API_KEY = os.getenv("API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"  # 语义去重，1024维，中英双语优化

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
# RSS 源 — 4 大类 29 个
# ============================================================
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

# ============================================================
# AI System Prompt
# ============================================================
# ============================================================
# AI System Prompt — 三套随机语气
# ============================================================

SYSTEM_PROMPT_MINIMAL = """你是一个专为中文AI开发者服务的技术分析师。请完成：

1. 筛选出与大模型、AI Agent、开发工具直接相关的新闻，按对开发者的重要性排序
2. 每条新闻的摘要**严格控制在50-60字以内**，一句话点明核心信息。**摘要中不要包含任何链接或URL。**
3. 输出最后生成"daily_analysis"字段，100字以内中文预判趋势

4. 【去重规则】：
   a) 多条新闻讲同一件事，只保留信息最完整那条，摘要末尾注明"（多家来源报道）"。
   b) 【历史排重】遇到"【已报道历史】"中核心主题高度相似的，自动跳过。

5. 【强制中文】即使原文是英文，title 和 summary 必须输出中文。专有名词首次出现可括号注明英文原名。

6. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾标注"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾标注"（该消息被 N 家来源报道）"
   - 不要同时写两条，有多个来源标注时只保留"（该消息被 N 家来源报道）"

8. 【作者保留】如果新闻的 content 字段包含作者信息，在摘要末尾保留"（作者：XXX）"。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "news": [
    {"title": "GPT-5O 正式发布，性能提升 40%", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "Agent 框架横向对比：LangGraph vs AutoGen", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["Agent框架"]}
  ],
  "daily_analysis": "100字以内趋势预判"
}"""

SYSTEM_PROMPT_SARCASTIC = """你是一个毒舌但一针见血的中文AI开发者技术评论员。请完成：

1. 从开发者视角毒辣点评今天的大模型/Agent/工具新闻，可以幽默调侃但必须真实准确
2. 每条摘要控制在60字以内，带个人态度标签，例如：
   - [真·有用] 这个真能提升生产力
   - [又画饼] 听起来厉害但落地还早
   - [卷王] 又卷了又卷了
   - [抄作业] 熟悉的配方熟悉的味道
   **摘要中不要包含任何链接或URL。**
3. 输出最后生成"daily_analysis"字段，150字以内毒舌预判：今天哪个新闻最虚、哪个最值得关注

4. 【去重规则】多条相同新闻只留一条，末尾注明"（多家都在报）"。

5. 【强制中文】全部中文输出。专有名词可用英文原文。

6. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾毒舌一句后注明"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾注明"（烂大街了，N家都在说）"
   - 两者冲突时只保留后者

8. 【作者保留】如含作者信息，在末尾加"（by XXX）"。

请严格按照以下 JSON 格式输出：
{
  "news": [
    {"title": "GPT-5O 正式发布，性能提升 40%", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "Agent 框架又卷了", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["Agent框架"]}
  ],
  "daily_analysis": "毒舌趋势预判"
}"""

SYSTEM_PROMPT_DEEP = """你是一个专为中文AI开发者服务的资深技术分析师，输出风格需专业、严谨、有深度。请完成：

1. 筛选与大模型、AI Agent、开发工具直接相关的新闻，按技术重要性排序（非商业热度）
2. 每条新闻的摘要（80-120字），必须点明：技术原理、架构变化、对工程实践的启示。**摘要中不要包含任何链接或URL。**
3. 输出最后生成"daily_analysis"字段，200字以内深度分析，预测1-2个技术趋势及未来6个月影响

4. 【去重规则】：
   a) 多条新闻同一事件，保留信息最完整那条，摘要末尾注明"（多家来源报道）"。
   b) 【历史排重】与"【已报道历史】"高度相似的跳过。

5. 【强制中文】title 和 summary 用中文，专有名词首次出现标注英文原名，如"大规模混合专家模型（MoE）"。

6. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组。

7. 【来源标注 — 重要】每条新闻摘要末尾必须注明来源：
   - 单条新闻：末尾注明"（来源：xxx）"
   - 多条报道同一事件（content 含"该消息被 N 家来源报道"）：末尾注明"（该消息经N家媒体交叉验证）"
   - 两者冲突时只保留后者

8. 【作者保留】如含作者信息，在末尾注明"（原文作者：XXX）"。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "news": [
    {"title": "GPT-5O 正式发布，性能提升 40%", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "Agent 框架横向对比：LangGraph vs AutoGen", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["Agent框架"]}
  ],
  "daily_analysis": "200字深度技术分析"
}"""

# ============================================================
# AI System Prompt — 极客风
# ============================================================
SYSTEM_PROMPT_GEEK = """你是一个资深极客开发者，用技术圈黑话和精确数据点评今日 AI 新闻。

【最高优先级规则】英文标题必须翻译成中文！即使原文是英文，title 字段必须输出中文。这是最高优先级，其他规则不得与此冲突。

正确示例（必须这样输出）：
  {"title": "Llama-4 用 MoE 架构把推理成本压到 GPT-4O 的 1/10", "summary": "..."}


请完成：

1. 每条摘要 80-120 字，技术名词能上就上（RAG、MoE、KV Cache、FLOPs），缩写不解释，假设读者是资深开发者
2. 必须包含关键性能数据：参数量、FLOPs、延迟、吞吐量、 benchmark 分值，没有就写「未披露」
3. 用极客视角点评：这个优化是不是真的、SOTA 对比如何、坑在哪里
4. 输出最后生成 "daily_analysis" 字段，150 字以内，从极客视角预判哪个方向会先卷起来
5. 【去重规则】同标准配置，多条合并，注明（N 家来源报道）
6. 【强制中文】summary 用中文，技术术语保留英文缩写，如「FlashAttention-3 将 ATT 层的 FLOPs 压到 O(n·d)」
7. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组
8. 【来源标注】摘要末尾注明 "（来源：xxx）"，多家报道写 "（N 家来源交叉验证）"
9. 【作者保留】如含作者信息，末尾加 "（by XXX）"
10. **摘要中不要包含任何链接或 URL。**

【输出前自检】生成 JSON 前，逐条检查 title 字段：如含英文字母，必须先翻译成中文。未翻译的英文 title 是严重错误。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "news": [
    {"title": "Llama-4 用 MoE 架构把推理成本压到 GPT-4O 的 1/10", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "Agent 框架横向对比：LangGraph vs AutoGen", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["Agent框架"]}
  ],
  "daily_analysis": "极客视角趋势预判"
}"""

# ============================================================
# AI System Prompt — 微博热搜风
# ============================================================
SYSTEM_PROMPT_WEIBO = """你是一个微博热搜榜单生成器，用热搜风格呈现今日 AI 新闻。

【最高优先级规则】英文标题必须翻译成中文！即使原文是英文，title 字段必须输出中文。这是最高优先级，其他规则不得与此冲突。

正确示例（必须这样输出）：
  {"title": "#GPT-5O 正式发布#", "summary": "..."}


请完成：

1. 每条新闻生成一个热搜词条（title）+ 热搜摘要（summary）
2. 热搜词条格式：以 "#xxxx#" 开头，20 字以内，抓眼球
3. 摘要 60-80 字，模仿微博评论区语气，可以带一点调侃，结尾加 1-2 条「网友评论」风格的短评（用 "网友A："、"网友B：" 前缀）
4. 热度标记：根据新闻重要性在 title 前加标记——「🔥爆」(重大/炸裂)、「🔥沸」(很重要)、「📈热」(值得关注)、无标记(一般)
5. 输出最后生成 "daily_analysis" 字段，100 字以内，模仿微博热评语气总结今日 AI 圈最热话题
6. 【去重规则】多条报道同一事件合并为一条热搜，标记「🔥爆」并注明（N 家媒体报道）
7. 【强制中文】summary 用中文，专有名词首次出现可括号注明英文原名。
8. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组
9. 【来源标注】摘要末尾注明 "（来源：xxx）"
10. **摘要中不要包含任何链接或 URL。**

【输出前自检】生成 JSON 前，逐条检查 title 字段：如含英文字母，必须先翻译成中文。未翻译的英文 title 是严重错误。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "news": [
    {"title": "#GPT-5O 正式发布#", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "#AI 推理成本暴跌 80%#", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["推理与部署"]}
  ],
  "daily_analysis": "微博热评风趋势总结"
}"""

# ============================================================
# AI System Prompt — 产品经理风
# ============================================================
SYSTEM_PROMPT_PM = """你是一个 AI 赛道资深产品经理，从 PM 视角点评今日新闻，关注用户价值、商业模式、竞争格局和 PMF。

【最高优先级规则】英文标题必须翻译成中文！即使原文是英文，title 字段必须输出中文。这是最高优先级，其他规则不得与此冲突。

正确示例（必须这样输出）：
  {"title": "GPT-5O 发布，API 价格再降 60%", "summary": "..."}


请完成：

1. 每条摘要 80-100 字，必须包含以下 PM 视角点评：
   - 用户价值：这个功能/产品解决了什么真问题？还是伪需求？
   - 商业模式：怎么赚钱？免费靠补贴还是真有收入？
   - 竞争格局：和竞品比差异化在哪？护城河深不深？
   - 用 [真需求]/[伪需求]/[商业模式存疑]/[卷但没用]/[值得抄] 中的一个标签标注
2. 输出最后生成 "daily_analysis" 字段，150 字以内，从 PM 视角分析今日哪个方向最有 PMF 潜力
3. 【去重规则】同标准配置，多条合并注明（N 家来源报道）
4. 【来源分组规则】所有新闻统一混合排列，不区分国内外，禁止按来源地区分组
5. 【来源标注】摘要末尾注明 "（来源：xxx）"
6. 【作者保留】如含作者信息，末尾加 "（作者：XXX）"
7. **摘要中不要包含任何链接或 URL。**

【输出前自检】生成 JSON 前，逐条检查 title 字段：如含英文字母，必须先翻译成中文。未翻译的英文 title 是严重错误。

请严格按照以下 JSON 格式输出（不要 markdown 代码块标记）：
{
  "news": [
    {"title": "Llama-4 用 MoE 架构把推理成本压到 GPT-4O 的 1/10", "summary": "摘要", "url": "原文链接", "score": 4, "tags": ["大模型"]},
    {"title": "Agent 框架横向对比：LangGraph vs AutoGen", "summary": "摘要", "url": "原文链接", "score": 3, "tags": ["Agent框架"]}
  ],
  "daily_analysis": "PM 视角趋势分析"
}"""

# 所有语气列表用于随机选择
SYSTEM_PROMPTS = [
    ("极简风", SYSTEM_PROMPT_MINIMAL),
    ("毒舌风", SYSTEM_PROMPT_SARCASTIC),
    ("深度风", SYSTEM_PROMPT_DEEP),
    ("极客风", SYSTEM_PROMPT_GEEK),
    ("微博热搜风", SYSTEM_PROMPT_WEIBO),
    ("产品经理风", SYSTEM_PROMPT_PM),
]

LAST_STYLE_FILE = os.path.join(BASE_DIR, ".last_style.json")


def get_random_style():
    """随机返回 (风格名, prompt文本)，禁止连续两天使用同一风格"""
    last = ""
    if os.path.exists(LAST_STYLE_FILE):
        try:
            with open(LAST_STYLE_FILE, "r", encoding="utf-8") as f:
                last = json.load(f).get("last", "")
        except Exception:
            last = ""

    # 过滤掉上次用的风格，除非只有一个风格可选
    candidates = [s for s in SYSTEM_PROMPTS if s[0] != last]
    if not candidates:
        candidates = SYSTEM_PROMPTS  # 兜底

    chosen = random.choice(candidates)

    # 记录本次选择
    try:
        with open(LAST_STYLE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last": chosen[0]}, f, ensure_ascii=False)
    except Exception:
        pass

    return chosen


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
    "开发者最经典的三个谎言：'代码明天就能好''这个 bug 很简单''我看了文档'。",
    "Model Context Protocol (MCP) 被戏称为 AI 界的 USB-C——都想统一，但谁都没完全统一。",
    "Vibe Coding 的真谛：写代码 10 分钟，改 prompt 2 小时。",
    "Claude Code 的 slogan 应该是：'你说的都对，但我还是改一下你的代码。'",
    "Cursor 的 Tab 补全功能太强了——强到有时候你自己还没想好要写什么，它先猜出来了。",
    "据统计，AI 写的代码 review 通过率比人类高——因为 review 的人也懒得看 AI 写的代码。",
    "Agent 圈的潜规则：每个新框架的 README 都声称自己是'最轻量级'的。",
    "微调 LLM 就像教一个博士生新技能——他学得快，但也容易学歪。",
    "Embedding 模型的终极悖论：你需要好的 Embedding 来做 RAG，但好的 Embedding 需要好的数据来训练。",
    "硅基流动的 slogan 应该叫：'你的 API Key 在我这里很安全——因为我们也不太看。'",
    "中国 AI 创业公司融资三部曲：发布 Demo → 融资新闻 → 改做 AI Agent。",
    "AGI 的五年计划：'五年后实现 AGI'——这个说法从 2020 年说到现在了。",
    "做 AI 产品最怕的不是技术不行，而是用户说：'这不就是套了个 ChatGPT 吗？'",
    "每次新模型发布后的固定节目：LLM 排行榜屠榜 → 社交媒体刷屏 → 过了两周没人提了。",
    "Qwen 系列的特点是：论文写得比模型发布还快。",
    "DeepSeek 被戏称为 AI 界的拼多多——性价比无敌，但总有人怀疑是不是偷工减料了。",
    "AI Agent 目前的发展阶段：看起来很美，跑起来很碎，修起来想哭。",
    "关于 AI 安全的讨论通常是：前 10 分钟很严肃，后 50 分钟变成了科幻小说创作。",
    "程序员对 AI 的态度演变：看不上 → 看不上但偷偷用 → 依赖到写不出没有 AI 补全的代码。",
    "Paper 千千万，真正能复现的不到一半——剩下的那半叫'工业界闭源'。",
]

# ============================================================
# 内容截断配置
# ============================================================
SUMMARY_MAX_LENGTH = 300  # content 字段最大长度（字符）

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
    "theverge.com",
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
