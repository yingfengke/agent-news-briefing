"""语义去重的向量缓存隔离测试：换模型后不得复用旧向量。"""
import json

from src import config
from src.dedupe.semantic_dedup import SemanticDeduper


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_cache_reused_when_model_matches(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    _write(cache_file, {"model": config.EMBEDDING_MODEL, "vectors": {"标题": [0.1, 0.2]}})
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(cache_file))

    deduper = SemanticDeduper()
    assert deduper._cache == {"标题": [0.1, 0.2]}


def test_cache_dropped_when_model_changes(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    _write(cache_file, {"model": "other/model", "vectors": {"标题": [0.1, 0.2]}})
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(cache_file))

    deduper = SemanticDeduper()
    assert deduper._cache == {}


def test_legacy_flat_cache_discarded(tmp_path, monkeypatch):
    """旧格式（扁平 {标题: 向量}）没有模型标识，一律丢弃。"""
    cache_file = tmp_path / "cache.json"
    _write(cache_file, {"标题": [0.1, 0.2]})
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(cache_file))

    deduper = SemanticDeduper()
    assert deduper._cache == {}


def test_corrupted_cache_discarded(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    cache_file.write_bytes(b"\xc8\xd0\xb2\xbb\xca\xc7 utf-8")
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(cache_file))

    deduper = SemanticDeduper()
    assert deduper._cache == {}


def test_save_cache_tags_model(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(cache_file))

    deduper = SemanticDeduper()
    deduper._cache = {"标题": [0.3]}
    deduper._save_cache()

    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["model"] == config.EMBEDDING_MODEL
    assert saved["vectors"] == {"标题": [0.3]}
