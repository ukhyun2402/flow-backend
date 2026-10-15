from __future__ import annotations

import json
import os
import re
import ssl
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager

import sqlglot
from sqlglot import exp

from .expressions import is_number, number, wire
from .models import Database, Fault


def sql_policy(sql: str, command: bool, vendor: str | None = None) -> str:
    if vendor is None:
        for dialect in ("oracle", "mysql"):
            try:
                return sql_policy(sql, command, dialect)
            except Fault:
                pass
        raise Fault("VALIDATION_ERROR", "지원하는 DB 방언의 단일 SQL 문이 아닙니다.")
    if not isinstance(sql, str) or len(sql) > 100000 or "${" in sql or "#{" in sql:
        raise Fault("VALIDATION_ERROR", "유효하지 않은 SQL입니다.")
    try:
        statements = sqlglot.parse(sql, read="mysql" if vendor == "mysql" else "oracle")
        statements = [s for s in statements if s is not None]
        if len(statements) != 1:
            raise ValueError()
        root = statements[0]
        if not isinstance(
            root, (exp.Insert, exp.Update, exp.Delete) if command else exp.Select
        ):
            raise ValueError()
        for item in root.walk():
            if item is not root and isinstance(
                item,
                (
                    exp.Insert,
                    exp.Update,
                    exp.Delete,
                    exp.Create,
                    exp.Drop,
                    exp.Command,
                    exp.Into,
                    exp.Lock,
                ),
            ):
                raise ValueError()
        if root.find(exp.Into) or root.find(exp.Lock):
            raise ValueError()
        return root.sql(dialect="mysql" if vendor == "mysql" else "oracle")
    except Exception:
        raise Fault(
            "VALIDATION_ERROR",
            "노드당 단일 SELECT 또는 INSERT/UPDATE/DELETE만 허용합니다.",
        ) from None


def bind_sql(sql: str, parameters: dict, vendor: str) -> tuple[str, dict | list]:
    # Tokenize quoted strings/identifiers and comments before rewriting bind markers.
    tokens = re.compile(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|--[^\n]*|/\*[\s\S]*?\*/|(?<!:):([A-Za-z_][A-Za-z0-9_]*)"
    )
    values, names = [], []

    def replace(match):
        name = match.group(1)
        if name is None:
            return match.group(0)
        names.append(name)
        if name not in parameters:
            raise Fault("VALIDATION_ERROR", f"SQL 파라미터가 누락되었습니다: {name}")
        v = parameters[name]
        if is_number(v):
            v = number(v)
        elif v is not None and not isinstance(v, (str, bool)):
            raise Fault(
                "VALIDATION_ERROR", "SQL 파라미터는 scalar 또는 정밀 숫자여야 합니다."
            )
        values.append(v)
        return (
            ":" + name
            if vendor == "oracle"
            else "\x00FLOW_BIND\x00"
            if vendor == "mysql"
            else "?"
        )

    query = tokens.sub(replace, sql)
    if vendor == "mysql":
        # DB-API percent interpolation also sees percent symbols inside SQL literals.
        query = query.replace("%", "%%").replace("\x00FLOW_BIND\x00", "%s")
    return query, dict(zip(names, values)) if vendor == "oracle" else values


def parameter_names(sql: str) -> list[str]:
    class AnyParameters(dict):
        def __contains__(self, key):
            return True

        def __getitem__(self, key):
            return None

    _, values = bind_sql(sql, AnyParameters(), "oracle")
    return list(values)


class Executions:
    def __init__(self):
        self.lock = threading.RLock()
        self.runs: dict[str, tuple[threading.Event, Callable | None]] = {}

    @contextmanager
    def run(self, id_: str):
        with self.lock:
            if id_ in self.runs:
                raise Fault("EXECUTION_CONFLICT", "실행 ID가 중복됩니다.", 409)
            self.runs[id_] = (threading.Event(), None)
        try:
            yield
        finally:
            with self.lock:
                self.runs.pop(id_, None)

    def check(self, id_: str):
        with self.lock:
            if self.runs.get(id_, (threading.Event(), None))[0].is_set():
                raise Fault("CANCELLED", "실행이 취소되었습니다.", 499)

    def statement(self, id_: str, cancel: Callable | None):
        with self.lock:
            if id_ in self.runs:
                self.runs[id_] = (self.runs[id_][0], cancel)

    def cancel(self, id_: str) -> bool:
        with self.lock:
            run = self.runs.get(id_)
            if not run:
                return False
            run[0].set()
            cancel = run[1]
        if cancel:
            try:
                cancel()
            except Exception:
                raise Fault(
                    "DB_ERROR", "드라이버의 취소 결과를 확인할 수 없습니다.", 502
                ) from None
        return True


