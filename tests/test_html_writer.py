"""测试 HTML 写入层核心函数"""
import sys, os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config
from src.html_writer import clean_links, _get_category, _merge_small_categories, make_email_with_categories, write_html


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


def test_get_category_prefers_category_field():
    """_get_category 优先用 item['category']（D1）。"""
    assert _get_category({"category": "Agent框架", "tags": ["大模型"], "title": "GPT-5"}) == "Agent框架"
    assert _get_category({"category": "未知类", "tags": ["论文与研究"], "title": "x"}) == "论文与研究"


def test_get_category_no_summary_scan():
    """关键词兜底只扫标题、不扫摘要，避免「其他动态」被反复捞走（D1 根因）。"""
    # title 不命中，但 summary 含触发词 -> 仍归其他动态
    assert _get_category({"title": "今日杂谈", "summary": "关于 llama 的论文"}) == "其他动态"
    # title 命中 -> 命中分类
    assert _get_category({"title": "OpenAI 发布新模型"}) == "产品与发布"


def test_merge_small_categories():
    """<2 条的分类应并入「其他动态」，避免板块过于分散（D1）。"""
    groups = {
        "大模型": [1, 2],
        "Agent框架": [3],        # <2 -> 合并
        "论文与研究": [],          # 0 -> 合并
        "其他动态": [9],
    }
    merged = _merge_small_categories(groups, min_size=2)
    assert "Agent框架" not in merged
    assert "论文与研究" not in merged
    assert len(merged["其他动态"]) == 2  # 原 [9] + Agent框架 [3]


def test_email_render_resolved_categories_and_links():
    """邮件渲染：分类解析正确、No. 顺序编号、阅读原文超链接、标签 chip、零散类合并（P1-2/P1-4/D1）。"""
    original_out = config.EMAIL_OUTPUT
    tmp_out = os.path.join(tempfile.gettempdir(), "email_render_test.html")
    config.EMAIL_OUTPUT = tmp_out
    try:
        items = [
            {"title": "GPT-5 正式发布", "summary": "OpenAI 推出 GPT-5。", "link": "https://openai.com/1",
             "source": "OpenAI", "score": 4.5, "tags": ["大模型"], "category": "大模型"},
            {"title": "GPT-5 多模态升级", "summary": "GPT-5 多模态能力增强。", "link": "https://openai.com/2",
             "source": "OpenAI", "score": 4.3, "tags": ["大模型"], "category": "大模型"},
            {"title": "LangGraph 新版本", "summary": "LangGraph 更新。", "link": "https://github.com/3",
             "source": "GitHub", "score": 3.5, "tags": ["Agent框架"], "category": "Agent框架"},
            {"title": "AutoGen 发布", "summary": "AutoGen v0.4。", "link": "https://github.com/4",
             "source": "GitHub", "score": 3.2, "tags": ["Agent框架"], "category": "Agent框架"},
            {"title": "某 ArXiv 论文", "summary": "一篇新论文。", "link": "https://arxiv.org/5",
             "source": "ArXiv AI", "score": 3.0, "tags": ["论文与研究"], "category": "论文与研究"},
            {"title": "某产品上线", "summary": "新产品发布。", "link": "https://x.com/6",
             "source": "TechCrunch AI", "score": 2.5, "tags": ["产品与发布", "工具"], "category": "产品与发布"},
            {"title": "行业融资动态", "summary": "某公司融资。", "link": "https://x.com/7",
             "source": "36氪", "score": 2.0, "tags": ["行业动态"], "category": "行业动态"},
        ]
        make_email_with_categories(items, "今日趋势预判。", [], filter_report=None,
                                   style_name="极简资讯", trivia="冷知识一条。")
        html = open(tmp_out, encoding="utf-8").read()
    finally:
        config.EMAIL_OUTPUT = original_out

    # No. 顺序编号
    nos = __import__("re").findall(r"No\.(\d{2})", html)
    assert nos == [f"{i:02d}" for i in range(1, len(items) + 1)], nos
    # 阅读原文超链接
    assert 'href="https://openai.com/1"' in html and "阅读原文" in html
    # 标签 chip（产品与发布那条带两个 tag）
    assert "产品与发布" in html and "工具" in html
    # 零散单条分类合并进「其他动态（3条）」
    assert "其他动态（3条）" in html


