"""semantic_dedup.py - 阶段 C: Embedding 语义去重（召回候选 + 重排精判 + Union-Find 聚类）。
"""
import json
import os
import time
from typing import Optional
from datetime import datetime
from urllib.request import Request, urlopen
from collections import defaultdict

import numpy as np

from src import config
from src.analysis.event_cluster import SAME_EVENT_THRESHOLD, rerank_pair
from src.core.http_utils import http_error_detail
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.semantic")


def _distinct_sources(sources: list[str]) -> list[str]:
    return sorted({s.strip() for s in sources if s and s.strip()})


def _build_multi_source_note(sources: list[str]) -> str:
    """生成多源报道标注（带具体来源名单，方便读者判断可信度）：
    [该消息被 2 家来源报道：36氪、量子位]
    来源全部为空时退化为仅数量（"多家"），不编造名单。
    """
    names = _distinct_sources(sources)
    if not names:
        return " [该消息被多家来源报道]"
    return f" [该消息被 {len(names)} 家来源报道：{'、'.join(names)}]"


class SemanticDeduper:
    """
    语义去重：

    1. 调用 Embedding API 取全量向量（title + content[:512]）
    2. 用 title[:50] 作为缓存键，避免重复调用
    3. 余弦相似度只用来召回候选对（门槛见 DEDUP_SEMANTIC_THRESHOLD）
    4. 候选对由重排模型按【标题】双向精判，确属同一事件才合为一簇
    5. 每簇保留发布时间最早的那条，标注 "该消息被 N 家来源报道"
       并写入 source_count，供下游跨期冷却判断信息增量

    只用标题做精判：拼上摘要会让重排模型退化成主题相关性检测器，
    把「同厂商的不同事件」判成同一件（实测 0.999 vs 纯标题 0.006）。
    精判不可用时本层零合并，保持条目原样，不阻断主流程。

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
        """加载 Embedding 缓存。

        缓存按模型隔离：不同模型的向量处在不同语义空间，混用会算出无意义的
        相似度。旧版缓存是扁平 {标题: 向量}，没有模型标识，一律丢弃。
        """
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            self._cache = {}
            return

        if not isinstance(data, dict) or "vectors" not in data:
            self._cache = {}
            return
        if data.get("model") != config.EMBEDDING_MODEL:
            log.info("  [语义去重] 缓存模型 %s 与当前 %s 不一致，丢弃缓存",
                     data.get("model"), config.EMBEDDING_MODEL)
            self._cache = {}
            return

        # 检查是否是今天的缓存（按文件修改时间）
        try:
            if datetime.fromtimestamp(os.path.getmtime(self._cache_file)).date() < datetime.now().date():
                self._cache = {}
                return
        except OSError:
            pass
        self._cache = data.get("vectors") or {}

    def _save_cache(self):
        """持久化缓存（带模型标识，供下次启动校验）"""
        with open(self._cache_file, "w", encoding="utf-8") as f:
            json.dump({"model": config.EMBEDDING_MODEL, "vectors": self._cache},
                      f, ensure_ascii=False)

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
            log.warning("  [语义去重] 仅 %d/%d 条取得向量，本层跳过（条目全部保留）",
                        len(valid_indices), n)
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

        # 遍历上三角矩阵，保留全部分数用于观察分布
        scored_pairs: list[tuple[float, int, int]] = []
        for i in range(m):
            for j in range(i + 1, m):
                scored_pairs.append((float(sim_matrix[i][j]), i, j))
        scored_pairs.sort(reverse=True)
        comparisons = len(scored_pairs)

        # 余弦分数只负责召回，是否同一事件交给重排模型按【标题】精判。
        # 实测 bge-m3 上同事件（0.656~0.847）与同主题不同事件（0.639~0.760）
        # 大面积重叠，任何单一阈值都会同时漏判与误合并。
        candidates = [p for p in scored_pairs if p[0] >= self.threshold]
        pending: list[tuple[int, int]] = []
        linked = list(range(m))

        def linked_find(x):
            while linked[x] != x:
                linked[x] = linked[linked[x]]
                x = linked[x]
            return x

        judged = 0
        for sim, i, j in candidates[:config.DEDUP_RERANK_MAX_PAIRS]:
            if linked_find(i) == linked_find(j):
                continue
            ta = items[valid_indices[i]].title or ""
            tb = items[valid_indices[j]].title or ""
            try:
                score = rerank_pair(ta, tb)
            except Exception as e:
                log.warning("  [语义去重] 重排判定不可用 (%s)，本层保持不合并",
                            http_error_detail(e))
                pending = []
                break
            judged += 1
            hit = score >= SAME_EVENT_THRESHOLD
            log.info("  [语义去重] 精判 emb=%.3f rerank=%.3f %s | %s <-> %s",
                     sim, score, "合并" if hit else "保留", ta[:26], tb[:26])
            if hit:
                pending.append((i, j))
                ri, rj = linked_find(i), linked_find(j)
                linked[rj] = ri

        # 判定全部成功后一次性合并：中途失败则零合并，避免留下半截簇
        for i, j in pending:
            union(i, j)
        if judged:
            log.info("  [语义去重] 重排精判 %d 对 -> 合并 %d 对",
                     judged, len(pending))

        log.info("  [语义去重] %d 条 -> 矩阵 %dx%d = %d 对 -> %d 簇",
                  n, m, m, comparisons, len(set(find(i) for i in range(m))))

        # 相似度分布：换模型或调阈值时靠这几行判断，不要凭感觉改阈值
        if scored_pairs:
            log.info("  [语义去重] 最相似对 top%d（召回门槛 %.2f / 精判门槛 %.2f）:",
                     min(8, len(scored_pairs)), self.threshold, SAME_EVENT_THRESHOLD)
            for sim, i, j in scored_pairs[:8]:
                log.info("    %.3f | %s <-> %s", sim,
                         items[valid_indices[i]].title[:30],
                         items[valid_indices[j]].title[:30])

        # 按簇分组
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(valid_indices)):
            root = find(i)
            clusters[root].append(valid_indices[i])

        # 每簇保留一条，标注多源报道（成员名单按各自所属簇记录，避免跨簇串源）
        kept_indices = set()
        cluster_members: dict[int, list[int]] = {}

        for root, members in clusters.items():
            # 选发布时间最早的
            cluster_items = [(items[valid_indices[m]], valid_indices[m]) for m in members]
            cluster_items.sort(key=lambda x: x[0].published_at or x[0].crawled_at)
            best_item, best_idx = cluster_items[0]
            kept_indices.add(best_idx)
            if len(members) > 1:
                cluster_members[best_idx] = members

        # 保留未被 API 处理到的（API 失败的保守保留）
        for i in range(n):
            if vectors[i] is None:
                kept_indices.add(i)

        # 构建结果
        result = []
        for i, it in enumerate(items):
            if i in kept_indices:
                if i in cluster_members:
                    # 收集本簇所有成员的真实来源名，随数量一起写入 content
                    member_sources = [items[valid_indices[m]].source
                                      for m in cluster_members[i]]
                    it.content = it.content + _build_multi_source_note(member_sources)
                    it.source_count = max(1, len(_distinct_sources(member_sources)))
                result.append(it)

        self._save_cache()
        return result
