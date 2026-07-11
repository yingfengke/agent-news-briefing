"""
trending_tags.py — GitHub Trending 项目分类配置

分类采用四层（无需模型、无第三方依赖）：
  L1  GitHub topics 投票（结构化、开发者自打标签，优先）
  L2  知名仓库硬编码（topics 缺失时兜底）
  L3  description 加权关键词（按词特异性排序，非 first-match）
  L4  兜底「其他」（不丢弃、不硬塞 Agent 框架）

说明：TOPIC_TO_CATEGORY / KNOWN_REPOS / DESC_KEYWORD_WEIGHTS 仍是静态表，
只是维护频率远低于原始「description 子串匹配」方案——topic 词汇演化更慢、更规范。
新出现的 topic 或知名仓库仍需手工补一行，但误伤大幅减少，且不再依赖易过时的词表。
"""

# 项目分类枚举（展示顺序；「其他」兜底）
PROJECT_CATEGORY_ORDER = [
    "大模型与基础研究",
    "Agent 与智能体",
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
    # Agent 与智能体
    "agent": "Agent 与智能体",
    "agents": "Agent 与智能体",
    "multi-agent": "Agent 与智能体",
    "autonomous-agent": "Agent 与智能体",
    "agent-framework": "Agent 与智能体",
    "mcp": "Agent 与智能体",
    "model-context-protocol": "Agent 与智能体",
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
    "comfyanonymous/comfyui": "多模态",
    "modelscope/ms-swift": "微调与训练",
    "modelscope/modelscope": "大模型与基础研究",
    "anthropics/claude-code": "开发工具与编程",
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


def classify_repo(topics, full_name, desc):
    """四层分类：返回项目所属分类字符串（必为 PROJECT_CATEGORY_ORDER 之一）。

    L1  GitHub topics 投票（命中 TOPIC_TO_CATEGORY 最多的分类胜出）
    L2  知名仓库硬编码（topics 缺失/为空时兜底）
    L3  description 加权关键词（按词特异性排序，非 first-match）
    L4  兜底「其他」（不丢弃、不硬塞 Agent 框架）
    """
    # L1
    votes = {}
    for t in (topics or []):
        cat = TOPIC_TO_CATEGORY.get((t or "").lower())
        if cat:
            votes[cat] = votes.get(cat, 0) + 1
    if votes:
        return max(votes, key=votes.get)

    # L2
    fn = (full_name or "").lower()
    if fn in KNOWN_REPOS:
        return KNOWN_REPOS[fn]

    # L3
    combined = f"{(full_name or '')} {(desc or '')}".lower()
    best_cat, best_w = None, 0
    for kw, (cat, w) in DESC_KEYWORD_WEIGHTS.items():
        if kw in combined and w > best_w:
            best_cat, best_w = cat, w
    if best_cat:
        return best_cat

    # L4
    return "其他"
