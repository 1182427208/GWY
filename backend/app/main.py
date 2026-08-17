import logging

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


def configure_runtime_logging() -> None:
    for logger_name in (
        "httpx",
        "httpcore",
        "openai",
        "openai._base_client",
        "uvicorn.access",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    access_logger.propagate = False
    hook_logger = logging.getLogger("app.gwy.agent_runtime.hooks")
    hook_logger.setLevel(logging.INFO)
    hook_logger.propagate = False
    if not hook_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        hook_logger.addHandler(handler)


configure_runtime_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Ensure CORS headers on all responses, including errors and SSE streams
@app.middleware("http")
async def add_cors_header(request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin in settings.all_cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

app.include_router(api_router, prefix=settings.API_V1_STR)
