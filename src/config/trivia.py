"""
AI 冷知识 / 编程笑话（彩蛋角落）

数据从 trivia.json 加载，实现代码与数据的分离。
"""

import json
import os

_TRIVIA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trivia.json")

with open(_TRIVIA_FILE, "r", encoding="utf-8") as _f:
    AI_TRIVIA = json.load(_f)
