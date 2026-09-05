#!/usr/bin/env python3
"""trending_fetcher 解析测试：确保「今日新增 star」取的是日增而非累计总数。"""
from bs4 import BeautifulSoup

from src.collect.trending_fetcher import (
    _extract_stars_today, _parse_trending_html, _fetch_html_with_retry,
    _search_fallback, _FALLBACK_MIN_STARS, _try_parse_int,
    fetch_github_trending,
)
from src.config import trending_tags as tt


def _make_article(total_stars: str, today_stars: str):
    html = f'''
    <article class="Box-row">
      <h2><a href="/owner/repo">owner / repo</a></h2>
      <p class="col-9">some description</p>
      <div class="f6 color-fg-muted mt-2">
        <a href="/owner/repo/stargazers" class="Link--muted">{total_stars}</a>
        <span class="d-inline-block float-sm-right">{today_stars} stars today</span>
      </div>
    </article>
    '''
    return BeautifulSoup(html, "html.parser").find("article")


def test_extract_stars_today_prefers_daily_not_total():
    # 累计 45,678、日增 2,514 -> 必须取到 2514，不能取到 45678
    art = _make_article("45,678", "2,514")
    assert _extract_stars_today(art) == 2514


def test_extract_stars_today_small_numbers():
    art = _make_article("1,200", "37")
    assert _extract_stars_today(art) == 37


def test_extract_stars_today_missing():
    html = '<article class="Box-row"><div class="f6">no stars info</div></article>'
    art = BeautifulSoup(html, "html.parser").find("article")
    assert _extract_stars_today(art) == 0


def test_parse_trending_html_extracts_fields():
    html = '''
    <article class="Box-row">
      <h2><a href="/deepseek-ai/deepseek-harness">deepseek-ai / deepseek-harness</a></h2>
      <p class="col-9">DeepSeek Harness: Everything is a Plugin. A very long description
      that should be truncated at one hundred characters exactly by the parser logic.</p>
      <div class="f6 color-fg-muted mt-2">
        <a href="/deepseek-ai/deepseek-harness/stargazers" class="Link--muted">207,000</a>
        <span class="d-inline-block float-sm-right">18,000 stars today</span>
      </div>
    </article>
    <article class="Box-row">
      <h2><a href="/gis-app/satellite-viewer">gis-app / satellite-viewer</a></h2>
      <p class="col-9">spy satellite simulator in your browser with real data</p>
      <div class="f6"><span class="d-inline-block float-sm-right">12 stars today</span></div>
    </article>
    '''
    items = _parse_trending_html(html)
    assert len(items) == 2
    first = items[0]
    assert first["name"] == "deepseek-ai/deepseek-harness"
    assert first["stars_n"] == 18000
    assert first["link"] == "https://github.com/deepseek-ai/deepseek-harness"
    assert len(first["desc"]) <= 100


def test_fetch_html_with_retry_succeeds_after_failures(monkeypatch):
    calls = {"n": 0}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>ok</html>"

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise Exception("IncompleteRead: connection cut")
        return _FakeResp()

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen", _flaky)
    html = _fetch_html_with_retry("https://github.com/trending", {"User-Agent": "t"}, retries=3)
    assert html == "<html>ok</html>"
    assert calls["n"] == 3


def test_fetch_html_with_retry_all_fail_returns_none(monkeypatch):
    def _always_fail(*a, **k):
        raise Exception("network down")

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen", _always_fail)
    assert _fetch_html_with_retry("https://github.com/trending", {}, retries=2) is None


def test_fetch_html_with_retry_http_404_no_retry(monkeypatch):
    """404/410 是永久错误，应只请求 1 次立即放弃，不浪费重试。"""
    import urllib.error
    calls = {"n": 0}

    def _not_found(*a, **k):
        calls["n"] += 1
        raise urllib.error.HTTPError("https://github.com/trending", 404,
                                     "Not Found", {}, None)

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen", _not_found)
    assert _fetch_html_with_retry("https://github.com/trending", {}, retries=3) is None
    assert calls["n"] == 1


