"""测试失败主动告警（send_failure_alert）"""
import sys, os
import tempfile
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import config
from src.delivery.send_email import (
    send_failure_alert, send_quality_alert, _strip_urls,
)


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
    with patch("src.delivery.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.delivery.send_email.os.path.exists", return_value=False), \
         patch("src.delivery.send_email.os.makedirs"), \
         patch("src.delivery.send_email.open", create=True):
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
    with patch("src.delivery.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.delivery.send_email.LOGS_DIR", tmp_marker_dir), \
         patch("src.delivery.send_email.os.path.exists", return_value=False), \
         patch("src.delivery.send_email.os.makedirs"), \
         patch("src.delivery.send_email.open", create=True):
        ok1 = send_failure_alert(RuntimeError("x"))
    assert ok1 is True
    assert calls["n"] == 1

    # 第二次：marker 已存在 -> 跳过，不再发信
    with patch("src.delivery.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.delivery.send_email.LOGS_DIR", tmp_marker_dir), \
         patch("src.delivery.send_email.os.path.exists", return_value=True), \
         patch("src.delivery.send_email.os.makedirs"), \
         patch("src.delivery.send_email.open", create=True):
        ok2 = send_failure_alert(RuntimeError("x"))
    assert ok2 is False
    assert calls["n"] == 1  # 仍是 1 次


def test_send_quality_alert_no_issues_no_mail():
    """无异常项时不应发信（避免无意义骚扰）。"""
    assert send_quality_alert([]) is False


def test_send_quality_alert_plain_text_with_issues():
    """质量提醒为纯文本、列出异常项、标题区别于失败告警。"""
    from email import message_from_string
    from email.header import decode_header
    fake_server = MagicMock()
    with patch("src.delivery.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.delivery.send_email.os.path.exists", return_value=False), \
         patch("src.delivery.send_email.os.makedirs"), \
         patch("src.delivery.send_email.open", create=True):
        sent = {}
        fake_server.__enter__.return_value.sendmail.side_effect = \
            lambda frm, to, msg_str: sent.update(msg=msg_str)
        ok = send_quality_alert(["最终新闻仅 2 条", "本期无 GitHub Trending 项目推荐"],
                                summary="指标: 新闻 2 条")
        assert ok is True
        m = message_from_string(sent["msg"])
        body = m.get_payload(decode=True).decode("utf-8")
        assert m.get_content_type() == "text/plain"
        assert "最终新闻仅 2 条" in body
        assert "Trending" in body
        assert "指标: 新闻 2 条" in body
        # 纯文本、无裸链接
        assert "<html" not in body.lower()
        assert "https://" not in sent["msg"]
        # 标题为「提醒」而非「告警」，与失败告警区分
        subject = str(decode_header(m["Subject"])[0][0], "utf-8") \
            if isinstance(decode_header(m["Subject"])[0][0], bytes) else m["Subject"]
        assert "提醒" in subject


def test_quality_and_failure_alerts_use_separate_markers(tmp_path):
    """两类告警各用各的 marker：质量提醒不应被失败告警的 marker 吞掉。"""
    import glob
    calls = {"n": 0}
    fake_server = MagicMock()
    fake_server.__enter__.return_value.sendmail.side_effect = \
        lambda *a, **k: calls.update(n=calls["n"] + 1)

    with patch("src.delivery.send_email.smtplib.SMTP_SSL", return_value=fake_server), \
         patch("src.delivery.send_email.LOGS_DIR", str(tmp_path)), \
         patch("src.delivery.send_email.os.makedirs"):
        assert send_failure_alert(RuntimeError("x")) is True
        assert send_quality_alert(["问题 A"]) is True
    assert calls["n"] == 2
    markers = sorted(os.path.basename(p) for p in glob.glob(os.path.join(str(tmp_path), "*.sent")))
    assert len(markers) == 2
    assert any(m.startswith("alert-") for m in markers)
    assert any(m.startswith("quality-") for m in markers)


if __name__ == "__main__":
    test_strip_urls_removes_links()
    test_send_failure_alert_plain_text_no_html()
    test_send_failure_alert_marker_dedup()
    test_send_quality_alert_no_issues_no_mail()
    test_send_quality_alert_plain_text_with_issues()
    print("All send_email tests passed!")
