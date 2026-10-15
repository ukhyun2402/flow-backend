import pytest
from fastapi.testclient import TestClient
from flowstudio.app import create_app
from flowstudio.storage import Store

TOKEN = "test-only-admin-token-at-least-24-chars"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "workspace.sqlite3")


@pytest.fixture
def client(store):
    with TestClient(
        create_app(
            store,
            tokens={
                "admin": TOKEN,
                "editor": "test-editor-token-at-least-24-chars",
                "runner": "test-runner-token-at-least-24-chars",
            },
        ),
        raise_server_exceptions=False,
    ) as client:
        client.headers["Authorization"] = "Bearer " + TOKEN
        yield client


@pytest.fixture
def process(store):
    for project in store.tree("main"):
        for unit in project["units"]:
            for process in unit["processes"]:
                if process["process_id"] == "SYS-001":
                    return store.process(process["id"])
