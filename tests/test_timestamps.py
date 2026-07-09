"""测试发布时间回填、生成时间戳、RSS pubDate 与相对时间换算规则"""
import sys, os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config
from src.config.constants import now_bjt
from src.html_writer import write_html, make_email_with_categories, generate_rss_feed
from src.ai_analyzer import _build_context
from src.main import _fmt_published, _attach_published_at
from src.models import NewsItem


def test_now_bjt_is_beijing():
    """now_bjt 应返回北京时间（UTC+8）。"""
    import datetime
    from zoneinfo import ZoneInfo
    dt = now_bjt()
    # BJT 自身时区偏移应为 +8
    assert dt.utcoffset() == datetime.timedelta(hours=8), dt.utcoffset()


def test_fmt_published_utc_iso_to_bjt():
    """UTC ISO 应转为北京时间显示串。"""
    # 2026-07-08T16:00:00+00:00 UTC = 2026-07-09 00:00 BJT（无具体时分 -> 仅月日）
    out = _fmt_published("2026-07-08T16:00:00+00:00")
    assert out == "07-09", out
    # 带具体时分
    out2 = _fmt_published("2026-07-08T06:30:00+00:00")
    assert out2 == "07-08 14:30", out2


def test_fmt_published_naive_iso_treated_as_utc():
    """无时区标注的 ISO 应视为 UTC 再转北京。"""
    out = _fmt_published("2026-07-08T16:00:00")
    assert out == "07-09", out


def test_fmt_published_invalid_returns_empty():
    assert _fmt_published("") == ""
    assert _fmt_published("not-a-date") == ""
    assert _fmt_published(None) == ""


def test_attach_published_at_by_url_and_title():
    """_attach_published_at 应按 URL / 标题回关联出 published_at 与显示串。"""
    clean = [
        NewsItem(id="1", title="GPT-5 发布", content="x", url="https://openai.com/1",
                  source="OpenAI", lang="en", source_type="rss",
                  crawled_at="t", published_at="2026-07-08T02:00:00+00:00", tags=[]),
        NewsItem(id="2", title="LangGraph 更新", content="y", url="https://github.com/2",
                  source="GitHub", lang="en", source_type="rss",
                  crawled_at="t", published_at="2026-07-07T12:00:00+00:00", tags=[]),
    ]
    final = [
        {"title": "GPT-5 发布", "link": "https://openai.com/1", "tags": ["大模型"], "category": "大模型"},
        {"title": "LangGraph 更新", "link": "https://github.com/2", "tags": ["Agent框架"], "category": "Agent框架"},
        {"title": "无发布时间的新闻", "link": "https://x.com/3", "tags": [], "category": "其他动态"},
    ]
    _attach_published_at(final, clean)

    assert final[0]["published_at"] == "2026-07-08T02:00:00+00:00"
    assert final[0]["published_at_disp"] == "07-08 10:00", final[0]["published_at_disp"]
    # 标题不匹配 URL 但标题命中也可回关联
    assert final[1]["published_at_disp"] == "07-07 20:00", final[1]["published_at_disp"]
    # 无发布时间 -> 不加字段
    assert "published_at" not in final[2]


def test_write_html_injects_generated_at_and_date():
    """write_html 应在 tech-briefing.html 注入服务端生成时间戳与日期。"""
    original_tmpl = config.HTML_TEMPLATE
    original_html = config.HTML_FILE
    original_base = config.BASE_DIR
    d = tempfile.mkdtemp()
    webd = os.path.join(d, "web")
    os.makedirs(webd, exist_ok=True)
    try:
        tmpl_src = os.path.join(os.path.dirname(__file__), "..", "web",
                               "tech-briefing.template.html")
        tmpl = os.path.join(webd, "tech-briefing.template.html")
        with open(tmpl_src, encoding="utf-8") as f:
            tpl = f.read()
        with open(tmpl, "w", encoding="utf-8") as f:
            f.write(tpl)
        tf = os.path.join(webd, "tech-briefing.html")
        config.HTML_TEMPLATE = tmpl
        config.HTML_FILE = tf
        config.BASE_DIR = d

        write_html(
            [{"title": "T1", "summary": "s", "link": "https://x.com",
              "source": "S", "tags": [], "category": "其他动态",
              "published_at_disp": "07-08 10:00"}],
            "分析",
            [{"name": "p", "link": "https://github.com/p", "stars": "star 1",
              "desc": "d", "tag": "t"}],
            generated_at="2026-07-09 06:00（北京时间）",
        )
        with open(tf, encoding="utf-8") as f:
            tb = f.read()
    finally:
        config.HTML_TEMPLATE = original_tmpl
        config.HTML_FILE = original_html
        config.BASE_DIR = original_base

    assert "2026-07-09 06:00（北京时间）" in tb
    # 头部日期为服务端注入（不再是 Loading date…）
    assert "Loading date" not in tb
    # 卡片展示发布时间：模板含「发布于」字面量，数据 JSON 含具体时刻
    assert "发布于" in tb
    assert "07-08 10:00" in tb
    # 时间换算免责声明已渲染（括号内日期可能不准）
    assert "由 AI 按发布日推算" in tb
    # Jinja2 渲染无残留占位
    assert "{{" not in tb and "}}" not in tb


