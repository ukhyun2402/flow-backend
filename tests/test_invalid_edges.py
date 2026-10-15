import copy

import pytest
from flowstudio.models import Flow
from flowstudio.validation import validate


@pytest.mark.parametrize("port", ["true", "false"])
def test_first_unsupported_edge_returns_issue_instead_of_crashing(process, port):
    value = copy.deepcopy(process["flow"])
    value["edges"][0]["port"] = port
    issues = validate(Flow.model_validate(value))
    assert any(
        issue["field"] == "edges" and port in issue["message"] for issue in issues
    )


def test_terminal_edge_and_duplicate_edge_are_validation_issues(process):
    value = copy.deepcopy(process["flow"])
    value["edges"].append({"from": "response", "to": "start", "port": "success"})
    assert any(
        issue["nodeId"] == "response" and issue["field"] == "edges"
        for issue in validate(Flow.model_validate(value))
    )
    value["edges"][-1] = dict(value["edges"][0])
    assert any(
        "중복" in issue["message"] for issue in validate(Flow.model_validate(value))
    )


def test_drawio_conversion_and_validation_report_bad_port_without_500(client, process):
    flow = process["flow"]
    xml = """<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="start" vertex="1" value="요청" parent="1"><mxGeometry x="0" y="0" as="geometry"/></mxCell>
        <mxCell id="response" vertex="1" value="응답" parent="1"><mxGeometry x="200" y="0" as="geometry"/></mxCell>
        <mxCell id="edge" edge="1" parent="1" source="start" target="response" value="false"/>
        </root></mxGraphModel>"""
    result = client.post("/api/drawio/convert", json={"flow": flow, "xml": xml})
    assert result.status_code == 200, result.text
    converted = result.json()
    assert converted["flow"]["edges"][0]["port"] == "false"
    assert any("false" in issue["message"] for issue in converted["issues"])
    checked = client.post(
        f"/api/validate?projectId={process['project_id']}&processId={process['id']}",
        json=converted["flow"],
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["valid"] is False
    assert checked.json()["validationId"] is None
    converted["flow"]["edges"][0]["port"] = "success"
    repaired = client.post(
        f"/api/validate?projectId={process['project_id']}&processId={process['id']}",
        json=converted["flow"],
    )
    assert repaired.status_code == 200
    assert repaired.json()["valid"] is True
    assert repaired.json()["validationId"]
