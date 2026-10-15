"""Real SQL/rollback tests use a SQLite bridge; this does not certify vendor drivers."""

import copy
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal

from flowstudio.database import Databases
from flowstudio.engine import Engine
from flowstudio.models import Database, Flow


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, values=None):
        values = [
            int(v)
            if isinstance(v, Decimal) and v == int(v)
            else str(v)
            if isinstance(v, Decimal)
            else v
            for v in (values or [])
        ]
        self.cursor.execute(query.replace("%s", "?").replace("%%", "%"), values)
        return self

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def close(self):
        self.cursor.close()


class Connection:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)

    def cursor(self, *args):
        return Cursor(self.connection.cursor())

    def thread_id(self):
        return 0

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class SqliteBridge(Databases):
    def __init__(self, tmp_path):
        self.paths = {id_: tmp_path / (id_ + ".sqlite3") for id_ in ("main", "crm")}
        configs = [
            Database(
                id=id_,
                name=id_,
                vendor="mysql",
                readonly=False,
                rollbackSafetyVerified=True,
            )
            for id_ in self.paths
        ]
        super().__init__(lambda: configs)
        for id_, path in self.paths.items():
            with sqlite3.connect(path) as c:
                c.execute("CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT)")
                c.execute("INSERT INTO users VALUES(1,?)", (id_ + " user",))

    @contextmanager
    def connect(self, id_, timeout=10, control=False):
        connection = Connection(self.paths[id_])
        try:
            yield connection
        finally:
            connection.close()


def test_multidatabase_reads_in_one_process(tmp_path, process):
    db = SqliteBridge(tmp_path)
    value = copy.deepcopy(process["flow"])
    value["resources"]["databases"] = ["main", "crm"]
    value["nodes"] = [
        value["nodes"][0],
        {
            "id": "mainQuery",
            "type": "db.query",
            "name": "ERP",
            "config": {
                "databaseRef": "main",
                "sql": "SELECT name FROM users WHERE id=:id",
                "parameters": {"id": 1},
                "resultMode": "zeroOrOne",
            },
        },
        {
            "id": "crmQuery",
            "type": "db.query",
            "name": "CRM",
            "config": {
                "databaseRef": "crm",
                "sql": "SELECT name FROM users WHERE id=:id",
                "parameters": {"id": 1},
                "resultMode": "zeroOrOne",
            },
        },
        {
            "id": "response",
            "type": "response.http",
            "name": "응답",
            "config": {
                "status": 200,
                "body": {
                    "erp": {"ref": "nodes.mainQuery.output.row.name"},
                    "crm": {"ref": "nodes.crmQuery.output.row.name"},
                },
            },
        },
    ]
    value["edges"] = [
        {"from": a, "to": b, "port": "success"}
        for a, b in [
            ("start", "mainQuery"),
            ("mainQuery", "crmQuery"),
            ("crmQuery", "response"),
        ]
    ]
    result = Engine(db).run(Flow.model_validate(value), {"name": "test"})
    assert result["status"] == 200
    assert result["body"] == {"erp": "main user", "crm": "crm user"}
    assert len(result["trace"]) == 4


def transaction_flow(process):
    value = copy.deepcopy(process["flow"])
    value["resources"]["databases"] = ["main"]
    value["nodes"] = [
        value["nodes"][0],
        {
            "id": "begin",
            "type": "transaction.begin",
            "name": "시작",
            "config": {"databaseRef": "main"},
        },
        {
            "id": "update",
            "type": "db.command",
            "name": "변경",
            "config": {
                "databaseRef": "main",
                "sql": "UPDATE users SET name=:name WHERE id=:id",
                "parameters": {"id": 1, "name": "changed"},
            },
        },
        {"id": "commit", "type": "transaction.commit", "name": "커밋", "config": {}},
        {
            "id": "response",
            "type": "response.http",
            "name": "응답",
            "config": {"status": 200, "body": {"changed": True}},
        },
    ]
    value["edges"] = [
        {"from": a, "to": b, "port": "success"}
        for a, b in [
            ("start", "begin"),
            ("begin", "update"),
            ("update", "commit"),
            ("commit", "response"),
        ]
    ]
    return value


def test_preview_rolls_back_and_runtime_commits(tmp_path, process):
    db = SqliteBridge(tmp_path)
    flow = Flow.model_validate(transaction_flow(process))
    assert Engine(db).run(flow, {"name": "test"}, True)["status"] == 200
    with sqlite3.connect(db.paths["main"]) as c:
        assert c.execute("SELECT name FROM users").fetchone()[0] == "main user"
    assert Engine(db).run(flow, {"name": "test"}, False)["status"] == 200
    with sqlite3.connect(db.paths["main"]) as c:
        assert c.execute("SELECT name FROM users").fetchone()[0] == "changed"


def test_unhandled_error_rolls_back_transaction(tmp_path, process):
    db = SqliteBridge(tmp_path)
    value = transaction_flow(process)
    value["nodes"][3] = {
        "id": "fail",
        "type": "error.raise",
        "name": "실패",
        "config": {"code": "REJECTED", "status": 409, "message": "업무 거절"},
    }
    value["nodes"] = value["nodes"][:4]
    value["edges"] = value["edges"][:3]
    value["edges"][2]["to"] = "fail"
    result = Engine(db).run(Flow.model_validate(value), {"name": "test"}, False)
    assert result["status"] == 409 and result["body"]["code"] == "REJECTED"
    with sqlite3.connect(db.paths["main"]) as c:
        assert c.execute("SELECT name FROM users").fetchone()[0] == "main user"


def test_query_row_and_byte_limits_and_binding(tmp_path):
    db = SqliteBridge(tmp_path)
    with sqlite3.connect(db.paths["main"]) as c:
        c.executemany(
            "INSERT INTO users VALUES(?,?)", [(i, "value" * 20) for i in range(2, 20)]
        )
    with db.connect("main") as conn:
        result = db.execute(
            conn,
            "main",
            "SELECT * FROM users ORDER BY id",
            {},
            False,
            str(uuid.uuid4()),
            time.monotonic() + 10,
            max_rows=2,
        )
        assert len(result["rows"]) == 2 and result["truncated"]
        result = db.execute(
            conn,
            "main",
            "SELECT * FROM users WHERE name=:name",
            {"name": "' OR 1=1 --"},
            False,
            str(uuid.uuid4()),
            time.monotonic() + 10,
        )
        assert not result["rows"]
        result = db.execute(
            conn,
            "main",
            "SELECT * FROM users ORDER BY id",
            {},
            False,
            str(uuid.uuid4()),
            time.monotonic() + 10,
            max_bytes=700,
        )
        import json

        assert len(json.dumps(result, ensure_ascii=False).encode()) <= 700
        assert result["truncated"]