class Databases:
    def __init__(
        self,
        catalog: Callable[[], list[Database]],
        executions: Executions | None = None,
    ):
        self.catalog = catalog
        self.executions = executions or Executions()
        self.limits: dict[str, threading.BoundedSemaphore] = {}
        self.lock = threading.Lock()

    def get(self, id_: str) -> Database:
        config = next((db for db in self.catalog() if db.id == id_), None)
        if config is None:
            raise Fault("DB_ERROR", "등록되지 않은 DB입니다.")
        return config

    def allow_write(self, id_: str, preview: bool):
        db = self.get(id_)
        if db.readonly:
            raise Fault("FORBIDDEN", "읽기 전용으로 등록된 DB입니다.", 403)
        if preview and (
            db.environment not in ("development", "test")
            or not db.rollbackSafetyVerified
        ):
            raise Fault(
                "FORBIDDEN",
                "변경 미리보기는 롤백 안전성을 확인한 개발·테스트 DB에서만 허용합니다.",
                403,
            )

    @contextmanager
    def connect(self, id_: str, timeout: float = 10, control: bool = False):
        db = self.get(id_)
        password = os.environ.get(db.passwordSecretRef)
        if password is None or not (db.host or db.dsn):
            raise Fault(
                "DB_NOT_CONFIGURED", "DB 주소와 비밀정보 환경 변수를 설정하세요.", 503
            )
        with self.lock:
            limit = self.limits.setdefault(
                id_ + (":control" if control else ""),
                threading.BoundedSemaphore(1 if control else 5),
            )
        if not limit.acquire(timeout=max(0.1, min(timeout, 5))):
            raise Fault("TIMEOUT", "DB 연결 대기 시간이 초과되었습니다.", 504)
        conn = None
        try:
            if db.vendor == "mysql":
                import pymysql

                conn = pymysql.connect(
                    host=db.host,
                    port=db.port or 3306,
                    database=db.database,
                    user=db.username,
                    password=password,
                    charset="utf8mb4",
                    autocommit=False,
                    connect_timeout=max(1, int(min(timeout, 5))),
                    read_timeout=max(1, int(timeout)),
                    write_timeout=max(1, int(timeout)),
                    ssl=ssl.create_default_context() if db.tls else None,
                )
                with conn.cursor() as c:
                    c.execute("SET time_zone = '+00:00'")
            elif db.vendor == "oracle":
                import oracledb

                conn = oracledb.connect(
                    user=db.username,
                    password=password,
                    dsn=f"{'tcps' if db.tls else 'tcp'}://{db.host}:{db.port or 1521}/{db.database}",
                    tcp_connect_timeout=min(timeout, 5),
                )
                conn.call_timeout = max(1, int(timeout * 1000))
                with conn.cursor() as c:
                    c.execute("ALTER SESSION SET TIME_ZONE = '+00:00'")
            else:
                import pyodbc

                if not db.dsn:
                    raise Fault(
                        "DB_NOT_CONFIGURED", "Tibero ODBC DSN을 설정하세요.", 503
                    )

                def escape(v):
                    return "{" + v.replace("}", "}}") + "}"

                conn = pyodbc.connect(
                    f"DSN={escape(db.dsn)};UID={escape(db.username)};PWD={escape(password)}",
                    autocommit=False,
                    timeout=max(1, int(min(timeout, 5))),
                )
                conn.timeout = max(1, int(timeout))
            yield conn
        except Fault:
            raise
        except Exception as error:
            raise self.error(error) from None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            limit.release()

    @staticmethod
    def error(error: Exception) -> Fault:
        code = getattr(error, "code", None)
        if not code and error.args:
            code = getattr(
                error.args[0],
                "code",
                error.args[0] if isinstance(error.args[0], int) else None,
            )
        if code in (1205, 3024) or isinstance(error, TimeoutError):
            return Fault("TIMEOUT", "DB 작업 시간이 초과되었습니다.", 504)
        return Fault(
            "DB_ERROR",
            f"DB 작업에 실패했습니다.{f' (vendorCode={code})' if isinstance(code, int) else ''}",
            502,
        )

    def execute(
        self,
        conn,
        id_: str,
        sql: str,
        parameters: dict,
        command: bool,
        execution_id: str,
        deadline: float,
        max_rows=100,
        max_bytes=5_000_000,
    ) -> dict:
        db = self.get(id_)
        sql = sql_policy(sql, command, db.vendor)
        if not command:
            sql = f"SELECT * FROM ({sql}) flow_limited " + (
                f"LIMIT {max_rows + 1}"
                if db.vendor == "mysql"
                else f"WHERE ROWNUM <= {max_rows + 1}"
            )
        query, values = bind_sql(sql, parameters, db.vendor)
        started = time.monotonic()
        if db.vendor == "mysql":
            import pymysql

            cursor = conn.cursor(pymysql.cursors.SSCursor)
        else:
            cursor = conn.cursor()
        try:
            if db.vendor == "oracle":
                conn.call_timeout = max(1, int((deadline - time.monotonic()) * 1000))
                cursor.arraysize = 1
            elif db.vendor == "tibero":
                conn.timeout = max(1, int(deadline - time.monotonic()))
            cancel = getattr(cursor, "cancel", None) or getattr(conn, "cancel", None)
            if db.vendor == "mysql":
                thread_id = conn.thread_id()

                def cancel():
                    with self.connect(id_, 5, control=True) as control:
                        with control.cursor() as c:
                            c.execute("KILL QUERY %s", (thread_id,))

            self.executions.statement(execution_id, cancel)
            self.executions.check(execution_id)
            cursor.execute(query, values)
            if command:
                return {
                    "affectedRows": cursor.rowcount,
                    "durationMs": round((time.monotonic() - started) * 1000),
                }
            columns = [
                {
                    "name": d[0],
                    "type": str(d[1]),
                    "nullable": d[6] if len(d) > 6 else None,
                }
                for d in cursor.description
            ]
            if len({c["name"] for c in columns}) != len(columns):
                raise Fault(
                    "DB_ERROR", "중복 결과 컬럼에 고유한 별칭을 지정하세요.", 422
                )
            out = {"columns": columns, "rows": [], "row": None, "truncated": False}
            used = len(json.dumps(out, ensure_ascii=False).encode()) + 256
            if used > max_bytes:
                raise Fault(
                    "DB_ERROR", "컬럼 메타데이터가 응답 크기 제한을 초과했습니다.", 413
                )
            while True:
                self.executions.check(execution_id)
                if time.monotonic() >= deadline:
                    raise Fault("TIMEOUT", "조회 시간이 초과되었습니다.", 504)
                row = cursor.fetchone()
                if row is None:
                    break
                if len(out["rows"]) >= max_rows:
                    out["truncated"] = True
                    break
                item = {}
                for c, value in zip(columns, row):
                    if isinstance(value, (bytes, bytearray, memoryview)) or hasattr(
                        value, "read"
                    ):
                        raise Fault(
                            "DB_ERROR",
                            "LOB·바이너리 미리보기는 지원하지 않습니다.",
                            422,
                        )
                    if isinstance(value, str) and len(value) > max_bytes:
                        raise Fault(
                            "DB_ERROR", "단일 필드 크기 제한을 초과했습니다.", 413
                        )
                    item[c["name"]] = wire(value)
                    if (
                        len(json.dumps(item, ensure_ascii=False).encode()) + used
                        > max_bytes
                    ):
                        out["truncated"] = True
                        break
                if out["truncated"]:
                    break
                cost = (
                    len(json.dumps(item, ensure_ascii=False).encode())
                    * (2 if not out["rows"] else 1)
                    + 1
                )
                if used + cost > max_bytes:
                    out["truncated"] = True
                    break
                used += cost
                out["rows"].append(item)
            out["row"] = out["rows"][0] if out["rows"] else None
            out["durationMs"] = round((time.monotonic() - started) * 1000)
            return out
        except Fault:
            raise
        except Exception as error:
            self.executions.check(execution_id)
            raise self.error(error) from None
        finally:
            self.executions.statement(execution_id, None)
            try:
                cursor.close()
            except Exception:
                pass

    def metadata(self, id_: str) -> dict:
        db = self.get(id_)
        with self.connect(id_) as conn:
            with conn.cursor() as c:
                if db.vendor == "mysql":
                    c.execute(
                        "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,IS_NULLABLE FROM information_schema.columns WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 2000",
                        (db.database,),
                    )
                    rows = c.fetchmany(2000)
                elif db.vendor == "oracle":
                    c.execute(
                        "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,NULLABLE FROM USER_TAB_COLUMNS ORDER BY TABLE_NAME,COLUMN_ID FETCH FIRST 2000 ROWS ONLY"
                    )
                    rows = c.fetchmany(2000)
                else:
                    rows = [
                        (r.table_name, r.column_name, r.type_name, r.nullable)
                        for r in c.columns(schema=db.schemaName or None).fetchmany(2000)
                    ]
                return {
                    "columns": [
                        {"table": r[0], "name": r[1], "type": r[2], "nullable": r[3]}
                        for r in rows
                    ],
                    "limited": len(rows) == 2000,
                }
