"""minhash_dedup.py - 阶段 B: MinHash+LSH 内容指纹去重（datasketch + jieba 分词）。
"""
import re
from collections import defaultdict

import jieba
from datasketch import MinHash, MinHashLSH

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.minhash")
class MinhashDeduper:
    """
    内容指纹去重：

    1. jieba 分词 → 对词序列做 3-gram
    2. datasketch MinHash 生成 128 维签名
    3. datasketch MinHashLSH 索引，只比较同桶文档
    4. Jaccard 相似度 > threshold 视为重复

    去重策略：同簇内保留来源可信度最高的那条（由上层评分决定）。
    """

    def __init__(self, threshold: float = config.DEDUP_MINHASH_THRESHOLD,
                 num_perm: int = 128):
        self.threshold = threshold
        self.num_perm = num_perm
        # LSH 索引：使用 MinHashLSH（内置 band 划分）
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._kept: list[NewsItem] = []
        self._signature_map: dict[int, tuple] = {}  # id -> minhash bytes

    def _tokenize(self, text: str) -> list[str]:
        """jieba 分词"""
        text = re.sub(r"<[^>]+>", " ", text)  # 去 HTML
        text = re.sub(r"\s+", " ", text).strip().lower()
        words = jieba.lcut(text)
        # 过滤单字和纯标点
        return [w for w in words if len(w) > 1 or w.isalnum()]

    def _shingle_words(self, words: list[str], k: int = 3) -> list[str]:
        """对词序列做 k-gram"""
        if len(words) < k:
            return [" ".join(words)]
        return [" ".join(words[i:i + k]) for i in range(len(words) - k + 1)]

    def _build_minhash(self, item: NewsItem) -> MinHash:
        """为单条新闻构建 MinHash 签名"""
        text = f"{item.title} {item.content}"
        words = self._tokenize(text)
        shingles = self._shingle_words(words)

        mh = MinHash(num_perm=self.num_perm)
        for s in shingles:
            mh.update(s.encode("utf-8"))
        return mh

    def is_duplicate(self, item: NewsItem) -> bool:
        """
        查询是否重复。
        返回 True = 重复（丢弃）。
        """
        mh = self._build_minhash(item)
        # LSH 查询：找同桶候选
        candidates = self._lsh.query(mh)
        if candidates:
            return True  # 有相似候补 → 判重

        # 无匹配 → 加入索引
        self._lsh.insert(len(self._kept), mh)
        self._kept.append(item)
        return False

    @property
    def count(self) -> int:
        return len(self._kept)


# ============================================================
# 阶段 C: 语义去重（Embedding + Union-Find 聚类）
# ============================================================
