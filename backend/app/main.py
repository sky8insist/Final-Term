from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, materials, outline, quiz, retrieval, review, subjects
from app.config.settings import settings

app = FastAPI(
    title="Exam AI Assistant API",
    description="Backend service for short-term exam review workflows.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(subjects.router, prefix="/subjects", tags=["subjects"])
app.include_router(materials.router, prefix="/materials", tags=["materials"])
app.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(outline.router, prefix="/outline", tags=["outline"])
app.include_router(quiz.router, prefix="/quiz", tags=["quiz"])
app.include_router(review.router, prefix="/review", tags=["review"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
