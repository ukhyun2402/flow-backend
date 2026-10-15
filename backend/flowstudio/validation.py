from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from .expressions import schema_safe
from .models import Fault, Flow

TYPES = {
    "trigger.http",
    "validate",
    "transform",
    "branch",
    "db.query",
    "db.command",
    "http.call",
    "transaction.begin",
    "transaction.commit",
    "transaction.rollback",
    "error.raise",
    "response.http",
}
ARITY = {
    "eq": 2,
    "ne": 2,
    "gt": 2,
    "gte": 2,
    "lt": 2,
    "lte": 2,
    "not": 1,
    "isNull": 1,
    "notNull": 1,
    "add": 2,
    "subtract": 2,
    "multiply": 2,
    "divide": 2,
    "trim": 1,
    "contains": 2,
    "toNumber": 1,
    "toString": 1,
    "toDateTime": 1,
}

CONFIG_PROPERTIES = {
    "trigger.http": {
        "method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "path": {"type": "string"},
        "input": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["source"],
                "properties": {
                    "source": {"type": "string"},
                    "convert": {"enum": ["integer", "number", "boolean", "string"]},
                },
                "additionalProperties": False,
            },
        },
    },
    "validate": {"schema": {"type": "object"}, "value": {}},
    "transform": {"mapping": {}},
    "branch": {"condition": {"type": ["boolean", "object"]}},
    "db.query": {
        "databaseRef": {"type": "string"},
        "sql": {"type": "string"},
        "parameters": {"type": "object"},
        "resultMode": {"enum": ["many", "zeroOrOne"]},
    },
    "db.command": {
        "databaseRef": {"type": "string"},
        "sql": {"type": "string"},
        "parameters": {"type": "object"},
    },
    "http.call": {
        "serviceRef": {"type": "string"},
        "path": {"type": "string"},
        "method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "body": {},
    },
    "transaction.begin": {
        "databaseRef": {"type": "string"},
        "isolation": {"enum": ["READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE"]},
    },
    "transaction.commit": {},
    "transaction.rollback": {},
    "response.http": {
        "status": {"type": "integer", "minimum": 200, "maximum": 599},
        "body": {},
        "headers": {"type": "object"},
    },
    "error.raise": {
        "code": {"type": "string", "minLength": 1, "maxLength": 80},
        "message": {"type": "string", "maxLength": 1000},
        "status": {"type": "integer", "minimum": 400, "maximum": 599},
    },
}


