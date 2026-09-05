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
    # 注：harness 已从映射表移除（测试工具语境误伤源），由 KNOWN_REPOS 精确兜底
    for topic in ["ai-agents", "ai-agent", "coding-agents", "agentic",
                  "dsh-plugin", "dsh", "agent-orchestration", "agentic-memory"]:
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
    # Agent 生态硬信号 → 强相关(2)：运行时/编排/MCP/Skills/浏览器 agent/编码 agent
    for topic in ["dsh", "dsh-plugin", "coding-agent", "codex",
                  "mcp", "mcp-server", "agent-orchestration", "agentic-skills",
                  "agent-skills", "claude-skills", "browser-use", "computer-use",
                  "agent-memory", "a2a", "openclaw", "superpowers", "swarm",
                  "function-calling", "skills"]:
        assert tt.relevance_score([topic], "x/y", "") == 2, topic
    # desc 兜底（topics 空时）
    assert tt.relevance_score([], "x/y", "a coding assistant for agents") == 2
    assert tt.relevance_score([], "x/y", "agent orchestration platform") == 2


def test_relevance_llm_engineering_is_weak_not_strong():
    # LLM 工程 / RAG 是相关但非 Agent 生态 → 弱相关(1)。
    # 强相关口径收敛为纯 Agent 生态（此前 vllm/rag/fine-tuning 误占 2 分）
    for topic in ["vllm", "rag", "fine-tuning", "inference", "quantization",
                  "embedding", "lora"]:
        assert tt.relevance_score([topic], "x/y", "") == 1, topic
    # harness / orchestration / 通用开发工具词同样是弱相关（防误伤）
    for topic in ["harness", "orchestration", "developer-tools", "ide"]:
        assert tt.relevance_score([topic], "x/y", "") == 1, topic


def test_relevance_weak_topic_scores_one():
    # 泛 AI topic → 弱相关(1)
    for topic in ["agents", "ai-agents", "llm", "multi-agent", "nlp"]:
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


def test_l1_known_repo_beats_topic_votes():
    """KNOWN_REPOS 是人工确认的黄金标准，不能被 topics 投票覆盖。

    回归锁死：vllm 的 topics=[llm, inference] 平票时，旧逻辑会按 topics
    顺序返回「大模型与基础研究」，覆盖硬编码的「推理与部署」。
    """
    assert tt.classify_repo(["llm", "inference"], "vllm-project/vllm", "") == "推理与部署"
    assert tt.classify_repo(["inference", "llm"], "vllm-project/vllm", "") == "推理与部署"


def test_l1_topic_vote_tie_break_stable():
    """非知名仓库 topics 平票时，结果必须与 topics 顺序无关（按分类枚举序裁决）。"""
    t1 = tt.classify_repo(["llm", "inference"], "foo/bar", "")
    t2 = tt.classify_repo(["inference", "llm"], "foo/bar", "")
    assert t1 == t2 == "大模型与基础研究"  # 平票取枚举序靠前者


def test_l3_word_boundary_no_substring_false_positive():
    """L3 词边界匹配：泛词不得命中子串（rag/fragile、vision/television 等）。"""
    assert tt.classify_repo([], "x/draggable-list", "draggable list component") == "其他"
    assert tt.classify_repo([], "x/outrage", "an outragegenerator") == "其他"
    assert tt.classify_repo([], "x/television-tool", "tv streaming helper") == "其他"
    # 词边界命中仍然有效
    assert tt.classify_repo([], "x/y", "rag pipeline with chroma") == "RAG 与知识库"


def test_l3_user_agent_compound_excluded():
    """user-agent 复合词被预处理剔除，UA 解析库不再误归 Agent。"""
    assert tt.classify_repo([], "x/user-agent-parser",
                            "HTTP user-agent string parser library") == "其他"
    # 正常 agent 语境不受影响
    assert tt.classify_repo([], "x/y", "autonomous agent framework") == "Agent 与智能体"


def test_l3_tie_break_stable_by_category_order():
    """同权重关键词命中不同分类时，按枚举序稳定裁决（deepseek+rag 同 4 分）。"""
    t1 = tt.classify_repo([], "x/y", "deepseek powered rag retrieval system")
    assert t1 == "大模型与基础研究"  # 大模型 枚举序在 RAG 之前，结果确定


def test_classify_skills_category():
    """Skills 已是独立开放标准赛道（SKILL.md 跨 Agent 通用），独立成类。"""
    for topic in ["agent-skills", "claude-skills", "agentic-skills",
                  "skills", "skills-as-code", "superpowers"]:
        tag = tt.classify_repo([topic], "x/y", "")
        assert tag == "Agent 技能包", f"topic {topic} -> {tag}"
    # KNOWN_REPOS 同步
    assert tt.classify_repo([], "anthropics/skills", "") == "Agent 技能包"
    assert tt.classify_repo([], "obra/superpowers", "") == "Agent 技能包"
    # desc 兜底同样归新类
    assert tt.classify_repo([], "x/y", "claude skills for code review") == "Agent 技能包"


def test_classify_mcp_protocol_category():
    """MCP 已捐入 Linux Foundation、servers 生态独立成类；A2A 协议同类。"""
    for topic in ["mcp", "mcp-server", "mcp-servers", "mcp-client",
                  "model-context-protocol", "a2a", "agent-protocol"]:
        tag = tt.classify_repo([topic], "x/y", "")
        assert tag == "MCP 与工具协议", f"topic {topic} -> {tag}"
    # KNOWN_REPOS 同步
    assert tt.classify_repo([], "modelcontextprotocol/servers", "") == "MCP 与工具协议"
    assert tt.classify_repo([], "composiohq/composio", "") == "MCP 与工具协议"