def test_email_render_project_links():
    """项目推荐区块：项目名应渲染为指向 GitHub 仓库的可点击超链接。

    修复点：数据源 trending_fetcher 已产出 link 字段，但渲染端此前从未将其接成
    超链接（邮件端是纯文本 span，web 端 __PROJECTS__ 从未渲染），导致项目推荐无法点击。
    """
    original_out = config.EMAIL_OUTPUT
    tmp_out = os.path.join(tempfile.gettempdir(), "email_project_test.html")
    config.EMAIL_OUTPUT = tmp_out
    try:
        projects = [
            {"name": "addyosmani/agent-skills", "desc": "生产级 Agent 技能。",
             "stars": "star 710", "link": "https://github.com/addyosmani/agent-skills",
             "tag": "Agent 框架"},
        ]
        make_email_with_categories([], "", projects)
        html = open(tmp_out, encoding="utf-8").read()
    finally:
        config.EMAIL_OUTPUT = original_out

    assert "本周热门学习项目" in html
    # 项目名是可点击链接，指向其 GitHub 仓库
    assert 'href="https://github.com/addyosmani/agent-skills"' in html
    assert "addyosmani/agent-skills" in html
    # 无 link 时回落为纯文本（不出现空 href）
    assert 'href=""' not in html


def test_index_redirect_placeholder():
    """web/index.html 应为固定重定向占位，不重复完整新闻内容（13.12）。"""
    from src.html_writer import _render_index_redirect
    html = _render_index_redirect()
    assert "tech-briefing.html" in html
    assert "http-equiv=\"refresh\"" in html
    # 重定向占位不应包含新闻数据占位，证明它不承载完整内容
    assert "__NEWS_DATA__" not in html


def test_write_html_index_is_redirect_not_duplicate():
    """write_html 后 index.html 为重定向占位，tech-briefing.html 承载真实数据（13.12 / ④）。"""
    original_tmpl = config.HTML_TEMPLATE
    original_html = config.HTML_FILE
    original_base = config.BASE_DIR
    d = tempfile.mkdtemp()
    webd = os.path.join(d, "web")
    os.makedirs(webd, exist_ok=True)
    try:
        # 复制真实模板到临时 web 目录，作为渲染源
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
              "source": "S", "tags": [], "category": "其他动态"}],
            "分析",
            [{"name": "p", "link": "https://github.com/p", "stars": "star 1",
              "desc": "d", "tag": "t"}],
        )
        with open(tf, encoding="utf-8") as f:
            tb = f.read()
        with open(os.path.join(webd, "index.html"), encoding="utf-8") as f:
            idx = f.read()
    finally:
        config.HTML_TEMPLATE = original_tmpl
        config.HTML_FILE = original_html
        config.BASE_DIR = original_base

    # tech-briefing.html 承载真实新闻数据，且经 Jinja2 渲染无残留 {{ }}
    assert "__NEWS_DATA__" in tb
    assert "T1" in tb
    assert "{{" not in tb and "}}" not in tb
    # index.html 只是重定向占位，不重复完整内容
    assert "__NEWS_DATA__" not in idx
    assert "tech-briefing.html" in idx


if __name__ == "__main__":
    test_clean_links_empty()
    test_clean_links_no_links()
    test_clean_links_markdown_link()
    test_clean_links_bare_url()
    test_clean_links_multiple()
    test_clean_links_url_with_path()
    test_clean_links_no_double_wrap()
    test_get_category_prefers_category_field()
    test_get_category_no_summary_scan()
    test_merge_small_categories()
    test_email_render_resolved_categories_and_links()
    test_email_render_project_links()
    print("All html_writer tests passed!")
