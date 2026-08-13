import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

from app.api.router import build_api_router
from app.config.settings import settings
from app.utils.errors import AppError
from app.utils.response import error
from app.services.observability_service import request_id_context
from app.api.workbench import router as workbench_router

logger = logging.getLogger(__name__)

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

app.include_router(build_api_router())
app.include_router(workbench_router)
if settings.enable_api_v1:
    app.include_router(build_api_router(), prefix="/api/v1")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get(settings.request_id_header) or str(uuid4())
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started_at = perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_context.reset(token)
    response.headers[settings.request_id_header] = request_id
    response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started_at) * 1000:.1f}"
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=error(
            code=exc.code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details,
        ),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error(
            code="validation_error",
            message="请求参数校验失败",
            request_id=_request_id(request),
            details=jsonable_encoder(exc.errors()),
        ),
    )


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    return JSONResponse(
        status_code=exc.status_code,
        content=error(
            code="http_error",
            message=message,
            request_id=_request_id(request),
            details=None if isinstance(exc.detail, str) else exc.detail,
        ),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled request error", extra={"request_id": _request_id(request)})
    return JSONResponse(
        status_code=500,
        content=error(
            code="internal_error",
            message="服务器暂时无法处理该请求",
            request_id=_request_id(request),
        ),
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "apiVersion": "v1"}
