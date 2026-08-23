from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/workbench", tags=["workbench-placeholder"])


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class ChatCreate(BaseModel):
    subject_id: str
    content: str = Field(min_length=1, max_length=4000)
    mode: str = "detail"


class ExamCreate(BaseModel):
    subject_id: str
    question_count: int = Field(default=10, ge=1, le=100)
    difficulty: str = "medium"


class TaskUpdate(BaseModel):
    completed: bool


SUBJECTS = [
    {"id": "math", "name": "高等数学", "description": "微积分、空间解析几何与级数", "progress": 65, "mastery": 72, "examDate": "2026-08-20"},
    {"id": "data-structure", "name": "数据结构", "description": "树、图、排序算法与哈希", "progress": 40, "mastery": 45, "examDate": "2026-08-25"},
    {"id": "network", "name": "计算机网络", "description": "OSI、TCP/IP 与 HTTP 协议", "progress": 80, "mastery": 85, "examDate": "2026-08-18"},
]

MATERIALS = [
    {"id": "m1", "subjectId": "network", "name": "计算机网络课程讲义.pdf", "type": "pdf", "status": "indexed", "size": 15400000, "uploadedAt": "2026-07-30T08:00:00Z"},
    {"id": "m2", "subjectId": "network", "name": "网络复习笔记.docx", "type": "docx", "status": "indexed", "size": 240000, "uploadedAt": "2026-07-31T08:00:00Z"},
    {"id": "m3", "subjectId": "math", "name": "高数期末样卷.pdf", "type": "pdf", "status": "parsing", "size": 1024000, "uploadedAt": "2026-08-01T10:00:00Z"},
]

TASKS = [
    {"id": "t1", "subjectId": "network", "title": "复习 TCP 拥塞控制", "time": "10:00 - 11:00", "completed": False},
    {"id": "t2", "subjectId": "math", "title": "完成定积分章节练习", "time": "14:00 - 15:30", "completed": True},
    {"id": "t3", "subjectId": "data-structure", "title": "整理二叉树遍历笔记", "time": "19:30 - 20:30", "completed": False},
]


@router.get("/dashboard")
async def dashboard():
    return {"subjects": SUBJECTS, "todayTasks": TASKS, "stats": {"studyMinutes": 126, "completedTasks": 8, "streakDays": 6}}


@router.get("/subjects")
async def list_subjects():
    return SUBJECTS


@router.post("/subjects", status_code=201)
async def create_subject(payload: SubjectCreate):
    subject = {"id": str(uuid4()), "name": payload.name, "description": payload.description, "progress": 0, "mastery": 0, "examDate": None}
    SUBJECTS.insert(0, subject)
    return subject


@router.get("/materials")
async def list_materials(subject_id: str):
    return [item for item in MATERIALS if item["subjectId"] == subject_id]


@router.post("/materials", status_code=202)
async def create_material_placeholder(subject_id: str, filename: str):
    material = {"id": str(uuid4()), "subjectId": subject_id, "name": filename, "type": filename.rsplit(".", 1)[-1].lower(), "status": "parsing", "size": 0, "uploadedAt": datetime.now(timezone.utc).isoformat()}
    MATERIALS.insert(0, material)
    return material


@router.get("/chat/{subject_id}")
async def chat_history(subject_id: str):
    return [{"id": "welcome", "role": "assistant", "content": "你好，我已经准备好根据当前学科资料帮助你复习。可以从一个具体知识点开始提问。", "createdAt": datetime.now(timezone.utc).isoformat(), "citations": []}]


@router.post("/chat", status_code=201)
async def chat(payload: ChatCreate):
    subject = next((item for item in SUBJECTS if item["id"] == payload.subject_id), None)
    if not subject:
        raise HTTPException(status_code=404, detail="学科不存在")
    return {"id": str(uuid4()), "role": "assistant", "content": f"这是“{subject['name']}”的占位回答。已收到你的问题：{payload.content}\n\n当前模式：{payload.mode}。后续可在此接入 RAG 与模型服务。", "createdAt": datetime.now(timezone.utc).isoformat(), "citations": [{"id": "c1", "sourceName": "示例资料", "page": 1, "text": "此引用为接口占位数据。"}]}


@router.get("/mind-map/{subject_id}")
async def mind_map(subject_id: str):
    subject = next((item for item in SUBJECTS if item["id"] == subject_id), None)
    title = subject["name"] if subject else "课程知识"
    return {"nodes": [{"id": "root", "label": title, "level": 0, "mastery": 70}, {"id": "n1", "label": "核心概念", "level": 1, "mastery": 82}, {"id": "n2", "label": "典型题型", "level": 1, "mastery": 58}, {"id": "n3", "label": "易错点", "level": 1, "mastery": 42}], "edges": [{"from": "root", "to": "n1"}, {"from": "root", "to": "n2"}, {"from": "root", "to": "n3"}]}


@router.get("/exams/{subject_id}")
async def exams(subject_id: str):
    return [{"id": "e1", "title": "章节综合练习", "score": 85, "questionCount": 10, "createdAt": "2026-08-01"}]


@router.post("/exams", status_code=201)
async def create_exam(payload: ExamCreate):
    return {"id": str(uuid4()), "title": "AI 生成练习", "score": None, "questionCount": payload.question_count, "difficulty": payload.difficulty, "status": "ready"}


@router.get("/plan")
async def plan(subject_id: str | None = None):
    rows = TASKS if not subject_id else [item for item in TASKS if item["subjectId"] == subject_id]
    return {"date": date.today().isoformat(), "tasks": rows, "week": [(date.today() + timedelta(days=index)).isoformat() for index in range(7)]}


@router.patch("/plan/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate):
    task = next((item for item in TASKS if item["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task["completed"] = payload.completed
    return task
