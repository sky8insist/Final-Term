"""Deterministic local substitutes for external APIs.

These responses follow the same contracts as real providers so the complete
application workflow can be previewed without sending data outside the machine.
"""
from datetime import UTC, datetime
from hashlib import sha256
import json
import re


def mock_embedding(text: str, dimensions: int) -> list[float]:
    seed = sha256(text.encode("utf-8")).digest()
    values = [((seed[index % len(seed)] / 255.0) * 2 - 1) for index in range(dimensions)]
    norm = sum(value * value for value in values) ** 0.5 or 1
    return [round(value / norm, 8) for value in values]


def _citation_ids(prompt: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'"id"\s*:\s*"([^"]+)"', prompt)))


def _intent(message: str) -> str:
    rules = [
        (("试卷", "模拟考", "组卷"), "generate_exam"),
        (("思维导图", "脑图"), "generate_mind_map"),
        (("练习", "刷题", "出题"), "generate_practice"),
        (("闪卡",), "generate_flashcards"), (("表格",), "analyze_table"),
        (("图表",), "explain_chart"), (("公式", "推导"), "derive_formula"),
        (("提纲", "大纲"), "generate_outline"), (("总结",), "summarize"),
        (("练习表现", "薄弱点", "错题", "做错"), "analyze_practice_performance"),
        (("进度", "掌握度"), "show_progress"), (("计划", "安排"), "build_study_plan"),
    ]
    return next((intent for words, intent in rules if any(word in message for word in words)), "qa")


