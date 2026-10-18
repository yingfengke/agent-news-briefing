"""同事件实体归一化与正文配额测试。"""
from src.analysis import summarize as S
from src.core.entities import extract_event_keys, primary_key


def _item(title, score, category="大模型"):
    return {"title": title, "score": score, "category": category,
            "summary": f"{title}的摘要", "link": "https://e.com/x"}


def test_event_keys_normalize_spacing_and_hyphen():
    """同一型号的不同写法必须归一化到同一个键。"""
    variants = [
        "DeepSeek V4.1-Flash-1017 发布",
        "DeepSeek V4.1 Flash 1017 成本下降",
        "DeepSeek v4.1_flash_1017 上线",
    ]
    keys = [primary_key(t) for t in variants]
    assert keys[0] == keys[1] == keys[2] == "v4.1flash1017"


def test_event_keys_handles_hyphenated_models():
    assert primary_key("Llama-4 用 MoE 架构降本") == "llama4"
    assert primary_key("GPT-5.2 发布，上下文 2M") == "gpt5.2"


def test_event_keys_ignores_generic_titles():
    assert extract_event_keys("OpenAI 调整 API 定价") == set()
    assert extract_event_keys("2026 年 AI 融资总额创新高") == set()


def test_entity_quota_moves_excess_to_briefs():
    """同型号第三条不占正文名额，转入简讯；不删除内容。"""
    items = [
        _item("DeepSeek 发布 V4.1-Flash-1017，得分 77.0", 4.2),
        _item("DeepSeek V4.1 Flash 1017 成本大幅下降", 4.1),
        _item("DeepSeek V4.1 Flash 1017 上线 Vercel", 3.1),
    ]
    display, rest = S.apply_entity_quota(items, [], limit=2)
    assert len(display) == 2
    assert [it["title"] for it in rest] == ["DeepSeek V4.1 Flash 1017 上线 Vercel"]


def test_entity_quota_backfills_from_rest():
    """移出后从待展示区补入其他条目，正文数量保持不变。"""
    display = [_item(f"DeepSeek V4.1 Flash 1017 报道{i}", 4.0 - i * 0.1) for i in range(3)]
    display += [_item(f"其他新闻{i}", 3.0 - i * 0.1) for i in range(2)]
    rest = [_item("备选新闻A", 2.5), _item("备选新闻B", 2.4)]

    kept, rest_out = S.apply_entity_quota(display, rest, limit=2)

    assert len(kept) == len(display)
    assert sum(1 for it in kept if "V4.1" in it["title"]) == 2
    assert "备选新闻A" in [it["title"] for it in kept]
    assert "DeepSeek V4.1 Flash 1017 报道2" in [it["title"] for it in rest_out]


def test_entity_quota_ignores_titles_without_model():
    """没有型号标识的标题不参与配额，避免把泛新闻误判为同一事件。"""
    items = [_item("OpenAI 调整定价", 4.0), _item("Google 发布新模型", 3.9),
             _item("Meta 开源新框架", 3.8)]
    display, rest = S.apply_entity_quota(items, [], limit=1)
    assert len(display) == 3 and rest == []


def test_entity_quota_counts_models_separately():
    """不同型号各自计数，互不影响。"""
    items = [_item("Llama-4 发布", 4.0), _item("Llama-4 性能实测", 3.9),
             _item("GPT-5.2 发布", 3.8), _item("GPT-5.2 定价", 3.7)]
    display, rest = S.apply_entity_quota(items, [], limit=1)
    assert len(display) == 2
    assert {primary_key(it["title"]) for it in display} == {"llama4", "gpt5.2"}
