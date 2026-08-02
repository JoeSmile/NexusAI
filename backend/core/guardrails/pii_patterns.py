"""PII 脱敏模式

处理顺序必须先长后短、先特异后通用:
id_card / bank_card 先于 phone，否则身份证中的 11 位数字段会被 phone 吃掉。
"""

# dict 保序(Python 3.7+)；input_guard 按插入顺序 sub
PII_PATTERNS = {
    "id_card": r"\d{17}[\dXx]",
    "bank_card": r"\d{16,19}",
    "phone": r"1[3-9]\d{9}",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "ip_address": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
}
