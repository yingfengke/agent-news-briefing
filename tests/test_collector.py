"""测试采集层核心函数"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collect.collector import _detect_lang, _make_id


def test_detect_lang_known_source():
    assert _detect_lang("量子位") == "zh"
    assert _detect_lang("InfoQ中文") == "zh"
    assert _detect_lang("ArXiv AI") == "en"
    assert _detect_lang("OpenAI") == "en"


def test_detect_lang_unknown_source():
    """Unknown source not in RSS config or Chinese names should default to en."""
    result = _detect_lang("UnknownSource")
    assert result == "en"


def test_make_id_consistency():
    """Same URL should produce same ID."""
    id1 = _make_id("https://example.com/article")
    id2 = _make_id("https://example.com/article")
    assert id1 == id2
    assert len(id1) == 16  # SHA256[:16]


def test_make_id_different_urls():
    """Different URLs should produce different IDs."""
    id1 = _make_id("https://example.com/article1")
    id2 = _make_id("https://example.com/article2")
    assert id1 != id2


def test_make_id_empty():
    """Empty URL should still produce a consistent ID."""
    id1 = _make_id("")
    id2 = _make_id("")
    assert id1 == id2


if __name__ == "__main__":
    test_detect_lang_known_source()
    test_detect_lang_unknown_source()
    test_make_id_consistency()
    test_make_id_different_urls()
    test_make_id_empty()
    print("All collector tests passed!")
