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
