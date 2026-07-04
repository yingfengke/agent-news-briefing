"""测试数据模型"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import NewsItem, FilterReport


def test_news_item_defaults():
    item = NewsItem(
        id="abc123", title="Test", content="Content",
        url="https://example.com", source="TestSource",
        lang="zh", source_type="rss", crawled_at="2026-07-04T10:00:00",
    )
    assert item.id == "abc123"
    assert item.title == "Test"
    assert item.published_at == ""  # default
    assert item.tags == []  # default
    assert item.summary == ""  # default


def test_news_item_all_fields():
    item = NewsItem(
        id="abc123", title="Test", content="Content",
        url="https://example.com", source="TestSource",
        lang="en", source_type="crawler", crawled_at="2026-07-04T10:00:00",
        published_at="2026-07-03T08:00:00",
        tags=["AI", "LLM"], summary="A test summary",
    )
    assert item.lang == "en"
    assert item.published_at == "2026-07-03T08:00:00"
    assert item.tags == ["AI", "LLM"]
    assert item.summary == "A test summary"


def test_filter_report_defaults():
    report = FilterReport()
    assert report.total_input == 0
    assert report.url_removed == 0
    assert report.total_removed == 0
    assert report.total_output == 0
    assert report.remaining_items == []


def test_filter_report_total_removed():
    report = FilterReport(
        total_input=100, url_removed=20, minhash_removed=15,
        semantic_removed=10, credibility_removed=5, total_output=50,
    )
    assert report.total_removed == 50  # 20+15+10+5
    assert report.total_input == 100
    assert report.total_output == 50


def test_filter_report_to_email_html():
    report = FilterReport(
        total_input=100, url_removed=20, minhash_removed=15,
        semantic_removed=10, credibility_removed=5, total_output=50,
    )
    html = report.to_email_html()
    assert "100 条" in html
    assert "50 条" in html
    assert "-20 条" in html or "-20 条" in html


def test_filter_report_to_email_html_zero_input():
    report = FilterReport()
    html = report.to_email_html()
    assert "0 条" in html


if __name__ == "__main__":
    test_news_item_defaults()
    test_news_item_all_fields()
    test_filter_report_defaults()
    test_filter_report_total_removed()
    test_filter_report_to_email_html()
    test_filter_report_to_email_html_zero_input()
    print("All models tests passed!")
