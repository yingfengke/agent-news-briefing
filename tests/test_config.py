"""测试配置模块"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config


def test_config_has_required_exports():
    assert hasattr(config, 'API_BASE_URL')
    assert hasattr(config, 'API_KEY')
    assert hasattr(config, 'MODEL_NAME')
    assert hasattr(config, 'RSS_SOURCES')
    assert hasattr(config, 'SYSTEM_PROMPTS')
    assert hasattr(config, 'AI_TRIVIA')
    assert hasattr(config, 'TRENDING_TAG_MAP')
    assert hasattr(config, 'CREDIBILITY_WHITELIST')
    assert hasattr(config, 'CREDIBILITY_BLACKLIST')


def test_rss_sources_count():
    assert len(config.RSS_SOURCES) > 20


def test_system_prompts_count():
    assert len(config.SYSTEM_PROMPTS) == 6


def test_get_random_style():
    name, prompt = config.get_random_style()
    assert name in [s[0] for s in config.SYSTEM_PROMPTS]
    assert len(prompt) > 100


def test_get_random_trivia():
    trivia = config.get_random_trivia()
    assert len(trivia) > 10
    assert trivia in config.AI_TRIVIA


def test_ai_trivia_count():
    assert len(config.AI_TRIVIA) == 40


def test_trending_tags_count():
    assert len(config.TRENDING_TAG_MAP) > 50


def test_base_dir():
    assert os.path.isdir(config.BASE_DIR)
    assert os.path.exists(os.path.join(config.BASE_DIR, "src"))


def test_category_order_is_six_class_enum():
    """分类体系已收敛为固定 6 类枚举（P1-3 / D1）。"""
    from src.config.sources import CATEGORY_ORDER
    assert CATEGORY_ORDER == [
        "大模型", "Agent框架", "产品与发布", "论文与研究", "行业动态", "其他动态"
    ]


def test_prompt_enum_matches_category_order():
    """AI 输出约束的类别枚举必须与 CATEGORY_ORDER 完全一致（D1）。"""
    from src.config.sources import CATEGORY_ORDER
    from src.config.prompts import SYSTEM_PROMPTS
    enum_text = SYSTEM_PROMPTS[0][1]
    for cat in CATEGORY_ORDER:
        assert cat in enum_text, f"prompt 中缺少类别枚举: {cat}"


if __name__ == "__main__":
    import os
    test_config_has_required_exports()
    test_rss_sources_count()
    test_system_prompts_count()
    test_get_random_style()
    test_get_random_trivia()
    test_ai_trivia_count()
    test_trending_tags_count()
    test_base_dir()
    test_category_order_is_six_class_enum()
    test_prompt_enum_matches_category_order()
    print("All config tests passed!")