def test_try_parse_int_anchors_stars_today():
    # 锚定 stars today 之前的数字：文案顺序变化（如 'up from 500, now 1,234
    # stars today'）时不能误取 500（旧 findall 取 [0] 会取错）
    assert _try_parse_int("1,234 stars today") == 1234
    assert _try_parse_int("up from 500, now 1,234 stars today") == 1234
    assert _try_parse_int("no numbers here") == 0


def test_extract_stars_today_with_reordered_text():
    # 端到端：direct 文本含额外前置数字时仍取 stars today 前的值
    art = BeautifulSoup(
        '<article class="Box-row"><div class="f6">'
        '<span class="d-inline-block float-sm-right">up from 500, now 2,514 stars today</span>'
        "</div></article>", "html.parser").find("article")
    assert _extract_stars_today(art) == 2514


def test_search_fallback_filters_noise_and_classifies(monkeypatch):
    """兜底必须滤掉 <300 星噪声与「其他」分类（非 AI），只保留高质量 AI 项目。"""
    import json

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            # 不同 topic 查询返回不同候选（模拟 5 组查询），含真实 deepseek-harness 样例
            payload = {
                "total_count": 4,
                "items": [
                    {
                        "full_name": "deepseek-ai/deepseek-harness",
                        "description": "DeepSeek Harness: Everything is a Plugin.",
                        "stargazers_count": 208987,
                        "topics": ["ai-agents", "cordis", "dsh", "dsh-plugin"],
                    },
                    {
                        "full_name": "noise/llm-agent",       # 星数过低
                        "description": "small llm agent demo",
                        "stargazers_count": 35,
                        "topics": ["llm", "agent"],
                    },
                    {
                        "full_name": "gis/satellite-viewer",   # 非 AI（分类其他）
                        "description": "spy satellite simulator with real data",
                        "stargazers_count": 9999,
                        "topics": ["gis", "satellite-tracking"],
                    },
                    {
                        "full_name": "xiao/ai-mcp-bridge",     # 合格替补
                        "description": "mcp bridge for coding agents",
                        "stargazers_count": 1200,
                        "topics": ["mcp", "coding-agents"],
                    },
                ],
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen",
                        lambda *a, **k: _FakeResp())
    out = _search_fallback({})
    names = [p["name"] for p in out]
    # deepseek-harness 必须在列（回归锁死 2026-09-02 漏推 bug）
    assert "deepseek-ai/deepseek-harness" in names
    # 噪声（35 星）与非 AI（卫星模拟器）必须被滤掉
    assert "noise/llm-agent" not in names
    assert "gis/satellite-viewer" not in names
    # 合格替补（mcp bridge）应入选补位
    assert "xiao/ai-mcp-bridge" in names
    # 每项都有正确分类标签
    by_name = {p["name"]: p for p in out}
    assert by_name["deepseek-ai/deepseek-harness"]["tag"] == "Agent 与智能体"
    assert by_name["xiao/ai-mcp-bridge"]["tag"] == "Agent 与智能体"
    assert len(out) <= 3


def test_fallback_min_stars_constant():
    # 兜底星数下限存在且合理（防噪声仓库进推荐）
    assert isinstance(_FALLBACK_MIN_STARS, int) and _FALLBACK_MIN_STARS >= 100


def _trending_html_rows(rows):
    """构造含多仓库的 trending 页面 HTML。rows: [(full_name, desc, total, today)]"""
    arts = []
    for full, desc, total, today in rows:
        arts.append(f'''
        <article class="Box-row">
          <h2><a href="/{full}">{full}</a></h2>
          <p class="col-9">{desc}</p>
          <div class="f6 color-fg-muted mt-2">
            <a href="/{full}/stargazers" class="Link--muted">{total}</a>
            <span class="d-inline-block float-sm-right">{today} stars today</span>
          </div>
        </article>''')
    return "<html><body>" + "".join(arts) + "</body></html>"


