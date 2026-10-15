import copy
import json
from decimal import Decimal

import pytest
from flowstudio.database import Executions, bind_sql, sql_policy
from flowstudio.drawio import from_xml
from flowstudio.expressions import Expressions, contract
from flowstudio.models import Fault, Flow
from flowstudio.validation import validate


def test_expression_types_precision_missing_and_limits():
    e = Expressions({"input": {"value": None}, "nodes": {}})
    assert e.evaluate({"op": "isNull", "args": [{"ref": "input.value"}]}) is True
    with pytest.raises(Fault):
        e.evaluate({"ref": "input.absent"})
    with pytest.raises(Fault):
        e.evaluate({"op": "add", "args": ["1", 2]})
    assert e.evaluate(
        {
            "op": "add",
            "args": [
                {"type": "decimal", "value": "0.1"},
                {"type": "decimal", "value": "0.2"},
            ],
        }
    ) == {"type": "decimal", "value": "0.3"}
    assert e.evaluate({"op": "toNumber", "args": ["9007199254740993"]}) == {
        "type": "integer",
        "value": "9007199254740993",
    }
    with pytest.raises(Fault):
        e.evaluate({"op": "toNumber", "args": ["1e999999999"]})
    with pytest.raises(Fault):
        e.evaluate({"op": "divide", "args": [1, 0]})


def test_sql_binding_keeps_literals_and_comments_out_of_parameters():
    sql = "SELECT ':ignored', '%s', id FROM users WHERE id=:id -- :also_ignored"
    query, values = bind_sql(sql, {"id": 1}, "mysql")
    assert "':ignored'" in query and "'%%s'" in query
    assert values == [Decimal(1)]
    assert ":also_ignored" in query
    assert bind_sql(
        "SELECT id FROM users WHERE id=:id OR parent=:id", {"id": 1}, "tibero"
    )[1] == [Decimal(1), Decimal(1)]
    with pytest.raises(Fault):
        bind_sql("SELECT :missing FROM dual", {}, "oracle")


@pytest.mark.parametrize(
    "sql,command",
    [
        ("SELECT 1; DELETE FROM users", False),
        ("DROP TABLE users", True),
        ("CALL proc()", True),
        ("SELECT * FROM users FOR UPDATE", False),
        ("SELECT * INTO copy FROM users", False),
    ],
)
def test_sql_forbidden_statements(sql, command):
    with pytest.raises(Fault):
        sql_policy(sql, command)


def test_graph_cycle_and_conditional_reference(process):
    value = copy.deepcopy(process["flow"])
    value["edges"].append({"from": "start", "port": "error", "to": "start"})
    assert any(
        "순환" in issue["message"] for issue in validate(Flow.model_validate(value))
    )
    value = copy.deepcopy(process["flow"])
    value["nodes"][-1]["config"]["body"] = {"ref": "nodes.absent.output"}
    assert any(
        i["code"] == "FLOW_INVALID_REFERENCE"
        for i in validate(Flow.model_validate(value))
    )


def test_multidatabase_transaction_is_not_distributed(process):
    value = copy.deepcopy(process["flow"])
    value["resources"]["databases"] = ["main", "crm"]
    value["nodes"] = [
        value["nodes"][0],
        {
            "id": "begin",
            "type": "transaction.begin",
            "name": "시작",
            "config": {"databaseRef": "main"},
        },
        {
            "id": "query",
            "type": "db.query",
            "name": "조회",
            "config": {
                "databaseRef": "crm",
                "sql": "SELECT id FROM users",
                "parameters": {},
            },
        },
        {"id": "commit", "type": "transaction.commit", "name": "커밋", "config": {}},
        value["nodes"][-1],
    ]
    value["edges"] = [
        {"from": a, "to": b, "port": "success"}
        for a, b in [
            ("start", "begin"),
            ("begin", "query"),
            ("query", "commit"),
            ("commit", "response"),
        ]
    ]
    assert any(
        "다른 DB" in issue["message"] for issue in validate(Flow.model_validate(value))
    )


def test_schema_remote_references_rejected():
    with pytest.raises(Fault):
        contract({"$ref": "https://example.com/schema"}, {})


def diagram(flow):
    import xml.etree.ElementTree as ET

    root = ET.Element("mxGraphModel")
    cells = ET.SubElement(root, "root")
    ET.SubElement(cells, "mxCell", id="0")
    ET.SubElement(cells, "mxCell", id="1", parent="0")
    for n in flow.nodes:
        obj = ET.SubElement(
            cells,
            "object",
            id=n.id,
            label=n.name,
            flowType=n.type,
            flowConfig=json.dumps(n.config),
        )
        cell = ET.SubElement(obj, "mxCell", vertex="1", parent="1")
        ET.SubElement(
            cell,
            "mxGeometry",
            x="80",
            y="120",
            width="180",
            height="76",
            attrib={"as": "geometry"},
        )
    for i, e in enumerate(flow.edges):
        ET.SubElement(
            cells,
            "mxCell",
            id=f"e{i}",
            edge="1",
            source=e.from_,
            target=e.to,
            value=e.port,
        )
    return ET.tostring(root, encoding="unicode")


def test_drawio_roundtrip_preserves_semantics_and_node_id(process):
    flow = Flow.model_validate(process["flow"])
    xml = diagram(flow)
    result = from_xml(xml, flow)
    assert result.nodes == flow.nodes and result.edges == flow.edges
    assert result.ui["positions"]["start"] == {"x": 80.0, "y": 120.0}
    assert result.ui["drawioXml"].startswith("<mxGraphModel")
    assert not validate(result)


def test_drawio_rejects_external_entities_and_unknown_shapes(process):
    flow = Flow.model_validate(process["flow"])
    with pytest.raises(Fault):
        from_xml(
            '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><mxGraphModel>&e;</mxGraphModel>',
            flow,
        )
    with pytest.raises(Fault):
        from_xml(
            '<mxGraphModel><root><mxCell id="unknown" vertex="1"/></root></mxGraphModel>',
            flow,
        )


def test_cancellation_is_request_scoped():
    executions = Executions()
    with executions.run("first"), executions.run("second"):
        assert executions.cancel("first")
        with pytest.raises(Fault):
            executions.check("first")
        executions.check("second")
    assert not executions.cancel("first")


def test_static_type_errors_are_reported_before_run(process):
    value = copy.deepcopy(process["flow"])
    value["nodes"][-1]["config"]["body"] = {
        "message": {"op": "add", "args": ["bad", 1]}
    }
    assert any("number" in i["message"] for i in validate(Flow.model_validate(value)))


def test_malformed_config_is_a_validation_issue_not_server_error(process):
    value = copy.deepcopy(process["flow"])
    value["nodes"][0]["config"]["path"] = 42
    assert validate(Flow.model_validate(value))
    value = copy.deepcopy(process["flow"])
    value["nodes"][-1]["config"]["body"] = {"op": {"invalid": "operator"}, "args": []}
    assert validate(Flow.model_validate(value))
