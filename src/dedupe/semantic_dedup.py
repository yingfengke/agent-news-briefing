"""semantic_dedup.py - 阶段 C: Embedding 语义去重（Qwen Embedding + Union-Find 聚类）。
"""
import json
import time
from typing import Optional
from datetime import datetime
from urllib.request import Request, urlopen

import numpy as np

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.semantic")
class SemanticDeduper:
    """
    语义去重：

    1. 调用硅基流动 Qwen/Qwen3-Embedding-4B Embedding API
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

    def _get_embeddings_batch(self, items: list[NewsItem]) -> list[Optional[list[float]]]:
        """
        批量获取 Embedding 向量（优先查缓存，不足的批量调 API）。
        将 O(n) 次 API 调用降低为 O(n/batch_size) 次。
        """
        n = len(items)
        keys = [self._cache_key(it) for it in items]
        results: list[Optional[list[float]]] = []

        # 先查缓存
        uncached_indices: list[int] = []
        for i, key in enumerate(keys):
            if key in self._cache:
                results.append(self._cache[key])
            else:
                results.append(None)
                uncached_indices.append(i)

        if not uncached_indices:
            return results

        if not config.API_KEY:
            return results

        # 分批调用 API
        for batch_start in range(0, len(uncached_indices), config.DEDUP_EMBEDDING_BATCH):
            batch_ids = uncached_indices[batch_start:batch_start + config.DEDUP_EMBEDDING_BATCH]
            batch_texts = [
                (f"{items[idx].title} {items[idx].content}")[:512]
                for idx in batch_ids
            ]

            payload = json.dumps({
                "model": config.EMBEDDING_MODEL,
                "input": batch_texts,
            }).encode("utf-8")

            try:
                req = Request(self._api_url, data=payload, headers=self._headers)
                with urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

                for j, idx in enumerate(batch_ids):
                    vec = result["data"][j]["embedding"]
                    self._cache[keys[idx]] = vec
                    results[idx] = vec
            except Exception as e:
                log.warning("Embedding 批失败 (第1次): %s", str(e)[:50])
                # 重试一次
                try:
                    time.sleep(3)
                    req2 = Request(self._api_url, data=payload, headers=self._headers)
                    with urlopen(req2, timeout=30) as resp2:
                        result2 = json.loads(resp2.read().decode("utf-8"))
                    for j, idx in enumerate(batch_ids):
                        vec2 = result2["data"][j]["embedding"]
                        self._cache[keys[idx]] = vec2
                        results[idx] = vec2
                except Exception as e2:
                    log.warning("Embedding 批失败 (重试后): %s", str(e2)[:50])
                    # API 失败的项保留 None，不会被聚类丢弃

            processed = min(batch_start + config.DEDUP_EMBEDDING_BATCH, len(uncached_indices))
            if processed % (config.DEDUP_EMBEDDING_BATCH * 2) == 0:
                log.info("  ... Embedding %d/%d", processed, len(uncached_indices))

        return results

    def deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        """
        语义去重主入口。

        1. 批量获取所有向量的 Embedding
        2. 用 numpy 矩阵乘法一次性计算所有余弦相似度
        3. 用 Union-Find 聚类
        4. 每簇保留发布时间最早的
        5. 标注多源报道计数
        """
        if not items:
            return items

        n = len(items)
        log.info("  [语义去重] 获取 %d 条 Embedding ...", n)

        # 批量获取 Embedding（减少 API 调用次数）
        vectors = self._get_embeddings_batch(items)

        # 对成功获取到向量的构建聚类
        valid_indices = [i for i, v in enumerate(vectors) if v is not None]
        valid_vecs = [vectors[i] for i in valid_indices]

        if len(valid_indices) < 2:
            self._save_cache()
            return items

        # numpy 矩阵乘法一次性计算所有余弦相似度
        valid_vecs_np = np.array(valid_vecs, dtype=np.float32)
        norms = np.linalg.norm(valid_vecs_np, axis=1, keepdims=True)
        norms[norms == 0] = 1  # 避免除零
        normed = valid_vecs_np / norms
        sim_matrix = normed @ normed.T  # 全量余弦相似度矩阵

        # Union-Find 聚类
        m = len(valid_indices)
        parent = list(range(m))
        cluster_sizes = [1] * m

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

        # 遍历上三角矩阵，合并相似项
        comparisons = 0
        for i in range(m):
            for j in range(i + 1, m):
                if sim_matrix[i][j] > self.threshold:
                    union(i, j)
                comparisons += 1

        log.info("  [语义去重] %d 条 -> 矩阵 %dx%d = %d 对 -> %d 簇",
                  n, m, m, comparisons, len(set(find(i) for i in range(m))))

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