def test_email_injects_generated_at_and_published():
    """邮件 HTML 应含生成时间戳与新闻发布时间。"""
    original_out = config.EMAIL_OUTPUT
    tmp_out = os.path.join(tempfile.gettempdir(), "email_ts_test.html")
    config.EMAIL_OUTPUT = tmp_out
    try:
        make_email_with_categories(
            [{"title": "GPT-5 发布", "summary": "OpenAI 推出 GPT-5。",
              "link": "https://openai.com/1", "source": "OpenAI", "score": 4.5,
              "tags": ["大模型"], "category": "大模型",
              "published_at_disp": "07-08 10:00"}],
            "今日趋势预判。", [], filter_report=None,
            style_name="极简资讯", trivia="冷知识一条。",
            generated_at="2026-07-09 06:00（北京时间）",
        )
        html = open(tmp_out, encoding="utf-8").read()
    finally:
        config.EMAIL_OUTPUT = original_out

    assert "生成时间：2026-07-09 06:00（北京时间）" in html
    assert "发布于 07-08 10:00" in html
    # 时间换算免责声明已渲染
    assert "由 AI 按发布日推算" in html


def test_rss_feed_has_pubdate():
    """RSS 每条新闻应带北京时间 pubDate。"""
    import xml.etree.ElementTree as ET
    original_base = config.BASE_DIR
    d = tempfile.mkdtemp()
    webd = os.path.join(d, "web")
    os.makedirs(webd, exist_ok=True)
    try:
        config.BASE_DIR = d
        generate_rss_feed(
            [{"title": "GPT-5 发布", "summary": "x", "link": "https://openai.com/1",
              "source": "OpenAI", "tags": ["大模型"],
              "published_at": "2026-07-08T02:00:00+00:00"}],
            "分析", generated_at="2026-07-09 06:00（北京时间）",
        )
        tree = ET.parse(os.path.join(webd, "rss.xml"))
        items = tree.findall(".//item")
        # 新闻条目（标题为 GPT-5 发布），排除「今日深度分析」条
        news_items = [it for it in items
                       if it.findtext("title") == "GPT-5 发布"]
        assert len(news_items) == 1, f"新闻条目数异常: {len(news_items)}"
        pub = news_items[0].find("pubDate")
        assert pub is not None, "缺少 pubDate"
        # 北京时间 = UTC+8 -> 2026-07-08 10:00:00 +0800（RFC822 格式）
        assert "08 Jul 2026 10:00:00 +0800" in pub.text, pub.text
    finally:
        config.BASE_DIR = original_base


def test_build_context_has_relative_time_rule():
    """_build_context 的 preamble 应包含「保留原文+括号附注+可能不准」的时间规则。"""
    item = NewsItem(id="1", title="t", content="c", url="u", source="s",
                    lang="en", source_type="rss", crawled_at="x", tags=[])
    ctx = _build_context([item], "sys prompt", content_limit=80, max_items=1)
    uc = ctx["user_content"]
    assert "时间表述要求" in uc
    # 保留原文（不替换）
    assert "保留原文" in uc
    # 括号附注绝对日期（保留原表述 + 加括号换算）
    assert "（2026年7月10日）" in uc
    # 覆盖各方向
    assert "昨天" in uc and "一周后" in uc and "中旬" in uc and "月底" in uc
    # 跨月跨年进位
    assert "跨月跨年" in uc and "2027年1月1日" in uc
    # 兜底：无法定位则不加括号、不臆造
    assert "切勿臆造" in uc
    # 警告：AI 推算的日期可能不准
    assert "仅供参考" in uc
    # 新闻条目仍正常注入（标题前缀 + 来源）
    assert "1. [s]" in uc


if __name__ == "__main__":
    test_now_bjt_is_beijing()
    test_fmt_published_utc_iso_to_bjt()
    test_fmt_published_naive_iso_treated_as_utc()
    test_fmt_published_invalid_returns_empty()
    test_attach_published_at_by_url_and_title()
    test_write_html_injects_generated_at_and_date()
    test_email_injects_generated_at_and_published()
    test_rss_feed_has_pubdate()
    test_build_context_has_relative_time_rule()
    print("All timestamp tests passed!")
