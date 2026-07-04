"""测试 HTML 写入层核心函数"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.html_writer import clean_links


def test_clean_links_empty():
    assert clean_links("") == ""
    assert clean_links(None) is None


def test_clean_links_no_links():
    text = "这是一条普通文本，没有链接。"
    assert clean_links(text) == text


def test_clean_links_markdown_link():
    result = clean_links("[OpenAI](https://openai.com)")
    assert '<a href="https://openai.com" target="_blank">OpenAI</a>' in result


def test_clean_links_bare_url():
    result = clean_links("访问 https://example.com 了解更多")
    assert '<a href="https://example.com" target="_blank">' in result


def test_clean_links_multiple():
    result = clean_links("[A](https://a.com) and [B](https://b.org)")
    assert 'href="https://a.com"' in result
    assert 'href="https://b.org"' in result


def test_clean_links_url_with_path():
    result = clean_links("见 https://github.com/user/repo/issues/1")
    assert 'href="https://github.com/user/repo/issues/1"' in result


def test_clean_links_no_double_wrap():
    """Already wrapped <a> tags should not be double-wrapped."""
    text = '<a href="https://example.com">link</a>'
    result = clean_links(text)
    # Should not have nested <a> tags
    assert result.count('<a ') == 1


if __name__ == "__main__":
    test_clean_links_empty()
    test_clean_links_no_links()
    test_clean_links_markdown_link()
    test_clean_links_bare_url()
    test_clean_links_multiple()
    test_clean_links_url_with_path()
    test_clean_links_no_double_wrap()
    print("All html_writer tests passed!")
