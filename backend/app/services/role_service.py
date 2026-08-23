ROLE_CONFIGS = {
    "beginner": {
        "name": "小白详细模式",
        "instruction": "少用术语，先用生活化类比，再分步骤解释；结尾用一个简单问题检查理解。",
        "suggestions": ["换一个更简单的例子", "生成基础闪卡"],
    },
    "crash_course": {
        "name": "快速学习模式",
        "instruction": "聚焦高频考点、记忆口诀、答题模板和最短得分路径，明确标出可暂缓内容。",
        "suggestions": ["生成一页速记", "开始高频题训练"],
    },
    "socratic": {
        "name": "苏格拉底反问模式",
        "instruction": "不要立即给出最终答案；先提出能够推动推理的具体问题，每轮只推进关键一步。",
        "suggestions": ["继续反问训练", "查看完整推导"],
    },
    "examiner": {
        "name": "严格考官模式",
        "instruction": "按照考试口径提问；交卷前不得泄露答案、解析或暗示，明确时间和得分点。",
        "suggestions": ["提交答案", "下一题"],
    },
    "performance_coach": {
        "name": "练习表现分析模式",
        "instruction": "结合正确率、掌握度、近期表现和学习互动定位薄弱知识点，并给出可执行的下一步。",
        "suggestions": ["生成专项练习", "生成复习计划"],
    },
    "academic": {
        "name": "专业解析模式",
        "instruction": "给出严谨定义、推导过程、边界条件和适用限制；重要断言必须绑定资料或外部来源。",
        "suggestions": ["展开完整推导", "比较不同定义"],
    },
    "sprint_planner": {
        "name": "冲刺规划模式",
        "instruction": "结合剩余时间、知识重要度和掌握度排序，给出可执行时间盒任务与取舍理由。",
        "suggestions": ["生成今日计划", "查看薄弱点"],
    },
}

_ROLE_POLICIES = {
    "beginner": ("guided_explanation", "medium", True, "introductory", "material claims"),
    "crash_course": ("exam_sprint", "low", True, "exam-focused", "all factual claims"),
    "socratic": ("guided_reasoning", "high", False, "adaptive", "hints and corrections"),
    "examiner": ("mock_exam", "medium", False, "exam-standard", "questions and post-submit analysis"),
    "performance_coach": ("performance_analysis", "high", True, "diagnostic", "practice and dialogue signals"),
    "academic": ("deep_study", "low", True, "advanced", "all important assertions"),
    "sprint_planner": ("planning", "medium", True, "strategic", "mastery and material evidence"),
}
for _key, (_scene, _density, _direct, _depth, _citations) in _ROLE_POLICIES.items():
    ROLE_CONFIGS[_key].update({
        "applicableScene": _scene, "questionDensity": _density,
        "directAnswer": _direct, "depth": _depth,
        "citationRequirement": _citations,
        "forbidden": ["改变事实标准", "伪造引用", "越权访问其他用户资料"],
    })


def recommend_role(*, requested: str, profile: dict, intent: str) -> tuple[str, dict]:
    if requested != "auto":
        key = requested
    elif intent in {"generate_exam", "grade_answer"}:
        key = "examiner"
    elif intent == "analyze_practice_performance":
        key = "performance_coach"
    elif intent in {"build_study_plan", "show_progress"}:
        key = "sprint_planner"
    elif profile.get("preferredRole") in ROLE_CONFIGS:
        key = profile["preferredRole"]
    elif profile.get("level") == "beginner":
        key = "beginner"
    else:
        key = "academic"
    return key, ROLE_CONFIGS[key]
