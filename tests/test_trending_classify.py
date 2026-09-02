"""trending 分类四层逻辑 + topics 拉取失败降级测试（无 pytest 依赖）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import trending_tags as tt
from src.collect.trending_fetcher import fetch_topics


def test_classify_l1_topics_voting():
    # topics 命中最多者胜出
    tag = tt.classify_repo(["rag", "vector-database", "llm"], "x/y", "")
    assert tag == "RAG 与知识库"


def test_classify_l2_known_repos():
    assert tt.classify_repo([], "langchain-ai/langchain", "") == "Agent 与智能体"
    # 大小写不敏感
    assert tt.classify_repo([], "VLLM-PROJECT/VLLM", "") == "推理与部署"


def test_classify_l3_desc_weighted():
    # 泛词 agent(权重3) 不压过具体词 vllm(权重5)
    tag = tt.classify_repo([], "foo/bar", "vllm is a high-throughput inference engine")
    assert tag == "推理与部署"


def test_classify_l3_fixes_old_typos():
    # 旧拼写 flashattention / llamaindex 已修正
    assert tt.classify_repo([], "foo/bar", "flash-attention v2 implementation") == "大模型与基础研究"
    assert tt.classify_repo([], "foo/bar", "llama_index for rag") == "RAG 与知识库"


def test_classify_cursor_copilot_not_multimodal():
    # 旧 bug：cursor/copilot/claude code 曾被错分「多模态与前沿」
    assert tt.classify_repo([], "foo/cursor", "ai code editor") == "开发工具与编程"
    assert tt.classify_repo([], "foo/bar", "github copilot alternative") == "开发工具与编程"
    assert tt.classify_repo([], "foo/bar", "claude code agent") == "开发工具与编程"


def test_classify_l4_fallback_other():
    assert tt.classify_repo([], "foo/bar", "a random side project") == "其他"


def test_classify_ai_agents_topic_mapping():
    # 2026 热门生态 topic：ai-agents / agent-skills / dsh-plugin 都应归 Agent 与智能体
    # （缺映射曾导致 deepseek-harness 被误分「大模型与基础研究」）
    for topic in ["ai-agents", "ai-agent", "agent-skills", "claude-skills",
                  "coding-agents", "agentic", "dsh-plugin", "dsh", "harness"]:
        tag = tt.classify_repo([topic], "x/y", "")
        assert tag == "Agent 与智能体", f"topic {topic} -> {tag}"


def test_classify_deepseek_harness_known_repo():
    # L2 硬编码：deepseek-harness 是 Agent 运行时框架，不该被 desc 的 "deepseek" 词
    # （权重 4，归大模型）带偏。topics 全空时靠 L2 兜底
    assert tt.classify_repo([], "deepseek-ai/deepseek-harness", "") == "Agent 与智能体"
    # 即使 topics 缺失、desc 含 deepseek 关键词，KNOWN_REPOS 也应在 L2 优先命中
    tag = tt.classify_repo([], "deepseek-ai/deepseek-harness",
                           "DeepSeek Harness: Everything is a Plugin.")
    assert tag == "Agent 与智能体"


def test_classify_deepseek_harness_real_topics():
    # 真实 topics（ai-agents/cordis/dsh/dsh-plugin）走 L1 投票应命中 Agent 与智能体
    tag = tt.classify_repo(["ai-agents", "cordis", "dsh", "dsh-plugin"],
                           "deepseek-ai/deepseek-harness",
                           "DeepSeek Harness: Everything is a Plugin.")
    assert tag == "Agent 与智能体"


def test_relevance_strong_topic_scores_two():
    # Agent 运行时/编码工具/LLM 工程硬信号 → 强相关(2)
    for topic in ["harness", "dsh", "dsh-plugin", "coding-agent", "codex",
                  "mcp", "vllm", "rag", "inference", "fine-tuning"]:
        assert tt.relevance_score([topic], "x/y", "") == 2, topic
    # desc 兜底（topics 空时）
    assert tt.relevance_score([], "x/y", "a coding assistant for agents") == 2


def test_relevance_weak_topic_scores_one():
    # 泛 AI topic → 弱相关(1)
    for topic in ["agents", "ai-agents", "llm", "multi-agent", "nlp", "agent-skills"]:
        assert tt.relevance_score([topic], "x/y", "") == 1, topic
    assert tt.relevance_score([], "x/y", "an llm-powered multi-agent thing") == 1


def test_relevance_unrelated_scores_zero():
    # 非关注域（但可能仍是 AI，如多模态/图像）→ 0，热度补位
    assert tt.relevance_score(["text-to-image", "vision"], "x/y", "") == 0
    assert tt.relevance_score([], "x/y", "gpt-image-2 prompt templates") == 0


def test_fetch_topics_fails_soft():
    """网络异常应返回空列表而非抛出，交由下层兜底。"""
    import urllib.request
    import urllib.error
    orig = urllib.request.urlopen

    def _boom(*a, **k):
        raise urllib.error.URLError("network down")

    urllib.request.urlopen = _boom
    try:
        assert fetch_topics("a", "b", {}) == []
    finally:
        urllib.request.urlopen = orig
