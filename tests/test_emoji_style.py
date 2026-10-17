"""风格 emoji 测试：微博热搜热度标记与项目推荐星级显示。"""
import os
import tempfile

from src import config
from src.collect.trending_fetcher import _parse_trending_html
from src.delivery.email_gen import _decorate_weibo_title, make_email_with_categories


def test_decorate_weibo_title_adds_emoji():
    assert _decorate_weibo_title("爆#中国拟收紧AI模型出口管制#") == "🔥爆#中国拟收紧AI模型出口管制#"
    assert _decorate_weibo_title("沸#ChatGPT成Chrome助手#") == "🔥沸#ChatGPT成Chrome助手#"
    assert _decorate_weibo_title("热#Meta新条款#") == "📈热#Meta新条款#"


def test_decorate_weibo_title_is_idempotent():
    """模型已按提示词输出 emoji 时不重复添加。"""
    assert _decorate_weibo_title("🔥爆#已有标记#") == "🔥爆#已有标记#"
    assert _decorate_weibo_title("📈热#已有标记#") == "📈热#已有标记#"


def test_decorate_weibo_title_leaves_other_titles_untouched():
    assert _decorate_weibo_title("#普通词条#") == "#普通词条#"
    assert _decorate_weibo_title("") == ""


def test_email_weibo_style_renders_heat_emoji():
    original_out = config.EMAIL_OUTPUT
    config.EMAIL_OUTPUT = os.path.join(tempfile.gettempdir(), "email_weibo_emoji_test.html")
    try:
        items = [{
            "title": "爆#中国拟收紧AI模型出口管制#",
            "summary": "摘要。网友A：这下热闹了",
            "link": "https://example.com/a",
            "source": "The Decoder", "score": 4.2, "tags": ["行业动态"],
        }]
        make_email_with_categories(items, "", [], style_name="微博热搜")
        html = open(config.EMAIL_OUTPUT, encoding="utf-8").read()
    finally:
        config.EMAIL_OUTPUT = original_out
    assert "🔥爆#中国拟收紧AI模型出口管制#" in html


def test_project_stars_use_star_emoji():
    html = '''<html><body>
    <article class="Box-row">
      <h2><a href="/deepseek-ai/deepseek-harness">deepseek-ai / deepseek-harness</a></h2>
      <p class="col-9">Agent runtime with plugin system</p>
      <div class="f6 color-fg-muted mt-2">
        <a href="/x/stargazers" class="Link--muted">209,015</a>
        <span class="d-inline-block float-sm-right">2,514 stars today</span>
      </div>
    </article></body></html>'''
    parsed = _parse_trending_html(html)
    assert parsed and parsed[0]["stars"] == "⭐+2514 today"


def test_web_template_has_weibo_emoji_fallback():
    template = open(config.HTML_TEMPLATE, encoding="utf-8").read()
    assert "WEIBO_HEAT_MARKS" in template
    assert "🚀 本周热门学习项目" in template
