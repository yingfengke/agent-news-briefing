"""entities.py - 从标题提取产品/型号标识，供同事件归组使用。

只认「含字母且含数字」的型号片段（V4.1-Flash-1017、Llama-4、GPT-5.2），
并把空格、连字符、下划线归一化，使下列写法得到同一个 key：
    V4.1-Flash-1017 / V4.1 Flash 1017 / v4_1_flash_1017  ->  v4.1flash1017

规则细节：
- 连字符连接的部分视为同一型号（Llama-4 不能只剩 "4"）；
- 空格分隔的纯字母前缀视为厂商/产品名，不参与 key（DeepSeek V4.1 -> V4.1）；
- 纯数字（2026）、纯厂商名（OpenAI、Google）不会产生 key，避免过度归组。
"""
import re

_TOKEN = r"[A-Za-z0-9][A-Za-z0-9.\-]*"
_SEQ_RE = re.compile(rf"{_TOKEN}(?:[\s\-_]+{_TOKEN}){{0,3}}")


def _key_of(match_text: str) -> str:
    """把一个型号片段归一化；不符合要求返回空串。"""
    parts = re.split(r"([\s\-_]+)", match_text)
    # parts 形如 [token, sep, token, sep, ...]，token 在偶数位
    start = next((i for i in range(0, len(parts), 2)
                  if re.search(r"\d", parts[i])), None)
    if start is None:
        return ""
    # 向前回溯：若前一个分隔符是纯连字符，说明与左侧同属一个型号（Llama-4）
    while start >= 2:
        sep = parts[start - 1]
        if "-" in sep and not re.search(r"\s", sep):
            start -= 2
        else:
            break
    seq = "".join(parts[start:])
    if not (re.search(r"[A-Za-z]", seq) and re.search(r"\d", seq)):
        return ""
    key = re.sub(r"[\s\-_]", "", seq).lower()
    return key if len(key) >= 6 else ""


def extract_event_keys(title: str) -> set[str]:
    """返回标题中的产品/型号归一化标识集合。"""
    keys = set()
    for match in _SEQ_RE.finditer(title or ""):
        key = _key_of(match.group(0))
        if key:
            keys.add(key)
    return keys


def primary_key(title: str) -> str:
    """返回最长的一个标识作为主键；无型号时返回空串。"""
    keys = extract_event_keys(title)
    return max(keys, key=len) if keys else ""
