#!/usr/bin/env python3
"""trending_fetcher 解析测试：确保「今日新增 star」取的是日增而非累计总数。"""
from bs4 import BeautifulSoup

from src.trending_fetcher import _extract_stars_today


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
