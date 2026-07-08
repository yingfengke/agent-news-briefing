"""测试去重层：原子写入与 run_pipeline 统一返回（13.8 / 13.14）"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch
from src import config
from src.models import NewsItem, FilterReport
from src.deduplicator import UrlDeduper, run_pipeline


def _make_item(url, title="标题", content="这是一段足够长的正文内容用于通过可信度门槛。"):
    return NewsItem(
        id=url[-16:], title=title, content=content, url=url,
        source="S", lang="zh", source_type="rss", crawled_at="2026-07-08T00:00:00",
    )


def test_atomic_save_no_temp_leftover():
    """UrlDeduper._save 应原子写入：不产生残留 .tmp 文件，且内容正确（13.8）。"""
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "url_db.json")
        ded = UrlDeduper(db_path=db, initial_set=set())
        ded._seen.add("abc")
        ded.flush()
        with open(db, encoding="utf-8") as f:
            assert json.load(f)["urls"] == ["abc"]
        leftovers = [n for n in os.listdir(d) if n.endswith(".tmp")]
        assert leftovers == [], leftovers


def test_atomic_save_accumulates_across_reloads():
    """原子写入后重新加载，已存哈希应累加保留。"""
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "url_db.json")
        UrlDeduper(db_path=db, initial_set=set()).flush()
        ded = UrlDeduper(db_path=db)  # 默认从文件加载
        ded._seen.add("x1")
        ded.flush()
        with open(db, encoding="utf-8") as f:
            assert "x1" in json.load(f)["urls"]


def _patched_run(items):
    """临时替换跨天去重库与 embedding 缓存路径，避免污染/读取真实文件后再跑 run_pipeline。"""
    with tempfile.TemporaryDirectory() as d:
        tmp_db = os.path.join(d, "url_db.json")
        tmp_emb = os.path.join(d, "embedding_cache.json")
        with patch.object(config, "URL_DB_FILE", tmp_db), \
             patch.object(config, "EMBEDDING_CACHE_FILE", tmp_emb):
            return run_pipeline(items)


def test_run_pipeline_empty_input_returns_report():
    """空输入也应返回完整 FilterReport。"""
    report = _patched_run([])
    assert isinstance(report, FilterReport)
    assert report.total_input == 0
    assert report.remaining_items == []


def test_run_pipeline_handle_url_duplicates():
    """含重复 URL 时 A 阶段去重，仍返回完整 FilterReport（不提前 return 缺字段，13.14）。"""
    items = [_make_item("https://a.com/1"), _make_item("https://a.com/1")]
    report = _patched_run(items)
    assert isinstance(report, FilterReport)
    assert report.total_input == 2
    assert report.url_removed == 1


def test_run_pipeline_full_run_returns_report():
    """正常流程统一在末尾返回 report，remaining_items 与 total_output 正确填充。"""
    items = [
        _make_item("https://a.com/1", content="内容甲：关于模型发布的报道。"),
        _make_item("https://b.com/2", content="内容乙：关于框架更新的报道。"),
    ]
    report = _patched_run(items)
    assert isinstance(report, FilterReport)
    assert report.total_input == 2
    assert report.remaining_items  # 至少保留部分
    assert report.total_output == len(report.remaining_items)


if __name__ == "__main__":
    test_atomic_save_no_temp_leftover()
    test_atomic_save_accumulates_across_reloads()
    test_run_pipeline_empty_input_returns_report()
    test_run_pipeline_handle_url_duplicates()
    test_run_pipeline_full_run_returns_report()
    print("All deduplicator tests passed!")
