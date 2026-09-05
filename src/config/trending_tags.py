"""
trending_tags.py — GitHub Trending 项目分类配置

分类采用四层（无需模型、无第三方依赖）：
  L1  知名仓库硬编码（人工确认的黄金标准，最高优先）
  L2  GitHub topics 投票（结构化、开发者自打标签；平票按分类枚举顺序稳定裁决）
  L3  description 加权关键词（词边界匹配防子串误伤；平局同样按枚举顺序稳定）
  L4  兜底「其他」（不丢弃、不硬塞 Agent 框架）

说明：TOPIC_TO_CATEGORY / KNOWN_REPOS / DESC_KEYWORD_WEIGHTS 仍是静态表，
只是维护频率远低于原始「description 子串匹配」方案——topic 词汇演化更慢、更规范。
新出现的 topic 或知名仓库仍需手工补一行，但误伤大幅减少，且不再依赖易过时的词表。
"""

import re

# 项目分类枚举（展示顺序；「其他」兜底）。
# 2026-09 按行业目录惯例扩至 11 类：Skills 已是跨 Agent 的开放标准赛道
# （agentskills.io 规范、Vercel skills.sh / AgentSkills.codes 等目录均独立成类），
# MCP 同理（已捐入 Linux Foundation，servers 生态 270+）。
PROJECT_CATEGORY_ORDER = [
    "大模型与基础研究",
    "Agent 与智能体",
    "Agent 技能包",
    "MCP 与工具协议",
    "RAG 与知识库",
    "推理与部署",
    "微调与训练",
    "开发工具与编程",
    "多模态",
    "安全与评测",
    "其他",
]

# L1: GitHub topics -> 分类（键小写；topics 端点返回即为小写）
TOPIC_TO_CATEGORY = {
    # Agent 与智能体（运行时/框架/编排/浏览器 agent/记忆）
    # Agent 技能包（SKILL.md 开放标准生态）、MCP 与工具协议（连接与互操作标准）
    "agent": "Agent 与智能体",
    "agents": "Agent 与智能体",
    "ai-agent": "Agent 与智能体",
    "ai-agents": "Agent 与智能体",
    "multi-agent": "Agent 与智能体",
    "autonomous-agent": "Agent 与智能体",
    "autonomous-agents": "Agent 与智能体",
    "agent-framework": "Agent 与智能体",
    "agent-orchestration": "Agent 与智能体",
    "agent-orchestrators": "Agent 与智能体",
    "agent-workflow": "Agent 与智能体",
    "agentic-workflow": "Agent 与智能体",
    "agentic-ai": "Agent 与智能体",
    "agent-skills": "Agent 技能包",
    "agentic-skills": "Agent 技能包",
    "claude-skills": "Agent 技能包",
    "coding-agents": "Agent 与智能体",
    "agentic": "Agent 与智能体",
    "dsh": "Agent 与智能体",
    "dsh-plugin": "Agent 与智能体",
    "mcp": "MCP 与工具协议",
    "mcp-server": "MCP 与工具协议",
    "mcp-servers": "MCP 与工具协议",
    "mcp-client": "MCP 与工具协议",
    "model-context-protocol": "MCP 与工具协议",
    "skills": "Agent 技能包",
    "skills-as-code": "Agent 技能包",
    "skill-framework": "Agent 技能包",
    "skill-creator": "Agent 技能包",
    "superpowers": "Agent 技能包",
    "browser-use": "Agent 与智能体",
    "browser-agent": "Agent 与智能体",
    "computer-use": "Agent 与智能体",
    "web-agent": "Agent 与智能体",
    "agentic-memory": "Agent 与智能体",
    "agent-memory": "Agent 与智能体",
    "a2a": "MCP 与工具协议",
    "agent-protocol": "MCP 与工具协议",
    "agent-to-agent": "MCP 与工具协议",
    "swarm": "Agent 与智能体",
    "agents-sdk": "Agent 与智能体",
    "openai-agents": "Agent 与智能体",
    "agent-evals": "Agent 与智能体",
    "openclaw": "Agent 与智能体",
    "tool-use": "Agent 与智能体",
    "function-calling": "Agent 与智能体",
    # 大模型与基础研究
    "llm": "大模型与基础研究",
    "llms": "大模型与基础研究",
    "large-language-models": "大模型与基础研究",
    "transformer": "大模型与基础研究",
    "foundation-model": "大模型与基础研究",
    "language-model": "大模型与基础研究",
    "nlp": "大模型与基础研究",
    # RAG 与知识库
    "rag": "RAG 与知识库",
    "retrieval-augmented-generation": "RAG 与知识库",
    "retrieval": "RAG 与知识库",
    "vector-database": "RAG 与知识库",
    "embedding": "RAG 与知识库",
    "knowledge-graph": "RAG 与知识库",
    "semantic-search": "RAG 与知识库",
    # 推理与部署
    "inference": "推理与部署",
    "inference-engine": "推理与部署",
    "llm-serving": "推理与部署",
    "model-serving": "推理与部署",
    "quantization": "推理与部署",
    "onnx": "推理与部署",
    "tensorrt": "推理与部署",
    "trt-llm": "推理与部署",
    # 微调与训练
    "fine-tuning": "微调与训练",
    "lora": "微调与训练",
    "qlora": "微调与训练",
    "rlhf": "微调与训练",
    "dpo": "微调与训练",
    "distributed-training": "微调与训练",
    "pretraining": "微调与训练",
    # 开发工具与编程
    "coding-assistant": "开发工具与编程",
    "code-generation": "开发工具与编程",
    "copilot": "开发工具与编程",
    "developer-tools": "开发工具与编程",
    "cli": "开发工具与编程",
    "sdk": "开发工具与编程",
    "ide": "开发工具与编程",
    "lsp": "开发工具与编程",
    "prompt-engineering": "开发工具与编程",
    # 多模态
    "multimodal": "多模态",
    "text-to-image": "多模态",
    "text-to-video": "多模态",
    "text-to-speech": "多模态",
    "speech-recognition": "多模态",
    "vision": "多模态",
    "vlm": "多模态",
    "image-generation": "多模态",
    # 安全与评测
    "alignment": "安全与评测",
    "safety": "安全与评测",
    "guardrails": "安全与评测",
    "red-teaming": "安全与评测",
    "evaluation": "安全与评测",
    "benchmark": "安全与评测",
    "responsible-ai": "安全与评测",
}

