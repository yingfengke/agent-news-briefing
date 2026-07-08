"""测试失败主动告警（send_failure_alert）"""
import sys, os
import tempfile
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config
from src.send_email import send_failure_alert, _strip_urls


def test_strip_urls_removes_links():
    """告警正文不得含裸 URL，避免 QQ 邮箱屏蔽（⑤）。"""
    text = '错误见 https://github.com/x/y 或 http://a.b/c?d=1 结束'
    out = _strip_urls(text)
    assert "https://" not in out
    assert "http://" not in out
    assert "(链接已省略)" in out


def test_send_failure_alert_plain_text_no_html():
    """告警邮件为纯文本、无 HTML、发信成功并返回 True（⑤）。"""
    from email import message_from_string
    fake_server = MagicMock()
    with patch("src.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.send_email.os.path.exists", return_value=False), \
         patch("src.send_email.os.makedirs"), \
         patch("src.send_email.open", create=True):
        sent = {}
        def fake_sendmail(frm, to, msg_str):
            sent["msg"] = msg_str
        fake_server.__enter__.return_value.sendmail.side_effect = fake_sendmail
        ok = send_failure_alert(RuntimeError("boom"), phase="生成")
        assert ok is True
        msg_str = sent["msg"]
        # 反序列化，验证解码后的正文（MIME 会对中文做传输编码）
        m = message_from_string(msg_str)
        body = m.get_payload(decode=True).decode("utf-8")
        assert m.get_content_type() == "text/plain"
        # 无 HTML 标签、无可点击链接（URL 被 _strip_urls 替换）
        assert "<html" not in body.lower()
        assert "https://" not in msg_str
        assert "boom" in body
        assert "生成" in body


def test_send_failure_alert_marker_dedup():
    """当日 marker 存在时不应重复发信（避免 workflow retry 重复告警）。"""
    calls = {"n": 0}
    fake_server = MagicMock()
    fake_server.__enter__.return_value.sendmail.side_effect = lambda *a, **k: calls.update(n=calls["n"] + 1)

    tmp_marker_dir = tempfile.mkdtemp()
    marker_path = os.path.join(tmp_marker_dir, "alert-20260708.sent")

    # 第一次：marker 不存在 -> 发信
    with patch("src.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.send_email.LOGS_DIR", tmp_marker_dir), \
         patch("src.send_email.os.path.exists", return_value=False), \
         patch("src.send_email.os.makedirs"), \
         patch("src.send_email.open", create=True):
        ok1 = send_failure_alert(RuntimeError("x"))
    assert ok1 is True
    assert calls["n"] == 1

    # 第二次：marker 已存在 -> 跳过，不再发信
    with patch("src.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.send_email.LOGS_DIR", tmp_marker_dir), \
         patch("src.send_email.os.path.exists", return_value=True), \
         patch("src.send_email.os.makedirs"), \
         patch("src.send_email.open", create=True):
        ok2 = send_failure_alert(RuntimeError("x"))
    assert ok2 is False
    assert calls["n"] == 1  # 仍是 1 次


if __name__ == "__main__":
    test_strip_urls_removes_links()
    test_send_failure_alert_plain_text_no_html()
    test_send_failure_alert_marker_dedup()
    print("All send_email tests passed!")
