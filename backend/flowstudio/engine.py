from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from .database import Databases
from .expressions import MISSING, Expressions, contract, wire
from .models import Fault, Flow
from .validation import require_valid


def normalize_input(flow: Flow, request: dict) -> dict:
    trigger = next(n for n in flow.nodes if n.type == "trigger.http")
    out = {}
    for key, mapping in trigger.config.get("input", {}).items():
        value = request
        for part in mapping["source"].split("."):
            value = value.get(part, MISSING) if isinstance(value, dict) else MISSING
            if value is MISSING:
                break
        if value is MISSING:
            continue
        convert = mapping.get("convert")
        try:
            if convert == "integer":
                if isinstance(value, bool) or not __import__("re").fullmatch(
                    r"-?[0-9]+", str(value)
                ):
                    raise ValueError()
                value = wire(int(value))
            elif convert == "number":
                from .expressions import number

                value = wire(number({"type": "decimal", "value": str(value)}))
            elif convert == "string":
                if isinstance(value, (dict, list)) or value is None:
                    raise ValueError()
                value = str(value)
            elif convert == "boolean":
                if str(value).lower() not in ("true", "false"):
                    raise ValueError()
                value = str(value).lower() == "true"
        except (ValueError, TypeError):
            raise Fault(
                "VALIDATION_ERROR", f"입력 변환에 실패했습니다: {key}"
            ) from None
        out[key] = value
    return out