def validate(flow: Flow, allowed_databases: set[str] | None = None) -> list[dict]:
    issues: list[dict] = []

    def add(node: str | None, field: str, message: str, code="FLOW_INVALID"):
        item = {
            "code": code,
            "flowId": flow.id,
            "nodeId": node,
            "field": field,
            "message": message,
        }
        if item not in issues:
            issues.append(item)

    nodes = {n.id: n for n in flow.nodes}
    if len(nodes) != len(flow.nodes):
        add(None, "nodes", "노드 ID가 중복됩니다.")
    starts = [n for n in flow.nodes if n.type == "trigger.http"]
    if len(starts) != 1:
        add(None, "nodes", "HTTP 진입 노드는 정확히 하나여야 합니다.")
    resources = set(flow.resources.get("databases", []))
    if allowed_databases is not None and not resources <= allowed_databases:
        add(None, "resources.databases", "프로젝트에 연결되지 않은 DB를 참조합니다.")
    for schema in (flow.inputSchema, flow.outputSchema):
        try:
            schema_safe(schema)
            Draft202012Validator.check_schema(schema)
        except (Fault, SchemaError):
            add(None, "schemas", "JSON Schema를 확인하세요.")
    timeout = flow.settings.get("timeoutMs", 10000)
    if type(timeout) is not int or not 1 <= timeout <= 60000:
        add(None, "settings.timeoutMs", "시간 제한은 1~60000ms입니다.")
    if flow.settings.get("authentication") not in ("public", "bearer"):
        add(None, "settings.authentication", "공개 또는 Bearer 인증 정책을 명시하세요.")
    required = {
        "trigger.http": ("method", "path"),
        "validate": ("schema",),
        "transform": ("mapping",),
        "branch": ("condition",),
        "db.query": ("databaseRef", "sql"),
        "db.command": ("databaseRef", "sql"),
        "http.call": ("serviceRef", "path"),
        "transaction.begin": ("databaseRef",),
        "response.http": ("status", "body"),
        "error.raise": ("code", "status"),
    }

    def inspect(expr: Any, node_id: str, depth=0):
        if depth > 64:
            add(node_id, "config", "표현식 깊이가 64를 초과합니다.")
            return
        if isinstance(expr, dict):
            if "literal" in expr:
                return
            if "op" in expr:
                op, args = expr["op"], expr.get("args")
                if (
                    not isinstance(op, str)
                    or op not in ARITY
                    and op not in ("and", "or", "concat", "coalesce")
                    or not isinstance(args, list)
                ):
                    add(node_id, "config", "연산자 또는 args가 유효하지 않습니다.")
                    return
                if (
                    op in ARITY
                    and len(args) != ARITY[op]
                    or op in ("and", "or")
                    and not args
                ):
                    add(node_id, "config", "연산자 인자 개수가 맞지 않습니다.")
            for value in expr.values():
                inspect(value, node_id, depth + 1)
        elif isinstance(expr, list):
            for value in expr:
                inspect(value, node_id, depth + 1)

    for n in flow.nodes:
        c = n.config
        if n.type not in TYPES:
            add(n.id, "type", "지원하지 않는 노드입니다.")
            continue
        properties = CONFIG_PROPERTIES[n.type] | {"outputSchema": {"type": "object"}}
        error = next(
            Draft202012Validator(
                {
                    "type": "object",
                    "properties": properties,
                    "additionalProperties": False,
                }
            ).iter_errors(c),
            None,
        )
        if error:
            add(n.id, "config", "노드 설정의 필드 또는 타입이 유효하지 않습니다.")
            continue
        for key in required.get(n.type, ()):
            if key not in c:
                add(n.id, "config." + key, "필수 설정입니다.")
        if n.type.startswith("db.") or n.type == "transaction.begin":
            if c.get("databaseRef") not in resources:
                add(n.id, "config.databaseRef", "Flow DB 자원에 선언되지 않았습니다.")
        if n.type == "trigger.http":
            if (
                c.get("method") not in ("GET", "POST", "PUT", "PATCH", "DELETE")
                or not re.fullmatch(r"/[A-Za-z0-9_/{}/-]*", c.get("path", ""))
                or c.get("path", "").startswith("/api/")
            ):
                add(n.id, "config", "HTTP 메서드 또는 경로를 확인하세요.")
            for mapping in c.get("input", {}).values():
                if (
                    not isinstance(mapping, dict)
                    or not re.match(
                        r"^(body|path|query|headers)\.", mapping.get("source", "")
                    )
                    or mapping.get("convert")
                    not in (None, "integer", "number", "string", "boolean")
                ):
                    add(n.id, "config.input", "입력 매핑을 확인하세요.")
        if (
            n.type == "branch"
            and "condition" in c
            and not isinstance(c["condition"], (bool, dict))
        ):
            add(n.id, "config.condition", "분기 조건은 boolean이어야 합니다.")
        if n.type == "http.call" and c.get("serviceRef") not in flow.resources.get(
            "services", []
        ):
            add(n.id, "config.serviceRef", "외부 서비스 자원이 선언되지 않았습니다.")
        if n.type.startswith("db.") and "sql" in c:
            from .database import parameter_names, sql_policy

            try:
                sql_policy(c["sql"], n.type == "db.command")
                if not set(parameter_names(c["sql"])) <= set(c.get("parameters", {})):
                    add(
                        n.id, "config.parameters", "SQL 파라미터 매핑이 누락되었습니다."
                    )
            except Fault as e:
                add(n.id, "config.sql", e.message)
        if n.type in ("response.http", "error.raise") and (
            type(c.get("status")) is not int or not 200 <= c.get("status", 0) <= 599
        ):
            add(n.id, "config.status", "HTTP 상태 코드를 확인하세요.")
        try:
            schema_safe(c)
            for key in ("schema", "outputSchema"):
                if key in c:
                    Draft202012Validator.check_schema(c[key])
        except (Fault, SchemaError):
            add(n.id, "config", "외부 스키마 참조 또는 잘못된 계약입니다.")
        for field in ("condition", "mapping", "body", "value", "headers"):
            if field in c:
                inspect(c[field], n.id)
        for value in c.get("parameters", {}).values():
            inspect(value, n.id)
        if not issues:
            from .typecheck import check_node

            try:
                check_node(n, flow, nodes)
            except Fault as error:
                add(n.id, "config", error.message)
    next_: dict[str, dict[str, str]] = {}
    for e in flow.edges:
        if e.from_ not in nodes or e.to not in nodes:
            add(e.from_, "edges", "연결 대상 노드가 없습니다.")
            continue
        kind = nodes[e.from_].type
        ports = (
            set()
            if kind == "response.http"
            else {"true", "false", "error"}
            if kind == "branch"
            else {"error"}
            if kind == "error.raise"
            else {"success", "error"}
        )
        outgoing = next_.setdefault(e.from_, {})
        if e.port not in ports:
            allowed = ", ".join(sorted(ports)) or "없음 (종료 노드)"
            add(
                e.from_,
                "edges",
                f"'{e.port}' 경로를 사용할 수 없습니다. 허용 경로: {allowed}.",
            )
            continue
        if e.port in outgoing:
            add(e.from_, "edges", f"'{e.port}' 출력 경로가 중복되었습니다.")
            continue
        outgoing[e.port] = e.to
    if issues:
        return issues
    reached, budget = set(), [20000]

    def refs(expr, available, node_id):
        if isinstance(expr, dict):
            if "literal" in expr:
                return
            if "ref" in expr:
                ref = expr["ref"]
                parts = str(ref).split(".")
                if parts[0] == "nodes":
                    if (
                        len(parts) < 3
                        or parts[1] not in available
                        or parts[2] != "output"
                    ):
                        add(
                            node_id,
                            "config",
                            "현재 경로에서 보장되지 않는 노드 출력입니다.",
                            "FLOW_INVALID_REFERENCE",
                        )
                elif parts[0] != "input" and ref not in (
                    "context.requestId",
                    "context.startedAt",
                ):
                    add(node_id, "config", "허용하지 않는 참조 영역입니다.")
            for v in expr.values():
                refs(v, available, node_id)
        elif isinstance(expr, list):
            for v in expr:
                refs(v, available, node_id)

    def walk(id_, stack, available, tx):
        budget[0] -= 1
        if budget[0] < 0:
            add(id_, "edges", "경로 분석 한도를 초과했습니다.")
            return
        if id_ in stack:
            add(id_, "edges", "순환 연결은 허용하지 않습니다.")
            return
        reached.add(id_)
        n, after = nodes[id_], tx
        for field in ("condition", "mapping", "body", "value", "headers"):
            if field in n.config:
                refs(n.config[field], available, id_)
        for value in n.config.get("parameters", {}).values():
            refs(value, available, id_)
        if n.type == "transaction.begin":
            if tx:
                add(id_, "config", "중첩 트랜잭션은 허용하지 않습니다.")
            after = n.config["databaseRef"]
        elif n.type in ("transaction.commit", "transaction.rollback"):
            if not tx:
                add(id_, "config", "활성 트랜잭션이 없습니다.")
            after = None
        elif n.type.startswith("db.") and tx and n.config["databaseRef"] != tx:
            add(
                id_,
                "config.databaseRef",
                "트랜잭션 내부에서 다른 DB를 사용할 수 없습니다.",
            )
        elif n.type == "http.call" and tx:
            add(id_, "config", "트랜잭션 내부 HTTP 호출은 금지합니다.")
        elif n.type == "response.http" and tx:
            add(id_, "config", "활성 트랜잭션 상태에서 응답할 수 없습니다.")
        edges = next_.get(id_, {})
        if n.type == "branch" and not {"true", "false"} <= set(edges):
            add(id_, "edges", "true와 false 경로가 모두 필요합니다.")
        if (
            n.type not in ("branch", "response.http", "error.raise")
            and "success" not in edges
        ):
            add(id_, "edges", "정상 경로가 응답으로 끝나지 않습니다.")
        for port, target in edges.items():
            if port == "error" and n.type.startswith("transaction."):
                add(id_, "edges", "트랜잭션 노드의 오류 경로는 지원하지 않습니다.")
            walk(
                target,
                stack | {id_},
                available | ({id_} if port != "error" else set()),
                tx if port == "error" else after,
            )

    walk(starts[0].id, set(), set(), None)
    for id_ in nodes.keys() - reached:
        add(id_, "nodes", "도달할 수 없는 노드입니다.")
    return issues


def require_valid(flow: Flow, allowed_databases: set[str] | None = None) -> None:
    issues = validate(flow, allowed_databases)
    if issues:
        raise Fault("VALIDATION_ERROR", issues[0]["message"])
