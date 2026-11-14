"""跨期事件冷却测试：命中降级、两个例外、补位与失败降级。"""
import pytest

from src import config
from src.analysis import event_cooldown as EC


def _item(title, score=4.0, source="MarkTechPost", summary="", **kw):
    d = {"title": title, "score": score, "source": source, "summary": summary}
    d.update(kw)
    return d


def _hist(*titles):
    return [{"t": t, "s": ""} for t in titles]


SEEN = "DeepSeek 发布 V4.1-Flash-1017"
CURRENT = "DeepSeek V4.1 Flash 1017 成本大幅下降"


def test_config_exports():
    assert config.EVENT_COOLDOWN_DAYS == 7
    assert config.EVENT_PROGRESS_MIN_SOURCES == 3


def test_seen_event_demoted_to_briefs():
    display = [_item(CURRENT, 4.2)]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist(SEEN))
    assert kept == []
    assert len(briefs) == 1
    assert briefs[0]["title"] == CURRENT


def test_unseen_event_untouched():
    display = [_item(CURRENT, 4.2)]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist("GPT-5.2 发布"))
    assert kept == display
    assert briefs == []


def test_normalized_writings_match():
    display = [_item("DeepSeek V4.1 Flash 1017 上线 Vercel")]
    kept, _ = EC.apply_event_cooldown(display, [], _hist("DeepSeek V4.1-Flash-1017 开放权重"))
    assert kept == []


def test_title_without_model_key_is_not_cooled():
    title = "智谱新模型在法律领域拿下全球第一"
    display = [_item(title)]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist(title))
    assert kept == display
    assert briefs == []


def test_official_source_is_exempt():
    display = [_item(CURRENT, source="OpenAI")]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist(SEEN))
    assert kept == display
    assert briefs == []


def test_multi_source_name_list_is_exempt():
    summary = "成本下降三成（该消息被 3 家来源报道：量子位、InfoQ、The Verge）"
    display = [_item(CURRENT, summary=summary)]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist(SEEN))
    assert kept == display
    assert briefs == []


def test_multi_source_count_form_is_exempt():
    display = [_item(CURRENT, summary="该消息被 4 家来源报道，成本明显下降")]
    kept, briefs = EC.apply_event_cooldown(display, [], _hist(SEEN))
    assert kept == display
    assert briefs == []


def test_source_count_parsing():
    assert EC._source_count({"summary": "该消息被 5 家来源报道"}) == 5
    assert EC._source_count({"summary": "被 2 家来源报道：甲、乙、丙"}) == 3
    assert EC._source_count({"summary": "没有标注的普通摘要"}) == 0


def test_backfill_keeps_body_size():
    cooled = _item(CURRENT, 4.5)
    normal = _item("GPT-5.2 发布", 4.0)
    display = [cooled, normal]
    rest = [_item("Llama-4 开源", 3.0), _item("DeepSeek V4.1 Flash 1017 跑分", 2.0)]
    kept, briefs = EC.apply_event_cooldown(display, rest, _hist(SEEN))
    assert len(kept) == 2
    assert all(x["title"] != CURRENT for x in kept)
    assert any(x["title"] == "Llama-4 开源" for x in kept)
    assert len(briefs) == 2


def test_all_rest_cooled_reduces_body():
    display = [_item(CURRENT, 4.5), _item("Llama-4 开源", 4.0)]
    rest = [_item("DeepSeek V4.1 Flash 1017 跑分", 3.0)]
    kept, briefs = EC.apply_event_cooldown(display, rest, _hist(SEEN))
    assert len(kept) == 1
    assert kept[0]["title"] == "Llama-4 开源"
    assert len(briefs) == 2


def test_history_read_failure_degrades_without_progress(monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk down")
    monkeypatch.setattr(EC, "load_recent_items", _boom)
    display = [_item(CURRENT)]
    kept, briefs = EC.apply_event_cooldown(display, [])
    assert kept is display
    assert briefs == []


def test_progress_prefix_demoted_without_history():
    """无型号标题靠续报标注命中，不需要历史库。"""
    title = "进展：智谱新模型在法律领域拿下全球第一"
    display = [_item(title)]
    kept, briefs = EC.apply_event_cooldown(display, [], history_items=[])
    assert kept == []
    assert briefs[0]["title"] == title


def test_progress_prefix_official_source_is_exempt():
    display = [_item("进展：" + CURRENT, source="OpenAI")]
    kept, briefs = EC.apply_event_cooldown(display, [], history_items=[])
    assert kept == display
    assert briefs == []


def test_progress_prefix_multi_source_is_exempt():
    summary = "该消息被 3 家来源报道：量子位、InfoQ、The Verge"
    display = [_item("进展：" + CURRENT, summary=summary)]
    kept, briefs = EC.apply_event_cooldown(display, [], history_items=[])
    assert kept == display
    assert briefs == []


def test_history_failure_still_cools_progress(monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk down")
    monkeypatch.setattr(EC, "load_recent_items", _boom)
    display = [_item("进展：" + CURRENT)]
    kept, briefs = EC.apply_event_cooldown(display, [])
    assert kept == []
    assert len(briefs) == 1


def test_no_signal_returns_original():
    display = [_item(CURRENT)]
    kept, briefs = EC.apply_event_cooldown(display, [], history_items=[])
    assert kept is display
    assert briefs == []


def test_progress_prefix_backfills_from_rest():
    display = [_item("进展：" + CURRENT, 4.5), _item("Llama-4 开源", 4.0)]
    rest = [_item("GPT-5.2 发布", 3.0)]
    kept, briefs = EC.apply_event_cooldown(display, rest, history_items=[])
    assert len(kept) == 2
    assert all(not x["title"].startswith("进展：") for x in kept)
    assert len(briefs) == 1


def test_days_window_forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(EC, "load_recent_items",
                        lambda days: calls.append(days) or [])
    EC.apply_event_cooldown([_item(CURRENT)], [], days=3)
    assert calls == [3]
