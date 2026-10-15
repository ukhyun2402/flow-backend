from __future__ import annotations

import base64
import json
import math
import re
import zlib
from urllib.parse import unquote

from defusedxml import ElementTree as SafeET

from .models import Fault, Flow


def from_xml(xml: str, base: Flow) -> Flow:
    if len(xml.encode()) > 2_000_000:
        raise Fault("DRAWIO_INVALID", "다이어그램은 2MB 이하여야 합니다.")
    try:
        document = SafeET.fromstring(xml)
        if document.tag == "mxfile":
            diagrams = document.findall("diagram")
            if len(diagrams) != 1:
                raise Fault(
                    "DRAWIO_INVALID", "프로세스당 하나의 draw.io 페이지를 사용하세요."
                )
            document = diagrams[0].find("mxGraphModel")
            if document is None:
                raw = base64.b64decode(diagrams[0].text or "", validate=True)
                decoder = zlib.decompressobj(-15)
                content = decoder.decompress(raw, 2_000_001)
                if len(content) > 2_000_000 or decoder.unconsumed_tail:
                    raise ValueError()
                document = SafeET.fromstring(unquote(content.decode()))
        if document.tag != "mxGraphModel":
            raise ValueError()
        root = document.find("root")
        if root is None:
            raise ValueError()
        known = {n.id: n for n in base.nodes}
        nodes, edges, positions = [], [], {}
        for obj in root:
            cell = obj if obj.tag == "mxCell" else obj.find("mxCell")
            if cell is None:
                continue
            id_ = obj.get("id") or cell.get("id")
            if cell.get("vertex") == "1":
                old = known.get(id_)
                kind = obj.get("flowType") or (old.type if old else None)
                if not kind:
                    raise Fault(
                        "DRAWIO_UNKNOWN_NODE",
                        "새 업무 노드는 Flow 노드 메뉴에서 추가하세요. 일반 도형은 실행 노드로 해석하지 않습니다.",
                    )
                config = (
                    json.loads(obj.get("flowConfig"))
                    if obj.get("flowConfig")
                    else old.config
                    if old
                    else {}
                )
                label = (
                    obj.get("label") or cell.get("value") or (old.name if old else id_)
                )
                label = re.sub(r"<[^>]*>", "", label)
                icon = obj.get("flowIcon")
                if icon and label.startswith(icon + " "):
                    label = label[len(icon) + 1 :]
                nodes.append({"id": id_, "type": kind, "name": label, "config": config})
                g = cell.find("mxGeometry")
                if g is not None:
                    position = {k: float(g.get(k, "0")) for k in ("x", "y")}
                    if any(
                        not math.isfinite(v) or abs(v) > 1_000_000
                        for v in position.values()
                    ):
                        raise ValueError()
                    positions[id_] = position
            elif cell.get("edge") == "1":
                label = re.sub(r"<[^>]*>", "", cell.get("value", "")).strip()
                edges.append(
                    {
                        "from": cell.get("source", ""),
                        "to": cell.get("target", ""),
                        "port": label or obj.get("flowPort") or "success",
                    }
                )
        result = base.model_dump(by_alias=True)
        result.update(nodes=nodes, edges=edges)
        import xml.etree.ElementTree as ET

        result["ui"] = {
            **base.ui,
            "positions": positions,
            "drawioXml": ET.tostring(document, encoding="unicode"),
        }
        return Flow.model_validate(result)
    except Fault:
        raise
    except Exception:
        raise Fault(
            "DRAWIO_INVALID", "draw.io XML 구조 또는 노드 데이터를 확인하세요."
        ) from None
