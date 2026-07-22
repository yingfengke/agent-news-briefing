"""credibility.py - 阶段 D: 来源可信度过滤（白名单/黑名单 + 信号评分）。
"""
import re
from urllib.parse import urlparse

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.credibility")
class CredibilityFilter:
    """
    可信度评分过滤。

    信号评分（满分 1.00）：
      HTTPS          +0.25
      有作者署名     +0.25
      有发布日期     +0.20
      无侵犯隐私     +0.20
      正文 >200字    +0.10（门槛，不满足直接丢弃）
      ─────────────────
      总分           1.00

    白名单域名 → 直接 0.92 分
    黑名单域名 → 直接丢弃
    阈值 0.40 → 低于此丢弃
    """

    def __init__(self):
        self.threshold = config.CREDIBILITY_SCORE_THRESHOLD
        self.whitelist = config.CREDIBILITY_WHITELIST
        self.blacklist = config.CREDIBILITY_BLACKLIST

    def _domain_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def _is_whitelisted(self, domain: str) -> bool:
        for wl in self.whitelist:
            if domain == wl or domain.endswith("." + wl):
                return True
        return False

    def _is_blacklisted(self, domain: str) -> bool:
        for bl in self.blacklist:
            if bl in domain:
                return True
        return False

    def _has_author(self, item: NewsItem) -> bool:
        """检查是否有作者署名"""
        text = f"{item.title} {item.content}"
        # 匹配 "作者/文/图/摄" 等关键字
        return bool(re.search(r"(作者|文\s*[/／]\s*|图\s*[/／]\s*|责编|编辑|撰文|记者)", text))

    def _has_pubdate(self, item: NewsItem) -> bool:
        """检查是否有发布日期"""
        if item.published_at and len(item.published_at) > 5:
            return True
        text = f"{item.title} {item.content}"
        # 匹配日期模式：2026-05-07, 2026年5月7日 等
        return bool(re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", text))

    def _has_privacy_content(self, item: NewsItem) -> bool:
        """检查是否包含侵犯隐私内容"""
        text = f"{item.title} {item.content}"
        # 手机号、身份证、邮箱
        if re.search(r"1[3-9]\d{9}", text):
            return True
        if re.search(r"\d{18}[\dXx]", text):
            return True
        if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
            return True
        return False

    def _content_length_ok(self, item: NewsItem) -> bool:
        """正文长度是否 >= 10 字（基本门槛，防止空/垃圾内容）"""
        return len(item.content) >= 10

    def score(self, item: NewsItem) -> float:
        """计算信任分数，返回 0.0 ~ 1.0"""
        domain = self._domain_from_url(item.url)

        # 黑名单 → 直接 0
        if self._is_blacklisted(domain):
            return 0.0

        # 白名单 → 直接高分
        if self._is_whitelisted(domain):
            return 0.92

        # 正文长度门槛：不满足直接丢弃
        if not self._content_length_ok(item):
            return 0.0

        score = 0.0
        # HTTPS
        if item.url.startswith("https"):
            score += 0.25

        # 作者署名
        if self._has_author(item):
            score += 0.25

        # 发布日期
        if self._has_pubdate(item):
            score += 0.20

        # 无侵犯隐私
        if not self._has_privacy_content(item):
            score += 0.20

        # 正文门槛加分
        score += 0.10

        return min(score, 1.0)

    def should_filter(self, item: NewsItem) -> bool:
        return self.score(item) < self.threshold


# ============================================================
# 过滤管道：串联 4 个阶段
# ============================================================
