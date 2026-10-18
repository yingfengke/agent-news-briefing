"""主模型接入点选择测试：DeepSeek 官方 vs 通用网关。"""
from src import config
from src.analysis import invoke as I


def test_main_model_uses_official_endpoint(monkeypatch):
    """配了主模型密钥时，主模型走 DeepSeek 官方并显式关闭 thinking。"""
    monkeypatch.setattr(config, "MODEL_NAME", "deepseek-flash")
    monkeypatch.setattr(config, "MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-official")

    url, key, extra = I._endpoint_for("deepseek-flash")
    assert url == "https://api.deepseek.com/chat/completions"
    assert key == "sk-official"
    # 默认开启 thinking，必须显式关闭，否则输出 token 成本翻倍
    assert extra == {"thinking": {"type": "disabled"}}


def test_fallback_model_uses_gateway(monkeypatch):
    """兜底模型不在官方接入点，仍走通用网关，且不传 thinking 参数。"""
    monkeypatch.setattr(config, "MODEL_NAME", "deepseek-flash")
    monkeypatch.setattr(config, "MODEL_API_KEY", "sk-official")
    monkeypatch.setattr(config, "API_BASE_URL", "https://api.siliconflow.cn")
    monkeypatch.setattr(config, "API_KEY", "sk-gateway")

    url, key, extra = I._endpoint_for("Pro/zai-org/GLM-5.1")
    assert url == "https://api.siliconflow.cn/v1/chat/completions"
    assert key == "sk-gateway"
    assert extra == {}


def test_main_model_falls_back_to_gateway_without_official_key(monkeypatch):
    """未配置主模型密钥时回落到通用网关，保证旧部署不至于直接失效。"""
    monkeypatch.setattr(config, "MODEL_NAME", "deepseek-flash")
    monkeypatch.setattr(config, "MODEL_API_KEY", "")
    monkeypatch.setattr(config, "API_BASE_URL", "https://api.siliconflow.cn")
    monkeypatch.setattr(config, "API_KEY", "sk-gateway")

    url, key, extra = I._endpoint_for("deepseek-flash")
    assert url == "https://api.siliconflow.cn/v1/chat/completions"
    assert key == "sk-gateway"
    assert extra == {}
