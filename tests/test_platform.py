import io
import json
import zipfile

from fastapi.testclient import TestClient
from flowstudio.runtime import create_runtime
from flowstudio.app import create_app


def test_local_workspace_without_token(store, monkeypatch):
    for key in ("FLOW_ADMIN_TOKEN", "FLOW_EDITOR_TOKEN", "FLOW_RUNNER_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(
        create_app(store), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as local:
        assert local.get("/api/workspace").status_code == 200
        assert (
            local.get(
                "/api/workspace", headers={"Origin": "https://example.com"}
            ).status_code
            == 401
        )
        assert (
            local.get(
                "/api/workspace", headers={"Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 401
        )
    with TestClient(
        create_app(store), base_url="http://127.0.0.1", client=("192.0.2.1", 50000)
    ) as remote:
        assert remote.get("/api/workspace").status_code == 401


def test_auth_and_role_boundaries(client):
    assert (
        client.get("/api/workspace", headers={"Authorization": ""}).status_code == 401
    )
    assert (
        client.post(
            "/api/projects",
            json={
                "code": "NEW",
                "name": "new",
                "primaryDatabaseId": "main",
                "databaseIds": ["main"],
            },
            headers={"Authorization": "Bearer test-runner-token-at-least-24-chars"},
        ).status_code
        == 403
    )


def test_hierarchy_filters_and_shared_projects(client):
    main = client.get("/api/workspace?databaseId=main").json()
    crm = client.get("/api/workspace?databaseId=crm").json()
    core = client.get("/api/workspace?databaseId=tibero").json()
    assert [p["code"] for p in main["projects"]] == ["ERP"]
    assert {p["code"] for p in crm["projects"]} == {"ERP", "CRM"}
    assert [p["code"] for p in core["projects"]] == ["CORE"]
    assert len(main["projects"][0]["databaseIds"]) == 2
    assert main["projects"][0]["units"][0]["processes"][0]["method"] == "POST"


def test_create_project_unit_process_and_database(client):
    database = {
        "id": "reporting",
        "name": "Reporting",
        "vendor": "mysql",
        "port": 3306,
        "passwordSecretRef": "REPORTING_PASSWORD",
    }
    assert client.put("/api/databases/reporting", json=database).status_code == 200
    project = client.post(
        "/api/projects",
        json={
            "code": "REPORT",
            "name": "리포트",
            "primaryDatabaseId": "reporting",
            "databaseIds": ["reporting", "main"],
        },
    ).json()
    unit = client.post(
        f"/api/projects/{project['id']}/units", json={"code": "SALES", "name": "매출"}
    ).json()
    process = client.post(
        f"/api/units/{unit['id']}/processes",
        json={"code": "SALES-001", "name": "매출 확인"},
    ).json()
    assert process["project"]["databaseIds"] == ["main", "reporting"]
    assert process["flow"]["id"] == "SALES-001"
    assert (
        client.post(
            f"/api/units/{unit['id']}/processes",
            json={"code": "SALES-001", "name": "중복"},
        ).status_code
        == 409
    )


def test_draft_conflicts_and_immutable_versions(client, process):
    id_ = process["id"]
    draft = {"flow": process["flow"], "expectedVersion": process["draft_version"]}
    saved = client.put(f"/api/processes/{id_}/draft", json=draft)
    assert saved.status_code == 200
    assert client.put(f"/api/processes/{id_}/draft", json=draft).status_code == 409
    version = client.post(
        f"/api/processes/{id_}/versions",
        json={"expectedVersion": saved.json()["draft_version"]},
    )
    assert version.status_code == 200
    assert version.json()["latest_revision"] == 1
    old = client.get(f"/api/processes/{id_}/versions/1").json()
    assert old["id"] == process["process_id"]
    assert (
        client.post(
            f"/api/processes/{id_}/versions",
            json={"expectedVersion": saved.json()["draft_version"]},
        ).status_code
        == 409
    )


def test_preview_trace_does_not_store_request_body(client, process):
    result = client.post(
        f"/api/processes/{process['id']}/preview",
        json={"request": {"body": {"name": "private-test-value"}}},
    )
    assert result.status_code == 200
    value = result.json()
    assert value["status"] == 200
    assert value["body"]["message"] == "Hello, private-test-value"
    trace = client.get("/api/executions/" + value["executionId"]).json()
    assert len(trace) == 2
    assert "private-test-value" not in json.dumps(trace)
    assert client.get("/api/history").json()[0]["process_id"] == process["id"]


def test_cross_project_database_is_rejected(client, process):
    flow = process["flow"]
    flow["resources"]["databases"] = ["tibero"]
    response = client.put(
        f"/api/processes/{process['id']}/draft",
        json={"flow": flow, "expectedVersion": process["draft_version"]},
    )
    assert response.status_code == 400


def test_generation_is_deterministic_independent_and_has_no_management(
    client, process, tmp_path, monkeypatch
):
    url = f"/api/processes/{process['id']}/generate"
    first, second = (
        client.post(url, json=process["flow"]),
        client.post(url, json=process["flow"]),
    )
    assert first.status_code == 200
    assert first.content == second.content
    process["flow"]["ui"]["positions"]["start"]["x"] += 100
    assert client.post(url, json=process["flow"]).content == first.content
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        assert "flowstudio/engine.py" in archive.namelist()
        assert "flowstudio/app.py" not in archive.namelist()
        assert "flowstudio/storage.py" not in archive.namelist()
        assert all("legacy" not in name for name in archive.namelist())
        archive.extractall(tmp_path)
    monkeypatch.setenv(
        "FLOW_RUNTIME_TOKEN", "runtime-test-token-with-more-than-24-characters"
    )
    runtime = TestClient(create_runtime(tmp_path / "flows"))
    path = process["flow"]["nodes"][0]["config"]["path"]
    assert runtime.post(path, json={"name": "test"}).status_code == 401
    response = runtime.post(
        path,
        json={"name": "test"},
        headers={
            "Authorization": "Bearer runtime-test-token-with-more-than-24-characters"
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Hello, test"
    assert runtime.get("/api/workspace").status_code == 404
