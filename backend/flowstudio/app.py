from __future__ import annotations

import hmac
import json
import os
import time
import secrets
import threading
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .database import Databases
from .drawio import from_xml
from .engine import Engine, normalize_input
from .generation import generate
from .models import Database, Fault, Flow, StrictModel
from .storage import Store
from .validation import require_valid, validate
from .deployment import Deployments, signature

ROOT = Path(__file__).resolve().parents[2]


class ProjectCreate(StrictModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    primaryDatabaseId: str
    databaseIds: list[str]


class UnitCreate(StrictModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)


class ProcessCreate(UnitCreate):
    pass


class Draft(StrictModel):
    flow: Flow
    expectedVersion: int = Field(ge=1)


class Version(StrictModel):
    expectedVersion: int = Field(ge=1)


class DatabaseIds(StrictModel):
    databaseIds: list[str]


class Preview(StrictModel):
    flow: Flow | None = None
    input: dict | None = None
    request: dict = Field(default_factory=dict)
    executionId: str | None = None


class Diagram(StrictModel):
    flow: Flow
    xml: str = Field(max_length=2_000_000)


class ApplyBuild(StrictModel):
    flow: Flow
    validationId: str


class ExecuteApplied(StrictModel):
    input: dict = Field(default_factory=dict)


class SqlPreview(StrictModel):
    databaseRef: str
    sql: str = Field(max_length=100000)
    parameters: dict = Field(default_factory=dict)
    command: bool = False
    executionId: str | None = None
    projectId: str


def create_app(
    store: Store | None = None,
    tokens: dict[str, str] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    store = store or Store(
        Path(os.environ.get("FLOW_DATA", str(ROOT / "data"))) / "flowstudio.sqlite3"
    )
    app = FastAPI(
        title="Flow Studio",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    databases = Databases(store.databases)
    services = (
        json.loads(Path(os.environ["FLOW_SERVICE_CONFIG"]).read_text(encoding="utf-8"))
        if os.environ.get("FLOW_SERVICE_CONFIG")
        else {}
    )
    engine = Engine(databases, services)
    deployments = Deployments(store)
    validations = {}
    validation_lock = threading.Lock()
    app.state.store, app.state.engine = store, engine

    @app.middleware("http")
    async def access(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            configured = (
                tokens
                if tokens is not None
                else {
                    "admin": os.environ.get("FLOW_ADMIN_TOKEN", ""),
                    "editor": os.environ.get("FLOW_EDITOR_TOKEN", ""),
                    "runner": os.environ.get("FLOW_RUNNER_TOKEN", ""),
                }
            )
            actual = request.headers.get("authorization", "")
            role = next(
                (
                    r
                    for r, value in configured.items()
                    if len(value) >= 24
                    and hmac.compare_digest(
                        actual.encode(), ("Bearer " + value).encode()
                    )
                ),
                None,
            )
            # The desktop workspace opens locally without an interactive token.
            # Explicit role configuration continues to protect managed deployments.
            if tokens is None and (
                os.environ.get("FLOW_LOCAL_WORKSPACE") == "1"
                or not any(configured.values())
            ):
                host = request.url.hostname
                client = request.client.host if request.client else ""
                origin = request.headers.get("origin")
                if (
                    host in {"localhost", "127.0.0.1", "::1"}
                    and client in {"127.0.0.1", "::1"}
                    and (not origin or origin == str(request.base_url).rstrip("/"))
                    and request.headers.get("sec-fetch-site") != "cross-site"
                ):
                    role = "admin"
            if role is None:
                return JSONResponse(
                    {"code": "UNAUTHORIZED", "message": "관리 API 토큰을 입력하세요."},
                    status_code=401,
                )
            request.state.role = role
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > 5_000_000:
                    return JSONResponse(
                        {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "요청 크기 제한을 초과했습니다.",
                        },
                        status_code=413,
                    )
                content.extend(chunk)
            request._body = bytes(content)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def require(request, *roles):
        if request.state.role not in roles:
            raise Fault("FORBIDDEN", "이 작업을 실행할 권한이 없습니다.", 403)

    @app.exception_handler(Fault)
    async def fault_handler(request, error):
        return JSONResponse(error.response(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_handler(request, error):
        return JSONResponse(
            {
                "code": "VALIDATION_ERROR",
                "message": "요청 형식을 확인하세요.",
                "fields": [list(e["loc"]) for e in error.errors()],
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def error_handler(request, error):
        return JSONResponse(
            {"code": "INTERNAL_ERROR", "message": "작업을 완료하지 못했습니다."},
            status_code=500,
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/api/workspace")
    def workspace(databaseId: str | None = None):
        return {
            "databases": [d.public() for d in store.databases()],
            "projects": store.tree(databaseId),
            "drawioInstalled": (ROOT / ".tools/drawio/index.html").exists(),
            "editorUrl": "/drawio/index.html",
            "version": "0.2.0",
        }

    @app.put("/api/databases/{id_}")
    def database_save(id_: str, body: Database, request: Request):
        require(request, "admin")
        if id_ != body.id:
            raise Fault("VALIDATION_ERROR", "DB ID가 일치하지 않습니다.")
        return store.save_database(body)

    @app.post("/api/databases/{id_}/test")
    def database_test(id_: str, request: Request):
        require(request, "admin", "runner")
        with databases.connect(id_) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT 1"
                    + (
                        " FROM dual"
                        if databases.get(id_).vendor in ("oracle", "tibero")
                        else ""
                    )
                )
                cursor.fetchone()
            finally:
                cursor.close()
            return {"connected": True, "vendor": databases.get(id_).vendor}

    @app.get("/api/databases/{id_}/metadata")
    def metadata(id_: str, request: Request):
        require(request, "admin", "runner")
        return databases.metadata(id_)

    @app.post("/api/projects")
    def project_create(body: ProjectCreate, request: Request):
        require(request, "admin", "editor")
        return store.create_project(
            body.code, body.name, body.primaryDatabaseId, body.databaseIds
        )

    @app.put("/api/projects/{id_}/databases")
    def project_databases(id_: str, body: DatabaseIds, request: Request):
        require(request, "admin", "editor")
        return store.set_project_databases(id_, body.databaseIds)

    @app.post("/api/projects/{id_}/units")
    def unit_create(id_: str, body: UnitCreate, request: Request):
        require(request, "admin", "editor")
        return store.create_unit(id_, body.code, body.name)

    @app.post("/api/units/{id_}/processes")
    def process_create(id_: str, body: ProcessCreate, request: Request):
        require(request, "admin", "editor")
        return store.create_process(id_, body.code, body.name)

    @app.get("/api/processes/{id_}")
    def process_get(id_: str):
        return store.process(id_)

    @app.put("/api/processes/{id_}/draft")
    def draft_save(id_: str, body: Draft, request: Request):
        require(request, "admin", "editor")
        return store.save_draft(id_, body.flow, body.expectedVersion)

    @app.post("/api/processes/{id_}/versions")
    def version_save(id_: str, body: Version, request: Request):
        require(request, "admin", "editor")
        return store.publish(id_, body.expectedVersion)

    @app.get("/api/processes/{id_}/versions/{revision}")
    def version_get(id_: str, revision: int):
        return store.version(id_, revision)

    @app.post("/api/validate")
    def validate_flow(
        body: Flow, projectId: str | None = None, processId: str | None = None
    ):
        process = store.process(processId) if processId else None
        if process and (
            body.id != process["process_id"] or projectId != process["project_id"]
        ):
            raise Fault("VALIDATION_ERROR", "프로세스와 프로젝트 범위를 확인하세요.")
        allowed = (
            set(store.project(projectId)["databaseIds"])
            if projectId
            else {d.id for d in store.databases()}
        )
        issues = validate(body, allowed)
        receipt = None
        if not issues and process:
            receipt = secrets.token_urlsafe(32)
            with validation_lock:
                for key in list(validations):
                    if validations[key][2] < time.monotonic():
                        validations.pop(key)
                if len(validations) >= 1000:
                    validations.pop(next(iter(validations)))
                validations[receipt] = (
                    processId,
                    signature(body, process["project"], store.databases()),
                    time.monotonic() + 900,
                )
        return {"valid": not issues, "issues": issues, "validationId": receipt}

    @app.post("/api/processes/{id_}/apply")
    def apply_server(id_: str, body: ApplyBuild, request: Request):
        require(request, "admin", "editor")
        process = store.process(id_)
        with validation_lock:
            receipt = validations.get(body.validationId)
        if (
            not receipt
            or receipt[0] != id_
            or receipt[2] < time.monotonic()
            or receipt[1] != signature(body.flow, process["project"], store.databases())
        ):
            raise Fault(
                "VALIDATION_REQUIRED",
                "구성이 변경되었거나 검증이 만료되었습니다. 구성 검증을 다시 수행하세요.",
                409,
            )
        require_valid(body.flow, set(process["project"]["databaseIds"]))
        result = deployments.apply(process, body.flow)
        store.audit("SERVER_APPLIED", id_, request.state.role)
        return result

    @app.post("/api/processes/{id_}/execute")
    def execute_applied(id_: str, body: ExecuteApplied, request: Request):
        require(request, "admin", "runner")
        store.process(id_)
        result = deployments.execute(id_, engine, body.input)
        store.record_execution(id_, result)
        return result

    @app.post("/api/drawio/convert")
    def diagram_convert(body: Diagram):
        flow = from_xml(body.xml, body.flow)
        return {"flow": flow.model_dump(by_alias=True), "issues": validate(flow)}

    @app.post("/api/processes/{id_}/preview")
    def preview(id_: str, body: Preview, request: Request):
        require(request, "admin", "runner")
        process = store.process(id_)
        flow = body.flow or Flow.model_validate(process["flow"])
        if flow.id != process["process_id"]:
            raise Fault("VALIDATION_ERROR", "프로세스 ID가 일치하지 않습니다.")
        require_valid(flow, set(process["project"]["databaseIds"]))
        input_ = (
            body.input
            if body.input is not None
            else normalize_input(flow, body.request)
        )
        result = engine.run(flow, input_, True, body.executionId)
        store.record_execution(id_, result)
        return result

    @app.post("/api/sql/preview")
    def sql_preview(body: SqlPreview, request: Request):
        require(request, "admin", "runner")
        if body.databaseRef not in store.project(body.projectId)["databaseIds"]:
            raise Fault("FORBIDDEN", "프로젝트에 연결되지 않은 DB입니다.", 403)
        if body.command:
            databases.allow_write(body.databaseRef, True)
        execution_id = body.executionId or str(uuid4())
        UUID(execution_id)
        with (
            databases.executions.run(execution_id),
            databases.connect(body.databaseRef) as conn,
        ):
            try:
                result = databases.execute(
                    conn,
                    body.databaseRef,
                    body.sql,
                    body.parameters,
                    body.command,
                    execution_id,
                    time.monotonic() + 10,
                )
            finally:
                try:
                    conn.rollback()
                except Exception:
                    raise Fault(
                        "DB_ERROR", "롤백 결과를 확인할 수 없습니다.", 502
                    ) from None
        store.audit("SQL_PREVIEW_EXECUTED", body.databaseRef, request.state.role)
        return result | {"executionId": execution_id, "rolledBack": body.command}

    @app.post("/api/executions/{id_}/cancel")
    def cancel(id_: str, request: Request):
        require(request, "admin", "runner")
        UUID(id_)
        return {"cancelRequested": databases.executions.cancel(id_)}

    @app.get("/api/history")
    def history(processId: str | None = None):
        return store.history(processId)

    @app.get("/api/executions/{id_}")
    def traces(id_: str):
        return store.trace(id_)

    @app.post("/api/processes/{id_}/generate")
    def process_generate(id_: str, request: Request, body: Flow | None = None):
        require(request, "admin")
        process = store.process(id_)
        if body:
            if body.id != process["process_id"]:
                raise Fault("VALIDATION_ERROR", "프로세스 ID가 일치하지 않습니다.")
            process["flow"] = body.model_dump(by_alias=True)
        content = generate(
            [process],
            store.databases(),
            {
                "projectId": process["project_id"],
                "businessUnitId": process["unit_id"],
                "processId": process["process_id"],
            },
        )
        store.audit("SERVER_GENERATED", id_, request.state.role)
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="generated-server.zip"'
            },
        )

    @app.post("/api/projects/{id_}/generate")
    def project_generate(id_: str, request: Request):
        require(request, "admin")
        project = store.project(id_)
        tree = next(p for p in store.tree() if p["id"] == id_)
        processes = [
            store.process(p["id"]) for u in tree["units"] for p in u["processes"]
        ]
        content = generate(
            processes,
            store.databases(),
            {"projectId": id_, "projectCode": project["code"]},
        )
        store.audit("PROJECT_SERVER_GENERATED", id_, request.state.role)
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="project-server.zip"'
            },
        )

    drawio = ROOT / ".tools/drawio"
    if drawio.exists():
        app.mount("/drawio", StaticFiles(directory=drawio, html=True), name="drawio")
    static = static_dir or ROOT / "frontend/dist"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="studio")
    return app


app = create_app()