class Engine:
    def __init__(self, databases: Databases, services: dict | None = None):
        self.databases, self.services = databases, services or {}

    def http(self, config: dict, expression: Expressions, deadline: float) -> dict:
        service = self.services.get(config["serviceRef"])
        if not service:
            raise Fault("EXTERNAL_API_ERROR", "외부 서비스 연결을 설정하세요.", 503)
        base = service["baseUrl"].rstrip("/")
        path = config.get("path", "")
        if any(v in path for v in ("..", ":", "\\", "#", "?")) or path.startswith("//"):
            raise Fault("VALIDATION_ERROR", "유효하지 않은 외부 서비스 경로입니다.")
        if urlsplit(base).scheme != "https" and not service.get(
            "allowHttpForDevelopment"
        ):
            raise Fault("EXTERNAL_API_ERROR", "외부 서비스에는 HTTPS가 필요합니다.")
        headers = {"Accept": "application/json"}
        if service.get("bearerSecretRef"):
            secret = os.environ.get(service["bearerSecretRef"])
            if secret is None:
                raise Fault(
                    "EXTERNAL_API_ERROR", "외부 서비스 비밀정보가 없습니다.", 503
                )
            headers["Authorization"] = "Bearer " + secret
        body = wire(expression.evaluate(config.get("body")))
        try:
            with (
                httpx.Client(
                    timeout=max(0.01, deadline - time.monotonic()),
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    config.get("method", "GET"),
                    base + "/" + path.lstrip("/"),
                    json=body,
                    headers=headers,
                ) as response,
            ):
                if not 200 <= response.status_code < 300:
                    raise Fault(
                        "EXTERNAL_API_ERROR",
                        "외부 서비스가 오류를 반환했습니다.",
                        502,
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > 1_048_576:
                        raise Fault(
                            "EXTERNAL_API_ERROR",
                            "외부 응답 크기 제한을 초과했습니다.",
                            413,
                        )
                    data.extend(chunk)
                return {
                    "status": response.status_code,
                    "body": json.loads(data) if data else None,
                }
        except Fault:
            raise
        except httpx.TimeoutException:
            raise Fault(
                "TIMEOUT", "외부 API 호출 시간이 초과되었습니다.", 504
            ) from None
        except Exception:
            raise Fault(
                "EXTERNAL_API_ERROR", "외부 API 호출에 실패했습니다.", 502
            ) from None

    def run(
        self, flow: Flow, input_: dict, preview=True, execution_id: str | None = None
    ) -> dict:
        require_valid(flow)
        contract(flow.inputSchema, input_)
        execution_id = execution_id or str(uuid.uuid4())
        try:
            uuid.UUID(execution_id)
        except ValueError:
            raise Fault("VALIDATION_ERROR", "실행 ID는 UUID여야 합니다.") from None
        nodes = {n.id: n for n in flow.nodes}
        edges: dict[str, dict[str, str]] = {}
        for e in flow.edges:
            edges.setdefault(e.from_, {})[e.port] = e.to
        current = next(n.id for n in flow.nodes if n.type == "trigger.http")
        context = {
            "input": input_,
            "nodes": {},
            "context": {
                "requestId": execution_id,
                "startedAt": datetime.now(UTC).isoformat(),
            },
        }
        evaluator, traces = Expressions(context), []
        started = time.monotonic()
        deadline = started + flow.settings.get("timeoutMs", 10000) / 1000
        tx, tx_scope = None, None
        with self.databases.executions.run(execution_id):
            try:
                while current:
                    node, port = nodes[current], "success"
                    at, tick, output = (
                        datetime.now(UTC).isoformat(),
                        time.monotonic(),
                        {},
                    )
                    c = node.config

                    def trace(status, code=None, node=node, at=at, tick=tick):
                        traces.append(
                            {
                                "executionId": execution_id,
                                "flowId": flow.id,
                                "flowRevision": flow.revision,
                                "nodeId": node.id,
                                "status": status,
                                "startedAt": at,
                                "durationMs": round(
                                    (time.monotonic() - tick) * 1000, 3
                                ),
                                "errorCode": code,
                            }
                        )

                    try:
                        self.databases.executions.check(execution_id)
                        if time.monotonic() >= deadline:
                            raise Fault(
                                "TIMEOUT", "Flow 실행 시간이 초과되었습니다.", 504
                            )
                        match node.type:
                            case "trigger.http":
                                output = input_
                            case "validate":
                                output = (
                                    evaluator.evaluate(c["value"])
                                    if "value" in c
                                    else input_
                                )
                                contract(c["schema"], output)
                            case "transform":
                                output = evaluator.evaluate(c["mapping"])
                            case "branch":
                                condition = evaluator.evaluate(c["condition"])
                                if type(condition) is not bool:
                                    raise Fault(
                                        "VALIDATION_ERROR",
                                        "분기 결과는 boolean이어야 합니다.",
                                    )
                                port = "true" if condition else "false"
                            case "db.query" | "db.command":
                                command = node.type == "db.command"
                                if command:
                                    self.databases.allow_write(
                                        c["databaseRef"], preview
                                    )
                                parameters = {
                                    name: evaluator.evaluate(value)
                                    for name, value in c.get("parameters", {}).items()
                                }
                                if tx is not None:
                                    output = self.databases.execute(
                                        tx,
                                        c["databaseRef"],
                                        c["sql"],
                                        parameters,
                                        command,
                                        execution_id,
                                        deadline,
                                    )
                                else:
                                    with self.databases.connect(
                                        c["databaseRef"],
                                        max(0.01, deadline - time.monotonic()),
                                    ) as connection:
                                        try:
                                            output = self.databases.execute(
                                                connection,
                                                c["databaseRef"],
                                                c["sql"],
                                                parameters,
                                                command,
                                                execution_id,
                                                deadline,
                                            )
                                            if command and not preview:
                                                connection.commit()
                                        finally:
                                            if preview or not command:
                                                connection.rollback()
                                if (
                                    not command
                                    and c.get("resultMode") == "zeroOrOne"
                                    and (len(output["rows"]) > 1 or output["truncated"])
                                ):
                                    raise Fault(
                                        "DB_ERROR", "결과가 2행 이상입니다.", 422
                                    )
                            case "transaction.begin":
                                if preview:
                                    self.databases.allow_write(c["databaseRef"], True)
                                if c.get("isolation") not in (
                                    None,
                                    "READ_COMMITTED",
                                    "REPEATABLE_READ",
                                    "SERIALIZABLE",
                                ):
                                    raise Fault(
                                        "VALIDATION_ERROR",
                                        "지원하지 않는 격리 수준입니다.",
                                    )
                                tx_scope = self.databases.connect(
                                    c["databaseRef"],
                                    max(0.01, deadline - time.monotonic()),
                                )
                                tx = tx_scope.__enter__()
                                if c.get("isolation"):
                                    level = c["isolation"].replace("_", " ")
                                    vendor = self.databases.get(c["databaseRef"]).vendor
                                    if (
                                        vendor in ("oracle", "tibero")
                                        and level == "REPEATABLE READ"
                                    ):
                                        raise Fault(
                                            "VALIDATION_ERROR",
                                            "해당 DB가 지원하지 않는 격리 수준입니다.",
                                        )
                                    cursor = tx.cursor()
                                    try:
                                        cursor.execute(
                                            "SET TRANSACTION ISOLATION LEVEL " + level
                                        )
                                    finally:
                                        cursor.close()
                            case "transaction.commit" | "transaction.rollback":
                                if preview or node.type == "transaction.rollback":
                                    tx.rollback()
                                else:
                                    tx.commit()
                                tx_scope.__exit__(None, None, None)
                                tx, tx_scope = None, None
                            case "http.call":
                                output = self.http(c, evaluator, deadline)
                            case "error.raise":
                                raise Fault(
                                    c["code"],
                                    c.get("message", "업무 오류"),
                                    c["status"],
                                    "BUSINESS_ERROR",
                                )
                            case "response.http":
                                body = wire(evaluator.evaluate(c["body"]))
                                contract(flow.outputSchema, body)
                                headers = evaluator.evaluate(c.get("headers", {}))
                                for key, value in headers.items():
                                    if (
                                        key.lower()
                                        not in (
                                            "x-request-id",
                                            "cache-control",
                                            "location",
                                            "content-language",
                                        )
                                        or not isinstance(value, str)
                                        or "\r" in value
                                        or "\n" in value
                                    ):
                                        raise Fault(
                                            "VALIDATION_ERROR",
                                            "허용되지 않는 응답 헤더입니다.",
                                        )
                                trace("SUCCESS")
                                return {
                                    "executionId": execution_id,
                                    "status": c["status"],
                                    "headers": headers,
                                    "body": body,
                                    "trace": traces,
                                    "durationMs": round(
                                        (time.monotonic() - started) * 1000, 3
                                    ),
                                }
                        if "outputSchema" in c:
                            contract(c["outputSchema"], output)
                        context["nodes"][current] = {"output": wire(output)}
                        trace("SUCCESS")
                    except Exception as error:
                        fault = (
                            error
                            if isinstance(error, Fault)
                            else self.databases.error(error)
                        )
                        trace("ERROR", fault.code)
                        port = "error"
                        if port not in edges.get(current, {}):
                            return {
                                "executionId": execution_id,
                                "status": fault.status,
                                "headers": {},
                                "body": fault.response(),
                                "trace": traces,
                                "durationMs": round(
                                    (time.monotonic() - started) * 1000, 3
                                ),
                            }
                    current = edges.get(current, {}).get(port)
                raise Fault("INTERNAL_ERROR", "응답 노드가 실행되지 않았습니다.", 500)
            finally:
                if tx is not None:
                    try:
                        tx.rollback()
                    except Exception:
                        raise Fault(
                            "DB_ERROR", "트랜잭션 롤백 결과를 확인할 수 없습니다.", 502
                        ) from None
                    finally:
                        tx_scope.__exit__(None, None, None)