# L2: 知名仓库硬编码（键小写 full_name；topics 缺失/为空时兜底）
KNOWN_REPOS = {
    "vllm-project/vllm": "推理与部署",
    "ggml-org/llama.cpp": "推理与部署",
    "ggerganov/llama.cpp": "推理与部署",
    "turboderp/exllamav2": "推理与部署",
    "huggingface/transformers": "大模型与基础研究",
    "huggingface/peft": "微调与训练",
    "huggingface/huggingface_hub": "大模型与基础研究",
    "meta-llama/llama": "大模型与基础研究",
    "meta-llama/llama3": "大模型与基础研究",
    "meta-llama/llama-models": "大模型与基础研究",
    "deepseek-ai/deepseek-v3": "大模型与基础研究",
    "deepseek-ai/deepseek-r1": "大模型与基础研究",
    "langchain-ai/langchain": "Agent 与智能体",
    "langchain-ai/langgraph": "Agent 与智能体",
    "run-llama/llama_index": "RAG 与知识库",
    "microsoft/autogen": "Agent 与智能体",
    "joaomdmoura/crewai": "Agent 与智能体",
    "openai/swarm": "Agent 与智能体",
    "browser-use/browser-use": "Agent 与智能体",
    "deepseek-ai/deepseek-harness": "Agent 与智能体",
    "openclaw/openclaw": "Agent 与智能体",
    "obra/superpowers": "Agent 技能包",
    "anthropics/skills": "Agent 技能包",
    "openai/skills": "Agent 技能包",
    "significant-gravitas/autogpt": "Agent 与智能体",
    "agno-agi/agno": "Agent 与智能体",
    "huggingface/smolagents": "Agent 与智能体",
    "ag2ai/ag2": "Agent 与智能体",
    "composiohq/composio": "MCP 与工具协议",
    "mem0ai/mem0": "Agent 与智能体",
    "modelcontextprotocol/servers": "MCP 与工具协议",
    "modelcontextprotocol/python-sdk": "MCP 与工具协议",
    "anthropics/claude-code": "开发工具与编程",
    "openai/codex": "开发工具与编程",
    "comfyanonymous/comfyui": "多模态",
    "modelscope/ms-swift": "微调与训练",
    "modelscope/modelscope": "大模型与基础研究",
    "github/copilot": "开发工具与编程",
}

