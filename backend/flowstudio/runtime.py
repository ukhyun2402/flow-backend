from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .database import Databases
from .engine import Engine, normalize_input
from .models import Database, Fault, Flow
from .validation import require_valid


def create_runtime(directory: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Generated Flow Server", docs_url=None, redoc_url=None, openapi_url=None
    )
    configs = (
        json.loads(Path(os.environ["FLOW_DATABASE_CONFIG"]).read_text(encoding="utf-8"))
        if os.environ.get("FLOW_DATABASE_CONFIG")
        else []
    )
    dbs = [Database.model_validate(v) for v in configs]
    services = (
        json.loads(Path(os.environ["FLOW_SERVICE_CONFIG"]).read_text(encoding="utf-8"))
        if os.environ.get("FLOW_SERVICE_CONFIG")
        else {}
    )
    engine = Engine(Databases(lambda: dbs), services)
    seen = set()

    @app.exception_handler(Fault)
    async def fault_handler(request, error):
        return JSONResponse(error.response(), status_code=error.status)

    def endpoint(flow):
        async def execute(request: Request):
            if flow.settings["authentication"] == "bearer":
                expected = "Bearer " + os.environ["FLOW_RUNTIME_TOKEN"]
                if not hmac.compare_digest(
                    request.headers.get("authorization", "").encode(), expected.encode()
                ):
                    raise Fault("UNAUTHORIZED", "Bearer 인증이 필요합니다.", 401)
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > 1_048_576:
                    raise Fault(
                        "VALIDATION_ERROR", "요청 크기 제한을 초과했습니다.", 413
                    )
                content.extend(chunk)
            try:
                body = json.loads(content) if content else {}
            except ValueError:
                raise Fault("VALIDATION_ERROR", "JSON 요청을 확인하세요.") from None
            input_ = normalize_input(
                flow,
                {
                    "body": body,
                    "path": request.path_params,
                    "query": dict(request.query_params),
                    "headers": dict(request.headers),
                },
            )
            result = await run_in_threadpool(engine.run, flow, input_, False)
            for t in result["trace"]:
                logging.getLogger("flow.trace").info(json.dumps(t))
            return JSONResponse(
                result["body"], status_code=result["status"], headers=result["headers"]
            )

        return execute

    for file in sorted(
        Path(directory or os.environ.get("FLOW_DIRECTORY", "flows")).glob("*.json")
    ):
        flow = Flow.model_validate_json(file.read_text(encoding="utf-8"))
        require_valid(flow)
        if (
            flow.settings["authentication"] == "bearer"
            and len(os.environ.get("FLOW_RUNTIME_TOKEN", "")) < 24
        ):
            raise RuntimeError("FLOW_RUNTIME_TOKEN must be at least 24 characters")
        trigger = next(n for n in flow.nodes if n.type == "trigger.http")
        import re

        key = (
            trigger.config["method"],
            re.sub(r"\{[^{}]+\}", "{}", trigger.config["path"]),
        )
        if key in seen:
            raise RuntimeError("Duplicate generated API route")
        seen.add(key)
        app.add_api_route(
            trigger.config["path"], endpoint(flow), methods=[trigger.config["method"]]
        )
    return app
