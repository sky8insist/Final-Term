"""Conservative lexical admission, not a semantic classifier or learner-state store."""
import re

from fastapi import HTTPException

VERSION = 'memory-boundary-v1'
STATE = r'mastery|accuracy|score|confidence|due.?review|next review|exam.?date|exam.?result|tomorrow|today|next week|掌握度|已掌握|掌握了|答对|答错|正确率|准确率|得分|分数|信心|复习到期|下次复习|考试日期|考试成绩|考试目标|明天|后天|今天|本周|下周|这次考试|[0-9]{4}[-/年][0-9]|[0-9]+\s*[%％]'
KINDS = [
    ('preference', r'偏好|喜欢|不喜欢|讲解方式|表达方式|prefer|teaching style'),
    ('habit', r'习惯|通常|每次学习|habit|usually'),
    ('difficulty', r'长期.*困难|经常.*困难|总是.*困难|persistent difficulty|often struggle'),
    ('long_term_goal', r'长期目标|长远目标|long.term goal'),
]


def classify(content: str) -> str | None:
    if not content or re.search(STATE, content, re.I): return None
    return next((kind for kind, pattern in KINDS if re.search(pattern, content, re.I)), None)


def admit(content: str) -> str:
    kind = classify(content)
    if not kind:
        raise HTTPException(422, '长期记忆仅保存稳定偏好、习惯、长期困难或目标；掌握度、考试和复习状态请使用学习记录。')
    return kind
