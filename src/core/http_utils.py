"""http_utils.py - HTTP 异常信息提取。

urllib 的 HTTPError 只把状态码写进 str()（如 "HTTP Error 400: Bad Request"），
API 返回的错误体被丢掉，日志里看不到「模型不存在」「限流」「余额不足」等真实原因。
小模型调用失败时必须把响应体一并打出，否则只能靠猜。
"""
from urllib.error import HTTPError


def http_error_detail(exc: Exception, limit: int = 200) -> str:
    """把异常转成可读描述：HTTPError 附带响应体，其余附异常类型与消息。"""
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8", "ignore").strip()
        except Exception:
            body = ""
        detail = f"HTTP {exc.code}"
        if body:
            detail += f" {body[:limit]}"
        return detail
    return f"{type(exc).__name__}: {str(exc)[:limit]}"