def mock_json(prompt: str) -> dict:
    if "识别期末复习助手意图" in prompt:
        message = prompt.rsplit("用户消息：", 1)[-1]
        intent = _intent(message)
        return {
            "primaryIntent": intent, "secondaryIntents": [], "confidence": 0.9,
            "needsRetrieval": True, "needsClarification": False,
            "clarificationQuestion": None, "requiredSkills": ["retrieval", intent],
            "materialScope": {}, "allowExternalKnowledge": "联网" in message,
        }
    citations = _citation_ids(prompt)
    citation = citations[0] if citations else "mock-source"
    if "MIND_MAP_WORKFLOW_V2" in prompt:
        focus_match = re.search(r"Focus Question:\s*(.+)", prompt)
        mode_match = re.search(r"生成模式:\s*(question|topic|chapter)", prompt)
        focus = focus_match.group(1).strip() if focus_match else "当前知识点如何理解？"
        mode = mode_match.group(1) if mode_match else "question"
        return {
            "title": "核心知识结构", "focusQuestion": focus,
            "summary": "围绕当前学习问题组织定义、关系与应用。",
            "mode": mode, "evidenceInsufficient": False,
            "nodes": [
                {"id": "root", "parentId": None, "label": "核心问题", "type": "root",
                 "importance": 1, "examImportance": "high", "mastery": None,
                 "description": focus, "sourceIds": [], "order": 0},
                {"id": "concept", "parentId": "root", "label": "核心概念", "type": "definition",
                 "importance": 0.9, "examImportance": "high", "mastery": None,
                 "description": "根据课程资料提炼的核心概念。", "sourceIds": [citation], "order": 1},
                {"id": "relation", "parentId": "root", "label": "概念关系", "type": "comparison",
                 "importance": 0.8, "examImportance": "medium", "mastery": None,
                 "description": "核心概念之间的逻辑联系。", "sourceIds": [citation], "order": 2},
            ],
            "edges": [
                {"source": "root", "target": "concept", "relation": "包含"},
                {"source": "root", "target": "relation", "relation": "包含"},
            ],
        }
    if "类型：mind_map" in prompt:
        return {"title": "Mock 复习思维导图", "nodes": [
            {"id": "root", "parentId": None, "title": "核心知识", "description": "本地 Mock 根节点",
             "nodeType": "concept", "mastery": 0.5, "citationIds": [citation], "order": 0},
            {"id": "node-1", "parentId": "root", "title": "重点与关系", "description": "接入真实模型后按资料生成",
             "nodeType": "exam_point", "mastery": 0.5, "citationIds": [citation], "order": 1},
        ]}
    if "类型：flashcards" in prompt:
        return {"title": "Mock 闪卡", "cards": [{
            "front": "本章核心概念是什么？", "back": "这是本地预览答案，真实模型将依据资料生成。",
            "knowledgeKey": "Mock知识点", "difficulty": "medium", "citationIds": [citation],
        }]}
    if "类型：outline" in prompt:
        return {"title": "Mock 复习提纲", "sections": [{
            "id": "section-1", "title": "核心内容", "keyPoints": ["资料重点将在这里展示"],
            "examTips": ["接入真实 API 后生成"], "citationIds": [citation],
        }]}
    if "期末考试命题专家" in prompt:
        match = re.search(r"蓝图：(.*?)；\s*总体难度", prompt, re.DOTALL)
        try:
            specs = json.loads(match.group(1)) if match else []
        except json.JSONDecodeError:
            specs = []
        questions = []
        for spec in specs:
            qtype, count = spec["questionType"], int(spec["count"])
            points = float(spec["pointsEach"])
            for index in range(count):
                options = ["A. 正确表述", "B. 常见误区", "C. 条件缺失", "D. 无关结论"] if qtype in {"single_choice", "multiple_choice"} else []
                correct = (
                    ["A. 正确表述"] if qtype == "multiple_choice"
                    else "A. 正确表述" if qtype == "single_choice"
                    else "true" if qtype == "true_false"
                    else "Mock参考答案"
                )
                rubric = {"criteria": [{"description": "核心得分点", "points": points}]} if qtype in {"short_answer", "calculation", "essay"} else {"criteria": []}
                questions.append({
                    "questionType": qtype, "stem": f"Mock {qtype} 第 {index + 1} 题：请根据资料完成作答。",
                    "options": options, "correctAnswer": correct,
                    "explanation": "这是本地预览解析，真实 API 将严格依据引用资料生成。",
                    "knowledgeKey": f"Mock知识点-{qtype}", "difficulty": "medium",
                    "rubric": rubric, "citationIds": [citation],
                })
        return {"questions": questions}
    if "按固定评分量规批改主观题" in prompt:
        points = float((re.search(r"满分不得超过([\d.]+)", prompt) or [None, "0"])[1])
        return {"earnedPoints": points, "isCorrect": True, "feedback": "Mock 评分通过",
                "earnedCriteria": ["核心得分点"], "missingCriteria": [], "errorType": None}
    if "复盘一次学习互动" in prompt:
        return {"eventType": "qa", "memoryCandidates": [], "skillCandidates": [], "summary": "Mock 会话复盘"}
    if "整理课程录音转写" in prompt:
        return {"correctedTranscript": "Mock 课程录音转写。", "summary": "Mock 音频摘要",
                "chapters": [{"title": "第一节", "summary": "预览章节"}],
                "knowledgePoints": ["Mock知识点"], "examPoints": ["Mock考点"], "uncertainTerms": []}
    return {"title": "Mock 产物", "sections": [{
        "title": "预览内容", "items": ["接入真实 API 后生成"], "citationIds": [citation],
    }]}


def mock_text(_prompt: str) -> str:
    return (
        "## 本地 Mock 回答\n\n"
        "当前内容由本地 Mock Adapter 生成，用于验证路由、检索、引用和界面流程。"
        "关闭 `MOCK_EXTERNAL_APIS` 并配置真实模型 API 后，将使用检索证据生成正式回答。"
    )


def mock_image(filename: str) -> dict:
    return {
        "kind": "image", "ocrText": f"Mock OCR：{filename}",
        "summary": "本地视觉识别预览结果", "confidence": 0.99,
        "table": {}, "chart": {}, "formula": {},
    }


def mock_transcription(filename: str) -> dict:
    text = f"这是文件 {filename} 的本地 Mock 音频转写。"
    return {"text": text, "segments": [{"start": 0, "end": 5, "text": text}],
            "duration": 5, "language": "zh"}


def mock_public_search(query: str) -> list[dict]:
    return [{
        "title": f"Mock 公共知识：{query[:40]}",
        "url": "https://example.invalid/mock-public-knowledge",
        "content": "这是本地公共知识兜底数据，不会发送任何网络请求。",
        "publishedAt": None, "accessedAt": datetime.now(UTC).isoformat(),
        "trustLevel": "mock", "score": 1.0, "provider": "mock",
    }]
