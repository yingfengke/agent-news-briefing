"""HTTP 异常信息提取测试。"""
import io
from urllib.error import HTTPError

from src.core.http_utils import http_error_detail


def test_http_error_includes_status_and_body():
    err = HTTPError("https://api.example/v1/chat", 400, "Bad Request", {},
                    io.BytesIO(b'{"code":20012,"message":"Model does not exist"}'))
    detail = http_error_detail(err)
    assert "400" in detail
    assert "Model does not exist" in detail


def test_http_error_without_body_still_reports_code():
    err = HTTPError("https://api.example", 429, "Too Many Requests", {}, None)
    assert "429" in http_error_detail(err)


def test_plain_exception_reports_type_and_message():
    detail = http_error_detail(TimeoutError("read operation timed out"))
    assert "TimeoutError" in detail
    assert "timed out" in detail
