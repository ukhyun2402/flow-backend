"""Conservative expression checks; unknown SQL result types need outputSchema."""

from .expressions import is_number
from .models import Fault, Flow


def compatible(actual, expected):
    return (
        actual == "unknown"
        or expected == "unknown"
        or actual == expected
        or actual == "integer"
        and expected == "number"
    )


def schema_type(schema):
    if not isinstance(schema, dict):
        return "unknown"
    if schema.get("properties", {}).get("type", {}).get("const") in (
        "decimal",
        "integer",
    ):
        return "number"
    value = schema.get("type", "unknown")
    return value if isinstance(value, str) else "unknown"


def infer(value, flow: Flow, nodes, depth=0, seen=None):
    if depth > 64:
        raise Fault("VALIDATION_ERROR", "표현식 타입 분석 깊이를 초과했습니다.")
    seen = seen or set()
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        for item in value:
            infer(item, flow, nodes, depth + 1, seen)
        return "array"
    if not isinstance(value, dict):
        return "unknown"
    if "literal" in value:
        literal = value["literal"]
        return (
            "object"
            if isinstance(literal, dict) and not is_number(literal)
            else infer(literal, flow, nodes, depth + 1, seen)
        )
    if "ref" in value:
        parts = str(value["ref"]).split(".")
        schema = None
        start = 0
        if parts[0] == "input":
            schema = flow.inputSchema
            start = 1
        elif parts[0] == "context":
            return "string"
        elif len(parts) >= 3 and parts[0] == "nodes" and parts[1] in nodes:
            source = nodes[parts[1]]
            if source.id in seen:
                return "unknown"
            schema = source.config.get("outputSchema")
            start = 3
            if schema is None and source.type == "transform":
                mapped = source.config.get("mapping")
                for part in parts[3:]:
                    if (
                        not isinstance(mapped, dict)
                        or "ref" in mapped
                        or "op" in mapped
                    ):
                        return "unknown"
                    mapped = mapped.get(part)
                return infer(mapped, flow, nodes, depth + 1, seen | {source.id})
        if schema is None:
            return "unknown"
        for part in parts[start:]:
            if schema.get("type") == "array" and part.isdigit():
                schema = schema.get("items", {})
            else:
                next_ = schema.get("properties", {}).get(part)
                if next_ is None:
                    if schema.get("additionalProperties") is False:
                        raise Fault(
                            "VALIDATION_ERROR", "입력 계약에 선언되지 않은 필드입니다."
                        )
                    return "unknown"
                schema = next_
        return schema_type(schema)
    if "op" not in value:
        for item in value.values():
            infer(item, flow, nodes, depth + 1, seen)
        return "object"
    op = value["op"]
    types = [infer(arg, flow, nodes, depth + 1, seen) for arg in value.get("args", [])]
    numeric = {"gt", "gte", "lt", "lte", "add", "subtract", "multiply", "divide"}
    logical = {"and", "or", "not"}
    string = {"concat", "trim", "contains", "toNumber", "toDateTime"}
    expected = (
        "number"
        if op in numeric
        else "boolean"
        if op in logical
        else "string"
        if op in string
        else None
    )
    if expected and any(not compatible(t, expected) for t in types):
        raise Fault("VALIDATION_ERROR", f"{op} 연산에는 {expected} 타입이 필요합니다.")
    if op in {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "and",
        "or",
        "not",
        "isNull",
        "notNull",
        "contains",
    }:
        return "boolean"
    if op in {"add", "subtract", "multiply", "divide", "toNumber"}:
        return (
            "integer"
            if op in {"add", "subtract", "multiply"}
            and types
            and all(t == "integer" for t in types)
            else "number"
        )
    if op in {"concat", "trim", "toString", "toDateTime"}:
        return "string"
    if op == "coalesce":
        return next((t for t in types if t != "null"), "null")
    return "unknown"


def check_node(node, flow, nodes):
    for field in ("condition", "mapping", "body", "value", "headers"):
        if field in node.config:
            infer(node.config[field], flow, nodes)
    for value in node.config.get("parameters", {}).values():
        infer(value, flow, nodes)
    if node.type == "branch" and not compatible(
        infer(node.config.get("condition"), flow, nodes), "boolean"
    ):
        raise Fault("VALIDATION_ERROR", "분기 조건은 boolean이어야 합니다.")
    if node.type == "response.http":
        body = node.config.get("body")
        expected = schema_type(flow.outputSchema)
        if not compatible(infer(body, flow, nodes), expected):
            raise Fault("VALIDATION_ERROR", "응답 타입이 출력 계약과 다릅니다.")
        if isinstance(body, dict) and not {"ref", "op", "literal"} & set(body):
            if not set(flow.outputSchema.get("required", [])) <= set(body):
                raise Fault("VALIDATION_ERROR", "필수 응답 필드가 누락되었습니다.")
            for key, value in body.items():
                expected_field = schema_type(
                    flow.outputSchema.get("properties", {}).get(key, {})
                )
                if not compatible(infer(value, flow, nodes), expected_field):
                    raise Fault(
                        "VALIDATION_ERROR", "응답 필드 타입이 출력 계약과 다릅니다."
                    )
