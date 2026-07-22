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
