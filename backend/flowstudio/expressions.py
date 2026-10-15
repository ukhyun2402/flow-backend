from __future__ import annotations

from datetime import UTC, datetime
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Any

from .models import Fault

SAFE_INT = 9007199254740991
MISSING = object()


def is_number(value: Any) -> bool:
    return (
        type(value) in (int, float, Decimal)
        or isinstance(value, dict)
        and value.get("type") in ("decimal", "integer")
        and isinstance(value.get("value"), str)
    )


def number(value: Any) -> Decimal:
    if not is_number(value):
        raise Fault("VALIDATION_ERROR", "숫자 타입이 필요합니다.")
    text = str(value["value"] if isinstance(value, dict) else value)
    if len(text) > 256:
        raise Fault("VALIDATION_ERROR", "숫자 정밀도 제한을 초과했습니다.")
    try:
        result = Decimal(text)
        if not result.is_finite() or abs(result.as_tuple().exponent) > 1000:
            raise ValueError()
        if (
            isinstance(value, dict)
            and value["type"] == "integer"
            and result != result.to_integral_value()
        ):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise Fault("VALIDATION_ERROR", "유효하지 않은 숫자입니다.") from None


def wire(value: Any) -> Any:
    if isinstance(value, Decimal):
        if (
            not value.is_finite()
            or len(value.as_tuple().digits) > 512
            or abs(value.as_tuple().exponent) > 1000
        ):
            raise Fault("VALIDATION_ERROR", "계산 결과의 정밀도 제한을 초과했습니다.")
        if value.as_tuple().exponent >= 0:
            return wire(int(value))
        return {"type": "decimal", "value": format(value, "f")}
    if type(value) is int and abs(value) > SAFE_INT:
        return {"type": "integer", "value": str(value)}
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Session timezone is fixed to UTC by the DB adapter where supported.
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def schema_safe(schema: Any, depth: int = 0) -> None:
    if depth > 64:
        raise Fault("VALIDATION_ERROR", "스키마 깊이 제한을 초과했습니다.")
    if isinstance(schema, dict):
        for key in ("$ref", "$dynamicRef", "$recursiveRef"):
            if key in schema and not str(schema[key]).startswith("#"):
                raise Fault("VALIDATION_ERROR", "스키마 외부 참조는 허용하지 않습니다.")
        for v in schema.values():
            schema_safe(v, depth + 1)
    elif isinstance(schema, list):
        for v in schema:
            schema_safe(v, depth + 1)


def contract(schema: dict, value: Any) -> None:
    from jsonschema import Draft202012Validator, SchemaError

    schema_safe(schema)
    try:
        Draft202012Validator.check_schema(schema)
        error = next(Draft202012Validator(schema).iter_errors(wire(value)), None)
        if error:
            path = ".".join(str(p) for p in error.absolute_path) or "$"
            raise Fault("VALIDATION_ERROR", f"데이터 계약에 맞지 않습니다: {path}")
    except SchemaError:
        raise Fault("VALIDATION_ERROR", "유효하지 않은 JSON Schema입니다.") from None


class Expressions:
    def __init__(self, context: dict):
        self.context, self.remaining = context, 10000

    def evaluate(self, expr: Any, depth: int = 0) -> Any:
        self.remaining -= 1
        if depth > 64 or self.remaining < 0:
            raise Fault("VALIDATION_ERROR", "표현식 실행 제한을 초과했습니다.")
        if isinstance(expr, list):
            return [self.evaluate(v, depth + 1) for v in expr]
        if not isinstance(expr, dict):
            return expr
        if "literal" in expr:
            return expr["literal"]
        if "ref" in expr:
            result = self.context
            for part in expr["ref"].split("."):
                if isinstance(result, dict):
                    result = result.get(part, MISSING)
                elif (
                    isinstance(result, list)
                    and part.isdigit()
                    and int(part) < len(result)
                ):
                    result = result[int(part)]
                else:
                    result = MISSING
                if result is MISSING:
                    raise Fault("VALIDATION_ERROR", "현재 경로에 없는 출력 참조입니다.")
            return result
        if "op" not in expr:
            return {k: self.evaluate(v, depth + 1) for k, v in expr.items()}
        op = expr["op"]
        args = [self.evaluate(v, depth + 1) for v in expr.get("args", [])]
        try:
            if op in ("eq", "ne"):
                same = (
                    number(args[0]) == number(args[1])
                    if all(is_number(v) for v in args)
                    else type(args[0]) is type(args[1]) and args[0] == args[1]
                )
                return same if op == "eq" else not same
            if op in ("gt", "gte", "lt", "lte"):
                a, b = map(number, args)
                return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
            if op in ("and", "or", "not"):
                if any(type(v) is not bool for v in args):
                    raise Fault(
                        "VALIDATION_ERROR", "논리 연산에는 boolean이 필요합니다."
                    )
                return (
                    not args[0]
                    if op == "not"
                    else all(args)
                    if op == "and"
                    else any(args)
                )
            if op in ("isNull", "notNull"):
                return (args[0] is None) == (op == "isNull")
            if op == "coalesce":
                return next((v for v in args if v is not None), None)
            if op in ("add", "subtract", "multiply", "divide"):
                a, b = map(number, args)
                with localcontext(Context(prec=512 if op != "divide" else 34)):
                    result = (
                        a + b
                        if op == "add"
                        else a - b
                        if op == "subtract"
                        else a * b
                        if op == "multiply"
                        else a / b
                    )
                return wire(result)
            if op in ("concat", "trim", "contains", "toNumber", "toDateTime"):
                if any(not isinstance(v, str) for v in args):
                    raise Fault("VALIDATION_ERROR", "문자열 타입이 필요합니다.")
                if op == "concat":
                    return "".join(args)
                if op == "trim":
                    return args[0].strip("".join(chr(i) for i in range(33)))
                if op == "contains":
                    return args[1] in args[0]
                if op == "toNumber":
                    return wire(number({"type": "decimal", "value": args[0]}))
                parsed = datetime.fromisoformat(args[0].replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
                return wire(parsed)
            if op == "toString":
                if (
                    args[0] is None
                    or isinstance(args[0], (dict, list))
                    and not is_number(args[0])
                ):
                    raise ValueError()
                return str(
                    args[0]["value"]
                    if isinstance(args[0], dict)
                    else str(args[0]).lower()
                    if type(args[0]) is bool
                    else args[0]
                )
        except (ValueError, IndexError, TypeError, ArithmeticError):
            raise Fault(
                "VALIDATION_ERROR", "표현식의 인자나 계산 결과가 유효하지 않습니다."
            ) from None
        raise Fault("VALIDATION_ERROR", f"지원하지 않는 연산자: {op}")
