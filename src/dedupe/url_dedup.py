"""url_dedup.py - 阶段 A: URL 去重（SHA256 持久化数据库）。
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.url")
class UrlDeduper:
    """
    URL 去重：SHA256 持久化数据库。
    同时做当日去重和历史去重。
    """

    def __init__(self, db_path: str = config.URL_DB_FILE, initial_set: set[str] | None = None):
        self.db_path = db_path
        self._seen: set[str] = set(initial_set) if initial_set else set()
        # 仅在 initial_set 为空时从文件加载
        if initial_set is None:
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
        # 原子写入：先写临时文件再 os.replace 替换目标，避免中途崩溃丢失去重库
        dir_name = os.path.dirname(self.db_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, self.db_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

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
