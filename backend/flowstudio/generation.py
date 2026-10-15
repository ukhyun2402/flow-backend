from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from .models import Fault, Flow
from .validation import require_valid

RUNTIME_FILES = (
    "__init__.py",
    "models.py",
    "expressions.py",
    "validation.py",
    "typecheck.py",
    "database.py",
    "engine.py",
    "runtime.py",
)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def openapi(flows: list[tuple[str, Flow]]) -> dict:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Generated Flow API", "version": "0.2.0"},
        "paths": {},
        "components": {
            "schemas": {},
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        },
    }
    seen = set()

    def rebase(value, prefix):
        if isinstance(value, dict):
            return {
                k: prefix + v[1:]
                if k in ("$ref", "$dynamicRef")
                and isinstance(v, str)
                and v.startswith("#")
                else rebase(v, prefix)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [rebase(v, prefix) for v in value]
        return value

    for process_uuid, flow in flows:
        start = next(n for n in flow.nodes if n.type == "trigger.http")
        path, method = start.config["path"], start.config["method"].lower()
        route = method + " " + re.sub(r"\{[^{}]+\}", "{}", path)
        if route in seen:
            raise Fault("ROUTE_CONFLICT", "프로젝트 내 API 경로·메서드가 충돌합니다.")
        seen.add(route)
        name = re.sub(r"[^A-Za-z0-9_]", "_", process_uuid)
        input_key, output_key = name + "Input", name + "Output"
        document["components"]["schemas"][input_key] = rebase(
            flow.inputSchema, "#/components/schemas/" + input_key
        )
        document["components"]["schemas"][output_key] = rebase(
            flow.outputSchema, "#/components/schemas/" + output_key
        )
        parameters, body_props, required, names = [], {}, [], set()
        for field, mapping in start.config.get("input", {}).items():
            source, external = mapping["source"].split(".", 1)
            schema = rebase(
                flow.inputSchema.get("properties", {}).get(field, {"type": "string"}),
                "#/components/schemas/" + input_key,
            )
            if source in ("path", "query", "headers"):
                parameters.append(
                    {
                        "name": external,
                        "in": "header" if source == "headers" else source,
                        "required": source == "path"
                        or field in flow.inputSchema.get("required", []),
                        "schema": schema,
                    }
                )
                if source == "path":
                    names.add(external)
            elif source == "body":
                target, parts = body_props, external.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(
                        part, {"type": "object", "properties": {}}
                    )["properties"]
                target[parts[-1]] = schema
                if len(parts) == 1 and field in flow.inputSchema.get("required", []):
                    required.append(parts[0])
        for variable in re.findall(r"\{([^{}]+)\}", path):
            if variable not in names:
                parameters.append(
                    {
                        "name": variable,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
        responses = {
            str(n.config["status"]): {
                "description": "Flow response",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/" + output_key}
                    }
                },
            }
            for n in flow.nodes
            if n.type == "response.http"
        }
        responses["default"] = {"description": "Sanitized execution error"}
        operation = {
            "operationId": process_uuid,
            "summary": flow.name,
            "parameters": parameters,
            "responses": responses,
        }
        if body_props:
            operation["requestBody"] = {
                "required": bool(required),
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": body_props,
                            "required": required,
                        }
                    }
                },
            }
        if flow.settings["authentication"] == "bearer":
            operation["security"] = [{"bearer": []}]
        document["paths"].setdefault(path, {})[method] = operation
    return document


def generate(processes: list[dict], databases: list, hierarchy: dict) -> bytes:
    if not processes:
        raise Fault("VALIDATION_ERROR", "생성할 프로세스가 없습니다.")
    files = {}
    flows = []
    for process in processes:
        flow = Flow.model_validate(process["flow"])
        require_valid(flow, set(process["project"]["databaseIds"]))
        value = flow.model_dump(by_alias=True)
        value.pop("ui", None)
        files["flows/" + process["id"] + ".json"] = canonical(value)
        files["schemas/" + process["id"] + "-input.json"] = canonical(flow.inputSchema)
        files["schemas/" + process["id"] + "-output.json"] = canonical(
            flow.outputSchema
        )
        flows.append((process["id"], flow))
    files["openapi.json"] = canonical(openapi(flows))
    root = Path(__file__).parent
    for name in RUNTIME_FILES:
        files["flowstudio/" + name] = (root / name).read_bytes()
    files["app.py"] = (
        b"from flowstudio.runtime import create_runtime\napp = create_runtime()\n"
    )
    # Exact dependency lock is included when available; no platform management source is exported.
    lock = root.parents[1] / "requirements.lock"
    dependencies = (
        lock.read_text(encoding="utf-8")
        if lock.exists()
        else "fastapi>=0.115,<1\nuvicorn>=0.32,<1\npydantic>=2.10,<3\njsonschema>=4.23,<5\nsqlglot>=26,<40\nhttpx>=0.28,<1\npymysql>=1.1,<2\noracledb>=3,<5\npyodbc>=5,<6\n"
    )
    files["requirements.txt"] = dependencies.encode()
    files["Dockerfile"] = (
        b'FROM python:3.12-slim\nWORKDIR /app\nRUN apt-get update && apt-get install -y --no-install-recommends unixodbc && rm -rf /var/lib/apt/lists/*\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nUSER 10001\nEXPOSE 8080\nCMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]\n'
    )
    used = set().union(*(set(f.resources.get("databases", [])) for _, f in flows))
    sample = []
    for db in databases:
        if db.id in used:
            sample.append(
                {
                    "id": db.id,
                    "name": db.name,
                    "vendor": db.vendor,
                    "host": "REPLACE_HOST",
                    "port": db.port,
                    "database": "REPLACE_DATABASE",
                    "username": "REPLACE_USER",
                    "passwordSecretRef": db.id.upper() + "_DB_PASSWORD",
                    "readonly": db.readonly,
                    "tls": db.tls,
                    "dsn": "REPLACE_ODBC_DSN" if db.vendor == "tibero" else "",
                }
            )
    files["config/databases.example.json"] = canonical(sample)
    files[".env.example"] = (
        b"FLOW_RUNTIME_TOKEN=replace_with_at_least_24_random_characters\nFLOW_DATABASE_CONFIG=config/databases.json\n"
    )
    files["extensions/.gitkeep"] = b""
    files["tests/README.md"] = (
        b"Validate API fixtures against schemas/ and openapi.json. Run DB integration checks in the target environment; do not invoke production write flows as smoke tests.\n"
    )
    files["README.md"] = (
        b"# Generated Python server\n\nPython 3.12+: `pip install -r requirements.txt`, then `uvicorn app:app --port 8080`.\nSet FLOW_RUNTIME_TOKEN for bearer APIs. Copy config/databases.example.json to an external config, set FLOW_DATABASE_CONFIG and provide passwordSecretRef environment variables. No management APIs are included.\n\nTibero requires a vendor ODBC driver and DSN installed in the target OS. Verify redistribution permissions separately. Dockerfile does not bundle this driver. Keep user code in extensions/ and export into a fresh directory.\n"
    )
    manifest = {
        "generatorVersion": "0.2.0",
        "runtimeVersion": "0.2.0",
        "hierarchy": hierarchy,
        "flows": [
            {"processUuid": id_, "flowId": f.id, "revision": f.revision}
            for id_, f in flows
        ],
        "files": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
        },
    }
    files["generation-manifest.json"] = canonical(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()
