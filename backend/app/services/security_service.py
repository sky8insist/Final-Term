import re
import unicodedata

PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"ignore (all|the) previous instructions", r"reveal (the )?system prompt",
        r"you are now (a|an)", r"developer message", r"execute (this|the following) tool",
        r"api[_ -]?key\s*[:=]", r"BEGIN (RSA|OPENSSH) PRIVATE KEY",
        r"忽略(以上|之前|所有).{0,12}(指令|要求)", r"(泄露|显示|输出).{0,8}(系统提示词|开发者消息)",
        r"你现在是", r"调用.{0,8}(工具|函数)", r"密码\s*[:：=]", r"密钥\s*[:：=]",
    )
]


def scan_untrusted_text(text: str) -> dict:
    matches = sorted({pattern.pattern for pattern in PATTERNS if pattern.search(text)})
    if any(unicodedata.category(char) == "Cf" for char in text):
        matches.append("invisible_unicode_format_character")
    return {
        "suspicious": bool(matches), "matchedPatterns": matches,
        "severity": "high" if len(matches) > 1 else "medium" if matches else "none",
    }
