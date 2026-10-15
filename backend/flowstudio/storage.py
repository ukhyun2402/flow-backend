from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import Database, Fault, Flow
from .validation import require_valid


def timestamp():
    return datetime.now(UTC).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path: Path | str, seed=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS databases(id TEXT PRIMARY KEY, config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, primary_db_id TEXT NOT NULL REFERENCES databases(id));
            CREATE TABLE IF NOT EXISTS project_databases(project_id TEXT REFERENCES projects(id), db_id TEXT REFERENCES databases(id), PRIMARY KEY(project_id,db_id));
            CREATE TABLE IF NOT EXISTS units(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), code TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(project_id,code));
            CREATE TABLE IF NOT EXISTS processes(id TEXT PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES units(id), process_id TEXT NOT NULL, name TEXT NOT NULL, draft TEXT NOT NULL, draft_version INTEGER NOT NULL DEFAULT 1, latest_revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, UNIQUE(unit_id,process_id));
            CREATE TABLE IF NOT EXISTS versions(process_id TEXT REFERENCES processes(id), revision INTEGER, flow TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(process_id,revision));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, entity_id TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY, process_id TEXT NOT NULL, status INTEGER NOT NULL, duration_ms REAL NOT NULL, trace TEXT NOT NULL, at TEXT NOT NULL);
            """)
        if seed and not self.databases():
            self.seed()

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            with c:
                yield c
        except sqlite3.IntegrityError:
            raise Fault(
                "CONFLICT", "중복 ID 또는 유효하지 않은 상위 항목입니다.", 409
            ) from None
        finally:
            c.close()

    def audit(self, kind, entity_id, actor="system"):
        with self.connection() as c:
            c.execute(
                "INSERT INTO events(kind,entity_id,actor,at) VALUES(?,?,?,?)",
                (kind, entity_id, actor, timestamp()),
            )
            c.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)"
            )

    def databases(self) -> list[Database]:
        with self.connection() as c:
            return [
                Database.model_validate_json(r[0])
                for r in c.execute("SELECT config FROM databases ORDER BY id")
            ]

    def save_database(self, db: Database):
        with self.connection() as c:
            c.execute(
                "INSERT INTO databases VALUES(?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",
                (db.id, db.model_dump_json()),
            )
        self.audit("DATABASE_UPDATED", db.id)
        return db.public()

    def project(self, id_: str) -> dict:
        with self.connection() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (id_,)).fetchone()
            if row is None:
                raise Fault("NOT_FOUND", "프로젝트가 없습니다.", 404)
            return dict(row) | {
                "databaseIds": [
                    r[0]
                    for r in c.execute(
                        "SELECT db_id FROM project_databases WHERE project_id=? ORDER BY db_id",
                        (id_,),
                    )
                ]
            }

    def create_project(
        self, code: str, name: str, primary_db_id: str, database_ids: list[str]
    ):
        id_ = str(uuid.uuid4())
        with self.connection() as c:
            c.execute(
                "INSERT INTO projects VALUES(?,?,?,?)", (id_, code, name, primary_db_id)
            )
            for db in set(database_ids) | {primary_db_id}:
                c.execute("INSERT INTO project_databases VALUES(?,?)", (id_, db))
        self.audit("PROJECT_CREATED", id_)
        return self.project(id_)

    def set_project_databases(self, id_, database_ids):
        project = self.project(id_)
        selected = set(database_ids) | {project["primary_db_id"]}
        with self.connection() as c:
            for row in c.execute(
                "SELECT p.draft FROM processes p JOIN units u ON p.unit_id=u.id WHERE u.project_id=?",
                (id_,),
            ):
                if (
                    not set(json.loads(row[0])["resources"].get("databases", []))
                    <= selected
                ):
                    raise Fault(
                        "CONFLICT",
                        "프로세스가 사용 중인 DB는 프로젝트에서 해제할 수 없습니다.",
                        409,
                    )
            c.execute("DELETE FROM project_databases WHERE project_id=?", (id_,))
            for db in selected:
                c.execute("INSERT INTO project_databases VALUES(?,?)", (id_, db))
        self.audit("PROJECT_DATABASES_UPDATED", id_)
        return self.project(id_)

    def create_unit(self, project_id, code, name):
        id_ = str(uuid.uuid4())
        with self.connection() as c:
            c.execute(
                "INSERT INTO units VALUES(?,?,?,?)", (id_, project_id, code, name)
            )
        self.audit("UNIT_CREATED", id_)
        return {"id": id_, "project_id": project_id, "code": code, "name": name}

    def create_process(self, unit_id, process_id, name, flow: Flow | None = None):
        id_ = str(uuid.uuid4())
        if flow is None:
            flow = Flow(
                specVersion="1.0",
                id=process_id,
                revision=1,
                name=name,
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                outputSchema={"type": "object"},
                resources={"databases": [], "services": []},
                nodes=[
                    {
                        "id": "start",
                        "type": "trigger.http",
                        "name": "HTTP 요청",
                        "config": {
                            "method": "POST",
                            "path": "/" + process_id.lower(),
                            "input": {"name": {"source": "body.name"}},
                        },
                    },
                    {
                        "id": "response",
                        "type": "response.http",
                        "name": "응답 반환",
                        "config": {
                            "status": 200,
                            "body": {
                                "message": {
                                    "op": "concat",
                                    "args": ["Hello, ", {"ref": "input.name"}],
                                }
                            },
                        },
                    },
                ],
                edges=[{"from": "start", "port": "success", "to": "response"}],
                settings={"timeoutMs": 10000, "authentication": "bearer"},
                ui={
                    "positions": {
                        "start": {"x": 80, "y": 120},
                        "response": {"x": 420, "y": 120},
                    }
                },
            )
        flow = flow.model_copy(update={"id": process_id, "name": name})
        with self.connection() as c:
            unit = c.execute(
                "SELECT project_id FROM units WHERE id=?", (unit_id,)
            ).fetchone()
            if not unit:
                raise Fault("NOT_FOUND", "업무 단위가 없습니다.", 404)
            allowed = {
                r[0]
                for r in c.execute(
                    "SELECT db_id FROM project_databases WHERE project_id=?", (unit[0],)
                )
            }
            require_valid(flow, allowed)
            c.execute(
                "INSERT INTO processes(id,unit_id,process_id,name,draft,updated_at) VALUES(?,?,?,?,?,?)",
                (
                    id_,
                    unit_id,
                    process_id,
                    name,
                    flow.model_dump_json(by_alias=True),
                    timestamp(),
                ),
            )
        self.audit("PROCESS_CREATED", id_)
        return self.process(id_)

    def process(self, id_) -> dict:
        with self.connection() as c:
            row = c.execute(
                "SELECT p.*,u.project_id,u.name AS unit_name FROM processes p JOIN units u ON p.unit_id=u.id WHERE p.id=?",
                (id_,),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND", "프로세스가 없습니다.", 404)
            value = dict(row)
            value["flow"] = json.loads(value.pop("draft"))
            value["project"] = self.project(value["project_id"])
            value["versions"] = [
                dict(r)
                for r in c.execute(
                    "SELECT revision,hash,created_at FROM versions WHERE process_id=? ORDER BY revision DESC",
                    (id_,),
                )
            ]
            return value

    def save_draft(self, id_, flow: Flow, expected_version: int):
        current = self.process(id_)
        if flow.id != current["process_id"]:
            raise Fault("VALIDATION_ERROR", "Flow ID는 프로세스 ID와 같아야 합니다.")
        # Drafts may be temporarily invalid while editing; structural Pydantic validation remains required.
        if not set(flow.resources.get("databases", [])) <= set(
            current["project"]["databaseIds"]
        ):
            raise Fault("VALIDATION_ERROR", "프로젝트에 연결되지 않은 DB입니다.")
        with self.connection() as c:
            changed = c.execute(
                "UPDATE processes SET draft=?,name=?,draft_version=draft_version+1,updated_at=? WHERE id=? AND draft_version=?",
                (
                    flow.model_dump_json(by_alias=True),
                    flow.name,
                    timestamp(),
                    id_,
                    expected_version,
                ),
            ).rowcount
            if not changed:
                raise Fault(
                    "VERSION_CONFLICT",
                    "다른 변경이 있습니다. 최신 프로세스를 다시 불러오세요.",
                    409,
                )
        self.audit("DRAFT_SAVED", id_)
        return self.process(id_)

    def publish(self, id_, expected_version):
        current = self.process(id_)
        flow = Flow.model_validate(current["flow"])
        require_valid(flow, set(current["project"]["databaseIds"]))
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT draft_version,latest_revision FROM processes WHERE id=?", (id_,)
            ).fetchone()
            if row[0] != expected_version:
                raise Fault("VERSION_CONFLICT", "최신 초안이 아닙니다.", 409)
            revision = row[1] + 1
            flow = flow.model_copy(update={"revision": revision})
            text = flow.model_dump_json(by_alias=True)
            digest = hashlib.sha256(text.encode()).hexdigest()
            c.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?)",
                (id_, revision, text, digest, timestamp()),
            )
            c.execute(
                "UPDATE processes SET latest_revision=?,draft_version=draft_version+1,draft=?,updated_at=? WHERE id=?",
                (revision, text, timestamp(), id_),
            )
        self.audit("VERSION_PUBLISHED", id_)
        return self.process(id_)

    def version(self, id_, revision):
        with self.connection() as c:
            row = c.execute(
                "SELECT flow FROM versions WHERE process_id=? AND revision=?",
                (id_, revision),
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND", "저장 버전이 없습니다.", 404)
            return json.loads(row[0])

    def tree(self, database_id: str | None = None):
        with self.connection() as c:
            projects = c.execute(
                "SELECT DISTINCT p.* FROM projects p JOIN project_databases d ON p.id=d.project_id WHERE (? IS NULL OR d.db_id=?) ORDER BY p.code",
                (database_id, database_id),
            ).fetchall()
            out = []
            for p in projects:
                project = self.project(p["id"])
                units = []
                for u in c.execute(
                    "SELECT * FROM units WHERE project_id=? ORDER BY code", (p["id"],)
                ):
                    summaries = []
                    for row in c.execute(
                        "SELECT id,process_id,name,draft_version,latest_revision,draft FROM processes WHERE unit_id=? ORDER BY process_id",
                        (u["id"],),
                    ):
                        item = dict(row)
                        draft = json.loads(item.pop("draft"))
                        item["method"] = next(
                            (
                                n["config"].get("method", "API")
                                for n in draft["nodes"]
                                if n["type"] == "trigger.http"
                            ),
                            "API",
                        )
                        summaries.append(item)
                    units.append(dict(u) | {"processes": summaries})
                out.append(project | {"units": units})
            return out

    def record_execution(self, process_id, result):
        with self.connection() as c:
            c.execute(
                "INSERT OR REPLACE INTO executions VALUES(?,?,?,?,?,?)",
                (
                    result["executionId"],
                    process_id,
                    result["status"],
                    result["durationMs"],
                    encode(result["trace"]),
                    timestamp(),
                ),
            )
            c.execute(
                "DELETE FROM executions WHERE id NOT IN (SELECT id FROM executions ORDER BY at DESC LIMIT 1000)"
            )
        self.audit("PREVIEW_EXECUTED", process_id)

    def history(self, process_id=None):
        with self.connection() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,process_id,status,duration_ms,at FROM executions WHERE (? IS NULL OR process_id=?) ORDER BY at DESC LIMIT 100",
                    (process_id, process_id),
                )
            ]

    def trace(self, id_):
        with self.connection() as c:
            row = c.execute(
                "SELECT trace FROM executions WHERE id=?", (id_,)
            ).fetchone()
            if not row:
                raise Fault("NOT_FOUND", "실행 기록이 없습니다.", 404)
            return json.loads(row[0])

    def seed(self):
        for id_, name, vendor, port in (
            ("main", "ERP Oracle", "oracle", 1521),
            ("crm", "CRM MySQL", "mysql", 3306),
            ("tibero", "Core Tibero", "tibero", 8629),
        ):
            self.save_database(
                Database(
                    id=id_,
                    name=name,
                    vendor=vendor,
                    port=port,
                    passwordSecretRef=id_.upper() + "_DB_PASSWORD",
                )
            )
        project = self.create_project("ERP", "ERP 플랫폼", "main", ["main", "crm"])
        common = self.create_unit(project["id"], "COMMON", "공통 업무")
        self.create_process(common["id"], "SYS-001", "API 연결 확인")
        users = self.create_unit(project["id"], "USER", "사용자 관리")
        example = Path(__file__).resolve().parents[2] / "examples/user-query-flow.json"
        if example.exists():
            self.create_process(
                users["id"],
                "USR-001",
                "사용자 조회",
                Flow.model_validate_json(example.read_text(encoding="utf-8")),
            )
        else:
            self.create_process(users["id"], "USR-001", "사용자 조회")
        for db, code, name in (
            ("crm", "CRM", "고객 서비스"),
            ("tibero", "CORE", "코어 업무"),
        ):
            p = self.create_project(code, name, db, [db])
            u = self.create_unit(p["id"], "COMMON", "공통 업무")
            self.create_process(u["id"], code + "-001", "API 연결 확인")
