import copy
from pathlib import Path

from fastapi.testclient import TestClient
from flowstudio.app import create_app
from conftest import TOKEN


def validate(client, process, flow):
    result = client.post(
        f"/api/validate?projectId={process['project_id']}&processId={process['id']}",
        json=flow,
    )
    assert result.status_code == 200
    assert result.json()["valid"]
    return result.json()["validationId"]


def test_requires_validation_and_rejects_modified_configuration(client, process):
    path = f"/api/processes/{process['id']}/apply"
    flow = process["flow"]
    assert (
        client.post(path, json={"flow": flow, "validationId": "missing"}).status_code
        == 409
    )
    receipt = validate(client, process, flow)
    changed = copy.deepcopy(flow)
    changed["name"] = "changed after validation"
    assert (
        client.post(path, json={"flow": changed, "validationId": receipt}).status_code
        == 409
    )


def test_applied_python_executes_snapshot_and_survives_restart(client, store, process):
    flow = copy.deepcopy(process["flow"])
    response = next(n for n in flow["nodes"] if n["type"] == "response.http")
    response["config"]["body"] = {"message": "applied version one"}
    receipt = validate(client, process, flow)
    url = f"/api/processes/{process['id']}"
    applied = client.post(url + "/apply", json={"flow": flow, "validationId": receipt})
    assert applied.status_code == 200, applied.text
    path = Path(applied.json()["sourcePath"])
    assert path.is_file() and "applied version one" in path.read_text(encoding="utf-8")
    assert client.post(url + "/execute", json={"input": {"name": "Alice"}}).json()[
        "body"
    ] == {"message": "applied version one"}
    response["config"]["body"] = {"message": "version two"}
    assert (
        client.post(
            url + "/apply", json={"flow": flow, "validationId": receipt}
        ).status_code
        == 409
    )
    assert (
        client.post(url + "/execute", json={"input": {"name": "Alice"}}).json()["body"][
            "message"
        ]
        == "applied version one"
    )
    receipt2 = validate(client, process, flow)
    updated = client.post(
        url + "/apply", json={"flow": flow, "validationId": receipt2}
    ).json()
    assert updated["buildHash"] != applied.json()["buildHash"]
    assert updated["changes"]["changedNodes"] == [response["id"]]
    assert path.is_file()
    with TestClient(
        create_app(store, tokens={"admin": TOKEN}),
        headers={"Authorization": "Bearer " + TOKEN},
    ) as restarted:
        assert (
            restarted.post(url + "/execute", json={"input": {"name": "Bob"}}).json()[
                "body"
            ]["message"]
            == "version two"
        )


def test_database_scope_change_requires_revalidation(client, store, process):
    receipt = validate(client, process, process["flow"])
    db = store.databases()[0].model_dump()
    db["host"] = "changed.example"
    assert client.put("/api/databases/" + db["id"], json=db).status_code == 200
    assert (
        client.post(
            f"/api/processes/{process['id']}/apply",
            json={"flow": process["flow"], "validationId": receipt},
        ).status_code
        == 409
    )


def test_unapplied_process_and_runner_cannot_apply(client, process):
    url = f"/api/processes/{process['id']}"
    assert client.post(url + "/execute", json={"input": {}}).status_code == 409
    receipt = validate(client, process, process["flow"])
    assert (
        client.post(
            url + "/apply",
            json={"flow": process["flow"], "validationId": receipt},
            headers={"Authorization": "Bearer test-runner-token-at-least-24-chars"},
        ).status_code
        == 403
    )