# L3: description 加权关键词（(分类, 权重)；权重越高越具体，优先于泛词）
DESC_KEYWORD_WEIGHTS = {
    # 高权重（具体项目/库名，几乎确定）
    "flash-attention": ("大模型与基础研究", 5),
    "flash_attn": ("大模型与基础研究", 5),
    "llama.cpp": ("推理与部署", 5),
    "llama_index": ("RAG 与知识库", 5),
    "llama-index": ("RAG 与知识库", 5),
    "langchain": ("Agent 与智能体", 5),
    "langgraph": ("Agent 与智能体", 5),
    "autogen": ("Agent 与智能体", 5),
    "crewai": ("Agent 与智能体", 5),
    "metagpt": ("Agent 与智能体", 5),
    "dify": ("Agent 与智能体", 5),
    "auto-gpt": ("Agent 与智能体", 5),
    "claude skills": ("Agent 技能包", 5),
    "agent skills": ("Agent 技能包", 5),
    "everything is a plugin": ("Agent 与智能体", 5),
    "vllm": ("推理与部署", 5),
    "ollama": ("推理与部署", 5),
    "lmdeploy": ("推理与部署", 5),
    "comfyui": ("多模态", 5),
    # 中权重（技术词，较具体）
    "deepseek": ("大模型与基础研究", 4),
    "qwen": ("大模型与基础研究", 4),
    "llama": ("大模型与基础研究", 4),
    "transformer": ("大模型与基础研究", 4),
    "moe": ("大模型与基础研究", 4),
    "attention": ("大模型与基础研究", 4),
    "lora": ("微调与训练", 4),
    "qlora": ("微调与训练", 4),
    "unsloth": ("微调与训练", 4),
    "axolotl": ("微调与训练", 4),
    "llama-factory": ("微调与训练", 4),
    "fine-tuning": ("微调与训练", 4),
    "rag": ("RAG 与知识库", 4),
    "chroma": ("RAG 与知识库", 4),
    "milvus": ("RAG 与知识库", 4),
    "haystack": ("RAG 与知识库", 4),
    "retrieval": ("RAG 与知识库", 4),
    "gptq": ("推理与部署", 4),
    "awq": ("推理与部署", 4),
    "inference": ("推理与部署", 4),
    "multimodal": ("多模态", 4),
    "vlm": ("多模态", 4),
    "vision": ("多模态", 4),
    "copilot": ("开发工具与编程", 4),
    "cursor": ("开发工具与编程", 4),
    "claude code": ("开发工具与编程", 4),
    "code-generation": ("开发工具与编程", 4),
    "mcp": ("Agent 与智能体", 4),
    "guardrails": ("安全与评测", 4),
    "evaluation": ("安全与评测", 4),
    "alignment": ("安全与评测", 4),
    # 低权重（泛词，仅当 L1/L2 均未中才轮到）
    "agent": ("Agent 与智能体", 3),
    "coding": ("开发工具与编程", 3),
    "llm": ("大模型与基础研究", 3),
}


# L3 匹配前需从文本中剔除的复合短语（词边界无法处理的误伤：
# "user-agent" 中的 "agent" 会被连字符后的词边界放过）
_L3_EXCLUDE_PHRASES = ("user-agent",)


def _kw_hit(kw, text):
    """关键词词边界匹配，防子串误伤（rag 不再命中 fragile/draggable，
    vision 不再命中 television，mcp 不再命中 MCP2515）。
    边界定义为前后紧邻字符不是字母/数字（下划线视为词内字符，
    使 llama_index 可命中 my_llama_index）。"""
    pattern = r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])'
    return re.search(pattern, text) is not None


def classify_repo(topics, full_name, desc):
    """四层分类：返回项目所属分类字符串（必为 PROJECT_CATEGORY_ORDER 之一）。

    L1  知名仓库硬编码（人工确认的黄金标准，最高优先——topics 会有历史遗留
        或宽泛词，不能反过来覆盖人工结论）
    L2  GitHub topics 投票（平票时按 PROJECT_CATEGORY_ORDER 顺序稳定裁决，
        不依赖 topics 的遍历顺序）
    L3  description 加权关键词（词边界匹配；平局同样按枚举顺序稳定）
    L4  兜底「其他」（不丢弃、不硬塞 Agent 框架）
    """
    order = {c: i for i, c in enumerate(PROJECT_CATEGORY_ORDER)}

    # L1
    fn = (full_name or "").lower()
    if fn in KNOWN_REPOS:
        return KNOWN_REPOS[fn]

    # L2
    votes = {}
    for t in (topics or []):
        cat = TOPIC_TO_CATEGORY.get((t or "").lower())
        if cat:
            votes[cat] = votes.get(cat, 0) + 1
    if votes:
        top = max(votes.values())
        return min((c for c, v in votes.items() if v == top),
                   key=lambda c: order[c])

    # L3
    combined = f"{(full_name or '')} {(desc or '')}".lower()
    for phrase in _L3_EXCLUDE_PHRASES:
        combined = combined.replace(phrase, " ")
    best_cat, best_key = None, None
    for kw, (cat, w) in DESC_KEYWORD_WEIGHTS.items():
        if _kw_hit(kw, combined):
            key = (-w, order[cat])
            if best_key is None or key < best_key:
                best_cat, best_key = cat, key
    if best_cat:
        return best_cat

    # L4
    return "其他"