def test_fetch_ranks_relevance_before_stars(monkeypatch):
    """领域相关优先：弱相关但日增 5000 的项目，排在强相关但日增 100 的项目之后。

    回归锁死推荐排序语义：强相关(harness/codex/mcp 等信号) > 弱相关(泛 agent/llm)
    > 热度。
    """
    import json
    html = _trending_html_rows([
        ("other/weak-agent", "generic multi-agent chat app", "9,000", "5,000"),
        ("deepseek-ai/strong-harness", "agent runtime with plugin system", "1,200", "100"),
    ])
    topics_map = {
        "other/weak-agent": ["agents", "llm"],          # 弱相关
        "deepseek-ai/strong-harness": ["dsh"],          # 强相关
    }

    class _FakeResp:
        def __init__(self, body, ctype="application/json"):
            self._body = body
            self.status = 200
            self._ctype = ctype

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._body

    def _router(url, *a, **k):
        u = url if isinstance(url, str) else url.full_url
        if "github.com/trending" in u:
            return _FakeResp(html.encode("utf-8"))
        if "/topics" in u:
            full = u.split("/repos/")[1].split("/topics")[0]
            return _FakeResp(json.dumps({"names": topics_map.get(full, [])}).encode("utf-8"))
        raise AssertionError(f"unexpected url: {u}")

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen", _router)
    result = fetch_github_trending()
    assert result, "应返回非空结果"
    # 强相关项目必须排第一（即使日增只有 100 vs 弱相关的 5000）
    assert result[0]["name"] == "deepseek-ai/strong-harness"
    assert result[0]["tag"] == "Agent 与智能体"
    assert len(result) == 2


def test_search_fallback_ranks_relevance_before_stars(monkeypatch):
    """兜底同样领域相关优先：弱相关高星排在强相关低星之后。"""
    import json

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            payload = {
                "total_count": 3,
                "items": [
                    {
                        "full_name": "other/weak-llm-chat",
                        "description": "generic llm chat app with agents",
                        "stargazers_count": 90000,
                        "topics": ["llm", "agents"],
                    },
                    {
                        "full_name": "deepseek-ai/strong-harness",
                        "description": "agent runtime, everything is a plugin",
                        "stargazers_count": 1200,
                        "topics": ["harness", "dsh"],
                    },
                ],
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen",
                        lambda *a, **k: _FakeResp())
    out = _search_fallback({})
    assert out, "应返回非空结果"
    # 强相关(1200 星)排到弱相关(9 万星)前面
    assert out[0]["name"] == "deepseek-ai/strong-harness"


def test_search_fallback_dynamic_min_stars(monkeypatch):
    """星数门槛动态化：强相关项目 50 星即可入选，弱相关仍需 300 星。"""
    import json

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            payload = {
                "total_count": 3,
                "items": [
                    {
                        "full_name": "early/strong-harness-tool",   # 强相关但早期
                        "description": "lightweight agent harness with mcp support",
                        "stargazers_count": 80,
                        "topics": ["harness", "mcp"],
                    },
                    {
                        "full_name": "other/weak-medium",            # 弱相关 200 星 → 应滤
                        "description": "a generic llm chat application",
                        "stargazers_count": 200,
                        "topics": ["llm", "agents"],
                    },
                    {
                        "full_name": "other/weak-big",               # 弱相关 9000 星 → 入选
                        "description": "popular llm multi-agent chat app",
                        "stargazers_count": 9000,
                        "topics": ["llm", "multi-agent"],
                    },
                ],
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("src.collect.trending_fetcher.urlopen",
                        lambda *a, **k: _FakeResp())
    out = _search_fallback({})
    names = [p["name"] for p in out]
    # 80 星强相关入选（动态门槛 50）；200 星弱相关被滤（固定门槛 300）
    assert "early/strong-harness-tool" in names
    assert "other/weak-medium" not in names
    assert "other/weak-big" in names
