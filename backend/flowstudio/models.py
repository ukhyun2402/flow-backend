from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Node(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    type: str
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any]


class Edge(StrictModel):
    from_: str = Field(alias="from")
    port: Literal["success", "error", "true", "false"]
    to: str


class Flow(StrictModel):
    specVersion: Literal["1.0"] = "1.0"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any]
    resources: dict[str, list[str]]
    nodes: list[Node] = Field(min_length=1, max_length=500)
    edges: list[Edge] = Field(max_length=1500)
    settings: dict[str, Any]
    ui: dict[str, Any] = Field(default_factory=dict)


class Database(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    vendor: Literal["mysql", "oracle", "tibero"]
    host: str = Field(default="", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    database: str = Field(default="", max_length=200)
    username: str = Field(default="", max_length=200)
    passwordSecretRef: str = Field(default="", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$")
    environment: Literal["development", "test", "production"] = "development"
    readonly: bool = True
    rollbackSafetyVerified: bool = False
    tls: bool = True
    dsn: str = Field(default="", max_length=200)
    schemaName: str = Field(default="", max_length=200)

    def public(self) -> dict:
        return self.model_dump() | {
            "configured": bool(self.host or self.dsn),
            "secretAvailable": bool(
                __import__("os").environ.get(self.passwordSecretRef)
            ),
        }


class Fault(Exception):
    def __init__(
        self, code: str, message: str, status: int = 400, category: str | None = None
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.category = category or code

    def response(self) -> dict:
        return {"code": self.code, "category": self.category, "message": self.message}
