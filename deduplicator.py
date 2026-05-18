#!/usr/bin/env python3
"""
deduplicator.py — 智能过滤与去重系统 v2

4 阶段串联流水线：
  A. URL 去重（SHA256 持久化数据库）
  B. MinHash + LSH 内容指纹去重（datasketch + jieba 分词）
  C. Embedding 语义去重（BAAI/bge-large-zh-v1.5 + Union-Find 聚类）
  D. 来源可信度过滤（白名单/黑名单 + 信号评分）

数据流向：采集层 → 本模块 → AI 分析层

依赖:
  datasketch, jieba, numpy, scikit-learn, python-dotenv
"""

import hashlib
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import jieba
import numpy as np
from datasketch import MinHash, MinHashLSH

import config
from models import NewsItem, FilterReport


# ============================================================
# 阶段 A: URL 去重
# ============================================================

class UrlDeduper:
    """
    URL 去重：SHA256 持久化数据库。
    同时做当日去重和历史去重。
    """

    def __init__(self, db_path: str = config.URL_DB_FILE):
        self.db_path = db_path
        self._seen: set[str] = set()
        self._load()

    def _load(self):
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
            self._seen = set(data.get("urls", []))
        except (FileNotFoundError, json.JSONDecodeError):
            self._seen = set()

    def _save(self):
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"urls": [], "updated": datetime.now().isoformat()}
        data["urls"] = list(self._seen)
        data["updated"] = datetime.now().isoformat()
        with open(self.db_path, "w") as f:
            json.dump(data, f, ensure_ascii=False)

    def is_duplicate(self, item: NewsItem) -> bool:
        url_hash = hashlib.sha256(item.url.encode("utf-8")).hexdigest()
        if url_hash in self._seen:
            return True
        self._seen.add(url_hash)
        return False

    def flush(self):
        self._save()


# ============================================================
# 阶段 B: MinHash + LSH 内容指纹去重
# ============================================================

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

