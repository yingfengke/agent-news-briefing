"""
logger.py — 集中式日志系统

提供:
  - 控制台输出（INFO 及以上）
  - 每日日志文件（logs/briefing-YYYY-MM-DD.log）
  - 结构化日志记录（JSON 格式 key=value 行）

用法:
  from src.core.logger import get_logger
  log = get_logger(__name__)
  log.info("采集完成: %d 条", count)
  log.warning("API 调用失败: %s", err)
  log.error("发送邮件出错")
"""

import logging
import os
import sys
import time
from datetime import datetime

# 日志目录
LOGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
)


def _ensure_logs_dir():
    """确保日志目录存在"""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR, exist_ok=True)


def _daily_log_path() -> str:
    """返回今日日志文件路径"""
    _ensure_logs_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOGS_DIR, f"briefing-{today}.log")


# 日志格式
_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志记录器缓存
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str = __name__) -> logging.Logger:
    """
    获取或创建日志记录器。

    首次调用时自动配置控制台处理器和文件处理器。
    后续调用复用已有记录器。
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 防止重复添加处理器
    if logger.handlers:
        _loggers[name] = logger
        return logger

    # 控制台处理器（INFO 及以上）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    # 文件处理器（DEBUG 及以上，每日轮转）
    file_handler = logging.FileHandler(_daily_log_path(), encoding="utf-8", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger


def log_structured(logger: logging.Logger, level: int, event: str, **kwargs):
    """
    记录结构化日志，格式为:
      [EVENT] key1=value1 key2=value2 ...

    示例:
      log_structured(log, logging.INFO, "collect_complete",
                     sources=21, items=156, duration_s=45.2)
    """
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.log(level, "[%s] %s", event, extra)


class Timeline:
    """流水线阶段计时器。

    用法:
      tl = Timeline()
      tl.mark("采集", "rss_fetch", "ok", "36源 128条")
      ...
      tl.summary(log)          # 打印各阶段耗时汇总
      data = tl.to_dict()      # 供写入 JSON 摘要

    每两次 mark 之间的间隔即为上一阶段的耗时（首次以构造时刻为起点）。
    """

    def __init__(self):
        self._t0 = time.perf_counter()
        self._marks: list[dict] = []

    def mark(self, stage: str, action: str, status: str = "ok", detail: str = ""):
        """记录一个阶段完成点。status 约定 ok / skipped / failed / degraded。"""
        self._marks.append({
            "stage": stage,
            "action": action,
            "status": status,
            "detail": detail,
            "at": round(time.perf_counter() - self._t0, 2),
        })

    def elapsed(self) -> float:
        """从构造到当前的秒数。"""
        return round(time.perf_counter() - self._t0, 2)

    def failures(self) -> list[dict]:
        """返回非 ok 状态的阶段记录（failed / degraded）。"""
        return [m for m in self._marks if m.get("status") not in ("ok", "skipped")]

    def _rows(self) -> list[dict]:
        prev, rows = 0.0, []
        for m in self._marks:
            rows.append({**m, "cost_s": round(m["at"] - prev, 2)})
            prev = m["at"]
        return rows

    def summary(self, logger: logging.Logger | None = None) -> list[dict]:
        """打印各阶段耗时汇总表，返回带 cost_s 的记录列表。"""
        rows = self._rows()
        lines = ["", "=== Pipeline Timeline ==="]
        for r in rows:
            detail = f" {r['detail']}" if r["detail"] else ""
            lines.append("  {stage} | {action} | {status} | {cost}s{detail}".format(
                stage=r["stage"], action=r["action"],
                status=r["status"], cost=r["cost_s"], detail=detail,
            ))
        failed = len(self.failures())
        lines.append(f"  总计 {self.elapsed()}s | 异常阶段 {failed} 个")
        if logger:
            logger.info("\n".join(lines))
        return rows

    def to_dict(self) -> dict:
        """返回可序列化的汇总数据。"""
        rows = self._rows()
        return {
            "total_s": self.elapsed(),
            "failed_stages": [m["action"] for m in self.failures()],
            "stages": rows,
        }
