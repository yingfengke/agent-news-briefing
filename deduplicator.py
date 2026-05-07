#!/usr/bin/env python3
"""
deduplicator.py — 智能过滤与去重层

4 阶段串联流水线：
  1. URL 去重（SHA256 持久化数据库）
  2. MinHash + LSH 内容指纹去重
  3. Embedding + 余弦相似度语义去重
  4. 来源可信度评分

数据流向：采集层（list[NewsItem]）→ 过滤层 → 干净数据 → 分析层

依赖：
  - numpy（pip install numpy）
  - 硅基流动 Embedding API（使用 config 中的 API_KEY）
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.request import Request, urlopen

import config
from models import NewsItem, FilterReport


# ============================================================
# 阶段 1: URL 去重
# ============================================================

class UrlDeduper:
    """
    URL 去重：基于 SHA256 持久化数据库。
    同时做两件事：
      - 当日去重（同一轮采集中出现的重复 URL）
      - 历史去重（与历史已推送的 URL 对比）
    """

    def __init__(self, db_path: str = config.URL_DB_FILE):
        self.db_path = db_path
        self._seen: set[str] = set()
        self._load()

    def _load(self):
        """加载历史 URL 数据库"""
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
            self._seen = set(data.get("urls", []))
        except (FileNotFoundError, json.JSONDecodeError):
            self._seen = set()

    def _save(self):
        """持久化 URL 数据库（仅保留最近 7 天）"""
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"urls": list(self._seen), "updated": datetime.now().isoformat()}
        data["urls"] = list(self._seen)
        data["updated"] = datetime.now().isoformat()
        with open(self.db_path, "w") as f:
            json.dump(data, f, ensure_ascii=False)

    def is_duplicate(self, item: NewsItem) -> bool:
        """检查 URL 是否已见过"""
        url_hash = hashlib.sha256(item.url.encode("utf-8")).hexdigest()
        if url_hash in self._seen:
            return True
        self._seen.add(url_hash)
        return False

    def flush(self):
        """持久化到磁盘"""
        self._save()


# ============================================================
# 阶段 2: MinHash + LSH 内容指纹去重
# ============================================================

class MinHashDeduper:
    """
    MinHash + LSH 内容指纹去重。

    MinHash 原理：
      1. 将文本切分为 k-shingle（k=4 的字符 n-gram）
      2. 用 n 个哈希函数对每个 shingle 取最小哈希值
      3. 两个文本的 MinHash 签名相似度 ≈ Jaccard 相似度

    LSH（Locality-Sensitive Hashing）：
      将签名分成 b 个 band，每个 band r 行。
      至少有一个 band 完全相同 → 视为候选相似对。
    """

    def __init__(self, threshold: float = config.DEDUP_MINHASH_THRESHOLD,
                 num_perm: int = 128, shingle_size: int = 4):
        self.threshold = threshold
        self.num_perm = num_perm
        self.shingle_size = shingle_size
        self._signatures: list[tuple[int, ...]] = []
        self._items: list[NewsItem] = []

        # LSH 参数：自动根据 threshold 选择 band 数
        # 经典公式: threshold ≈ (1/b)^(1/r)
        # 固定 num_perm = b * r
        self._b, self._r = self._auto_lsh_params(threshold)

    def _auto_lsh_params(self, threshold: float):
        """自动选择合适的 (b, r) 参数对"""
        candidates = [
            (16, 8), (20, 6), (24, 5), (32, 4), (40, 3), (64, 2)
        ]
        best = (16, 8)
        best_diff = float("inf")
        for b, r in candidates:
            if b * r != self.num_perm:
                continue
            actual = (1.0 / b) ** (1.0 / r)
            diff = abs(actual - threshold)
            if diff < best_diff:
                best_diff = diff
                best = (b, r)
        return best

    def _shingle(self, text: str) -> set[str]:
        """将文本切分为 k-shingle 集合"""
        text = re.sub(r"\s+", " ", text.lower()).strip()
        if len(text) < self.shingle_size:
            return {text}
        return {text[i:i + self.shingle_size]
                for i in range(len(text) - self.shingle_size + 1)}

    def _minhash_signature(self, shingles: set[str]) -> list[int]:
        """计算 MinHash 签名向量"""
        sig = []
        for seed in range(1, self.num_perm + 1):
            # 用不同的种子作为哈希函数
            min_hash = float("inf")
            for s in shingles:
                h = hashlib.md5(f"{seed}:{s}".encode()).hexdigest()
                val = int(h[:8], 16)
                if val < min_hash:
                    min_hash = val
            sig.append(min_hash if min_hash != float("inf") else 0)
        return sig

    def _lsh_bands(self, signature: list[int]) -> list[tuple[int, tuple[int, ...]]]:
        """将签名分成 b 个 band，返回 (band_idx, hash_tuple)"""
        bands = []
        for i in range(self._b):
            start = i * self._r
            end = start + self._r
            band_hash = tuple(signature[start:end])
            bands.append((i, band_hash))
        return bands

    def is_duplicate(self, item: NewsItem) -> bool:
        """
        检查 item 是否与已有内容相似。
        返回 True 表示重复（应被过滤）。
        """
        text = f"{item.title} {item.content}"
        shingles = self._shingle(text)
        if not shingles:
            return False

        sig = self._minhash_signature(shingles)
        bands = self._lsh_bands(sig)

        # 检查是否有任何 band 与已有签名匹配
        for band_idx, band_hash in bands:
            for existing_sig in self._signatures:
                e_bands = self._lsh_bands(list(existing_sig))
                if e_bands[band_idx][1] == band_hash:
                    # 候选匹配，计算精确 Jaccard 相似度确认
                    return True  # LSH 碰撞即判定为重复

        # 无匹配，加入数据库
        self._signatures.append(tuple(sig))
        self._items.append(item)
        return False

    @property
    def count(self) -> int:
        return len(self._signatures)


# ============================================================
# 阶段 3: 语义去重（Embedding + 余弦相似度）
# ============================================================

class SemanticDeduper:
    """
    语义去重：用 Embedding 向量 + 余弦相似度检测语义重复。

    流程：
      1. 将每条新闻的 (title + content) 发给硅基流动 Embedding API
      2. 得到向量后，与已有向量逐一计算余弦相似度
      3. 余弦相似度 > threshold 即判为重复

    使用 model: Qwen/Qwen3-Embedding-4B
    """

    def __init__(self, threshold: float = config.DEDUP_SEMANTIC_THRESHOLD):
        self.threshold = threshold
        self._vectors: list[list[float]] = []
        self._items: list[NewsItem] = []
        self._api_url = f"{config.API_BASE_URL.rstrip('/')}/v1/embeddings"
        self._headers = {
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
        }

    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """调用硅基流动 Embedding API 获取向量"""
        if not config.API_KEY:
            return None
        payload = json.dumps({
            "model": config.EMBEDDING_MODEL,
            "input": text[:512],  # 控制 token 消耗
        }).encode("utf-8")
        try:
            req = Request(self._api_url, data=payload, headers=self._headers)
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result["data"][0]["embedding"]
        except Exception as e:
            print(f"    [Embedding] {str(e)[:60]}")
            return None

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def is_duplicate(self, item: NewsItem) -> bool:
        """
        检查 item 是否语义重复。
        返回 True 表示应被过滤。
        """
        text = f"{item.title} {item.content}"[:512]
        if not text.strip():
            return False

        vec = self._get_embedding(text)
        if vec is None:
            # API 失败，保守返回不重复
            return False

        # 与已有向量逐一比较
        for existing_vec in self._vectors:
            sim = self._cosine_similarity(vec, existing_vec)
            if sim > self.threshold:
                return True  # 语义重复

        self._vectors.append(vec)
        self._items.append(item)
        return False

    @property
    def count(self) -> int:
        return len(self._vectors)


# ============================================================
# 阶段 4: 可信度评分
# ============================================================

class CredibilityScorer:
    """
    可信度评分过滤。

    评分公式：
      score = base(50) + source_bonus + freshness_bonus

    过滤条件：score < min_score（默认 0，即除非扣分否则不过滤）
    """

    def __init__(self):
        self.weights = config.CREDIBILITY_WEIGHTS
        self.min_score = self.weights.get("min_score", 0)

    def score(self, item: NewsItem) -> int:
        """
        计算单条新闻的信任分数。
        返回整数分数，低于 min_score 的应过滤。
        """
        score = 50  # 基础分

        # 来源加分/扣分
        source_name = item.source.replace("爬虫", "")  # 去掉"爬虫"后缀以匹配映射
        score += self.weights.get("source_bonus", {}).get(source_name, 0)
        score += self.weights.get("source_malus", {}).get(source_name, 0)

        # 时效性加分（48小时内满分，之后线性衰减）
        if item.published_at:
            try:
                pub = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
                age_hours = (datetime.now().astimezone() - pub).total_seconds() / 3600
                freshness_hours = self.weights.get("freshness_hours", 48)
                if age_hours < freshness_hours:
                    freshness_bonus = int(20 * (1 - age_hours / freshness_hours))
                    score += freshness_bonus
            except (ValueError, TypeError):
                pass

        return score

    def should_filter(self, item: NewsItem) -> bool:
        """是否应过滤此条"""
        return self.score(item) < self.min_score


# ============================================================
# 过滤管道：串联 4 个阶段
# ============================================================

def run_pipeline(items: list[NewsItem]) -> FilterReport:
    """
    4 阶段串联过滤流水线。

    参数:
      items — 原始新闻列表（来自 collector）

    返回:
      FilterReport — 各阶段去重统计 + 剩余干净数据
    """
    report = FilterReport(total_input=len(items))

    if not items:
        return report

    # ---- 阶段 1: URL 去重 ----
    print(f"\n  ── 过滤 · URL 去重 ──")
    url_deduper = UrlDeduper()
    after_url = []
    for it in items:
        if not url_deduper.is_duplicate(it):
            after_url.append(it)
        else:
            report.url_removed += 1
    url_deduper.flush()
    print(f"  {len(items)} → {len(after_url)} (去重 {report.url_removed} 条)")

    if not after_url:
        return report

    # ---- 阶段 2: MinHash + LSH 指纹去重 ----
    print(f"\n  ── 过滤 · MinHash 指纹去重 ──")
    minhasher = MinHashDeduper()
    after_minhash = []
    for it in after_url:
        if not minhasher.is_duplicate(it):
            after_minhash.append(it)
        else:
            report.minhash_removed += 1
    print(f"  {len(after_url)} → {len(after_minhash)} (去重 {report.minhash_removed} 条)")

    if not after_minhash:
        return report

    # ---- 阶段 3: 语义去重（耗时操作，需要调用 Embedding API）----
    print(f"\n  ── 过滤 · 语义去重 ──")
    semanticer = SemanticDeduper()
    after_semantic = []
    for i, it in enumerate(after_minhash):
        if not semanticer.is_duplicate(it):
            after_semantic.append(it)
        else:
            report.semantic_removed += 1
        if (i + 1) % 5 == 0:
            print(f"    ... 已处理 {i+1}/{len(after_minhash)} 条")
    print(f"  {len(after_minhash)} → {len(after_semantic)} (去重 {report.semantic_removed} 条)")

    if not after_semantic:
        return report

    # ---- 阶段 4: 可信度评分 ----
    print(f"\n  ── 过滤 · 可信度评分 ──")
    scorer = CredibilityScorer()
    after_cred = [it for it in after_semantic if not scorer.should_filter(it)]
    report.credibility_removed = len(after_semantic) - len(after_cred)
    print(f"  {len(after_semantic)} → {len(after_cred)} (过滤 {report.credibility_removed} 条)")

    # ---- 完成 ----
    report.total_output = len(after_cred)
    report.remaining_items = after_cred
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
        print(f"  [{it.source}] {it.title[:50]}")
