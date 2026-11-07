import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agents.llm import ai_status
from .api import router
from .config import settings
from .database import Base, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aura")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    ai = ai_status()
    log.log(logging.INFO if ai["configured"] else logging.WARNING, "AI provider=%s model=%s configured=%s - %s",
            ai["provider"], ai["model"], ai["configured"], ai["message"])
    yield


app = FastAPI(title="SOFT QA", version="0.1.0", lifespan=lifespan,
              description="AI-powered software QA: static analysis, security scanning, AI review, sandboxed test execution.")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/")
def root() -> dict:
    return {"name": "SOFT QA", "docs": "/docs", "status": "/api/system/status"}