class SemanticDeduper:
    """
    语义去重：

    1. 调用硅基流动 BAAI/bge-large-zh-v1.5 Embedding API
    2. 用 title[:50] 作为缓存键，避免重复调用
    3. 用 Union-Find 做聚类，相似度 > 0.92 的合为一簇
    4. 每簇保留发布时间最早的那条
    5. 标注 "该消息被 N 家来源报道"

    Embedding 缓存持久化到 .embedding_cache.json，每天清一次。
    """

    def __init__(self, threshold: float = config.DEDUP_SEMANTIC_THRESHOLD):
        self.threshold = threshold
        self._cache: dict[str, list[float]] = {}
        self._cache_file = config.EMBEDDING_CACHE_FILE
        self._load_cache()

        # API 配置
        self._api_url = f"{config.API_BASE_URL.rstrip('/')}/v1/embeddings"
        self._headers = {
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
        }

    def _load_cache(self):
        """加载 Embedding 缓存"""
        try:
            with open(self._cache_file, "r") as f:
                self._cache = json.load(f)
            # 检查是否是今天的缓存（按文件修改时间）
            mtime = os.path.getmtime(self._cache_file)
            if datetime.fromtimestamp(mtime).date() < datetime.now().date():
                self._cache = {}  # 过期，清空
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self):
        """持久化缓存"""
        with open(self._cache_file, "w") as f:
            json.dump(self._cache, f, ensure_ascii=False)

    def _cache_key(self, item: NewsItem) -> str:
        """缓存键：标题前 50 字"""
        return item.title.strip()[:50]

    def _get_embedding(self, item: NewsItem) -> Optional[list[float]]:
        """获取 Embedding 向量（先查缓存，再调 API）"""
        key = self._cache_key(item)
        if key in self._cache:
            return self._cache[key]

        if not config.API_KEY:
            return None

        text = f"{item.title} {item.content}"[:512]
        payload = json.dumps({
            "model": config.EMBEDDING_MODEL,
            "input": text,
        }).encode("utf-8")

        try:
            req = Request(self._api_url, data=payload, headers=self._headers)
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            vec = result["data"][0]["embedding"]
            self._cache[key] = vec
            return vec
        except Exception as e:
            print(f"    [Embedding] {key[:30]}... {str(e)[:50]}")
            return None

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        a_np = np.array(a, dtype=np.float32)
        b_np = np.array(b, dtype=np.float32)
        norm_a = np.linalg.norm(a_np)
        norm_b = np.linalg.norm(b_np)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_np, b_np) / (norm_a * norm_b))

    def deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        语义去重主入口。

        1. 获取所有向量的 Embedding
        2. 用 Union-Find 聚类
        3. 每簇保留发布时间最早的
        4. 标注多源报道计数
        """
        if not items:
            return items

        n = len(items)
        # 获取 Embedding
        vectors: list[Optional[list[float]]] = []
        for i, it in enumerate(items):
            vec = self._get_embedding(it)
            vectors.append(vec)
            if (i + 1) % 10 == 0:
                print(f"    ... Embedding {i+1}/{n}")

        # 对成功获取到向量的构建聚类
        valid_indices = [i for i, v in enumerate(vectors) if v is not None]
        valid_vecs = [vectors[i] for i in valid_indices]

        if len(valid_indices) < 2:
            self._save_cache()
            return items

        # Union-Find 聚类
        parent = list(range(len(valid_indices)))
        cluster_sizes = [1] * len(valid_indices)

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx == ry:
                return
            if cluster_sizes[rx] < cluster_sizes[ry]:
                rx, ry = ry, rx
            parent[ry] = rx
            cluster_sizes[rx] += cluster_sizes[ry]

        # 分批计算相似度（避免 O(n²) 全量计算）
        batch_size = config.DEDUP_EMBEDDING_BATCH
        comparisons = 0
        for i in range(len(valid_indices)):
            for j in range(i + 1, len(valid_indices)):
                sim = self._cosine_similarity(valid_vecs[i], valid_vecs[j])
                comparisons += 1
                if sim > self.threshold:
                    union(i, j)

        print(f"    [语义去重] {n} 条 → 计算 {comparisons} 对相似度 → "
              f"{len(set(find(i) for i in range(len(valid_indices))))} 簇")

        # 按簇分组
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(valid_indices)):
            root = find(i)
            clusters[root].append(valid_indices[i])

        # 每簇保留一条，标注多源报道
        kept_indices = set()
        multi_source_map = {}  # kept_index -> cluster count

        for root, members in clusters.items():
            # 选发布时间最早的
            cluster_items = [(items[valid_indices[m]], valid_indices[m]) for m in members]
            cluster_items.sort(key=lambda x: x[0].published_at or x[0].crawled_at)
            best_item, best_idx = cluster_items[0]
            kept_indices.add(best_idx)
            if len(members) > 1:
                multi_source_map[best_idx] = len(members)

        # 保留未被 API 处理到的（API 失败的保守保留）
        for i in range(n):
            if vectors[i] is None:
                kept_indices.add(i)

        # 构建结果
        result = []
        for i, it in enumerate(items):
            if i in kept_indices:
                if i in multi_source_map:
                    count = multi_source_map[i]
                    it.content = it.content + f" [该消息被 {count} 家来源报道]"
                result.append(it)

        self._save_cache()
        return result


# ============================================================
# 阶段 D: 来源可信度过滤
# ============================================================

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
        """正文长度是否 > 200 字（基本门槛）"""
        return len(item.content) > 200

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

def run_pipeline(items: list[NewsItem]) -> FilterReport:
    """
    四层过滤管道。

    参数:
      items — 原始新闻列表

    返回:
      FilterReport — 各阶段统计 + 干净数据
    """
    report = FilterReport(total_input=len(items))
    if not items:
        return report

    # ---- A: URL 去重 ----
    print(f"\n  ── A. URL 去重 ──")
    url_deduper = UrlDeduper()
    after_a = []
    for it in items:
        if not url_deduper.is_duplicate(it):
            after_a.append(it)
        else:
            report.url_removed += 1
    url_deduper.flush()
    print(f"  {len(items)} → {len(after_a)} (去重 {report.url_removed} 条)")

    if not after_a:
        return report

    # ---- B: MinHash + LSH 内容指纹去重 ----
    print(f"\n  ── B. 内容指纹去重 (MinHash+LSH) ──")
    mh_deduper = MinhashDeduper()
    after_b = []
    for it in after_a:
        if not mh_deduper.is_duplicate(it):
            after_b.append(it)
        else:
            report.minhash_removed += 1
    print(f"  {len(after_a)} → {len(after_b)} (去重 {report.minhash_removed} 条)")

    if not after_b:
        return report

    # ---- C: 语义去重 (Embedding + Union-Find) ----
    print(f"\n  ── C. 语义去重 (Embedding+聚类) ──")
    semanticer = SemanticDeduper()
    after_c = semanticer.deduplicate(after_b)
    report.semantic_removed = len(after_b) - len(after_c)
    print(f"  {len(after_b)} → {len(after_c)} (去重 {report.semantic_removed} 条，含聚类标注)")

    if not after_c:
        return report

    # ---- D: 可信度过滤 ----
    print(f"\n  ── D. 来源可信度过滤 ──")
    filter_d = CredibilityFilter()
    after_d = [it for it in after_c if not filter_d.should_filter(it)]
    report.credibility_removed = len(after_c) - len(after_d)
    print(f"  {len(after_c)} → {len(after_d)} (过滤 {report.credibility_removed} 条)")

    report.total_output = len(after_d)
    report.remaining_items = after_d
    return report


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    from collector import collect_all
    raw = collect_all()
    report = run_pipeline(raw)
    report.print_report()
    print(f"\n  前 5 条保留新闻:")
    for it in report.remaining_items[:5]:
        tags = f" [{', '.join(it.tags)}]" if it.tags else ""
        print(f"  [{it.source}]{tags} {it.title[:60]}")
        if "多家来源报道" in it.content:
            print(f"     ⚡ {it.content[-30:]}")