# ============================================================
# 领域相关度排序（relevance_score）
# 推荐按「匹配度优先、热度次之」排序。匹配度三档：
#   2=强相关（Agent 生态：运行时/框架/编排/MCP/Skills/浏览器与操作 agent/
#            编码 agent/记忆/协议。LLM 工程、RAG 等通用方向【不算】强相关）
#   1=弱相关（泛 AI）
#   0=泛 AI（仅热度补位）
# 调整推荐口径只需增删下方信号表。
# ============================================================
# 强相关 topics：命中即 relevance=2（仅 Agent 生态硬信号）
INTEREST_STRONG_TOPICS = {
    # Agent 运行时 / 框架 / 平台
    "dsh", "dsh-plugin", "agent-runtime", "agent-framework",
    "agent-platform", "agent-sdk", "agentic", "agentic-ai", "swarm",
    "agents-sdk", "openai-agents", "autonomous-agents",
    # Agent 编排 / 工作流
    "agent-orchestration", "agent-orchestrators",
    "agent-workflow", "agentic-workflow",
    # MCP 生态
    "mcp", "model-context-protocol", "mcp-server", "mcp-servers", "mcp-client",
    # Agent Skills / 能力包
    "skills", "agent-skills", "claude-skills", "agentic-skills",
    "skills-as-code", "superpowers",
    # 浏览器 / 计算机操作 agent
    "browser-use", "browser-agent", "computer-use", "web-agent",
    # Agent 记忆 / 工具 / 协议
    "agent-memory", "agentic-memory", "a2a", "agent-protocol",
    "agent-to-agent", "tool-use", "tool-calling", "function-calling",
    "code-interpreter", "openclaw",
    # 编码 agent（AI 编码方向核心词；通用开发工具词归弱相关）
    "coding-agent", "coding-agents", "coding-assistant", "ai-coding",
    "code-generation", "codex", "claude-code", "copilot",
}
# 弱相关 topics：命中即 relevance=1（泛 AI，相关但非 Agent 生态核心）
INTEREST_WEAK_TOPICS = {
    "agent", "agents", "ai-agent", "ai-agents", "multi-agent",
    "autonomous-agent", "agent-evals", "harness", "orchestration",
    "workflow-automation", "developer-tools", "ide", "lsp",
    # LLM 工程（推理/部署/微调）——相关但非 Agent 生态
    "llm", "llms", "large-language-models", "language-model",
    "foundation-model", "transformer", "nlp",
    "inference", "inference-engine", "llm-serving", "model-serving",
    "vllm", "quantization", "fine-tuning", "lora", "unsloth",
    "rlhf", "dpo", "distributed-training", "pretraining",
    "onnx", "tensorrt", "trt-llm",
    # RAG / 检索 / 向量——相关但非 Agent 生态
    "rag", "retrieval-augmented-generation", "vector-database", "embedding",
    "retrieval", "semantic-search", "knowledge-graph",
    "evaluation", "benchmark", "evals", "alignment", "guardrails",
}
# desc 关键词兜底（topics 缺失/为空时生效；小写子串匹配）
INTEREST_DESC_STRONG = (
    "coding assistant", "coding agent", "ai coding", "code assistant",
    "claude code", "agent framework", "agent runtime", "mcp server",
    "agent orchestration", "multi-agent orchestration", "agentic skills",
    "computer use", "agent memory",
    "agent workflow", "agent platform", "orchestration framework",
)
INTEREST_DESC_WEAK = (
    "multi-agent", "agentic", "llm", "large language model", "rag",
    "fine-tuning", "inference", "vector database",
)


def relevance_score(topics, full_name, desc) -> int:
    """领域相关度打分：0=泛 AI（热度补位用）/ 1=弱相关 / 2=强相关。

    只看 topics 与 name/desc 文本，不依赖分类结果
    （分类是「这是什么」，相关度是「是否属于简报侧重方向」）。
    """
    tl = [(t or "").lower() for t in (topics or [])]
    if any(t in INTEREST_STRONG_TOPICS for t in tl):
        return 2
    low_text = f"{(full_name or '')} {(desc or '')}".lower()
    if any(kw in low_text for kw in INTEREST_DESC_STRONG):
        return 2
    if any(t in INTEREST_WEAK_TOPICS for t in tl):
        return 1
    if any(kw in low_text for kw in INTEREST_DESC_WEAK):
        return 1
    return 0
