import type { Flow } from "./types";
import { nodeKinds } from "./types";
import { validationShield } from "./stencils";

const styles: Record<string, string> = {
  "trigger.http": "rounded=1;arcSize=50;fillColor=#d5e8d4;strokeColor=#82b366;",
  validate: `shape=stencil(${validationShield});fillColor=#d0ece9;strokeColor=#62b8b0;`,
  transform: "shape=parallelogram;fillColor=#e1d5e7;strokeColor=#9673a6;",
  branch: "rhombus;fillColor=#fff2cc;strokeColor=#d6b656;",
  "db.query":
    "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#dae8fc;strokeColor=#6c8ebf;",
  "db.command":
    "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#ffe6cc;strokeColor=#d79b00;",
  "http.call": "shape=hexagon;fillColor=#dae8fc;strokeColor=#6c8ebf;",
  "error.raise": "shape=octagon;fillColor=#f8cecc;strokeColor=#b85450;",
  "response.http": "rounded=1;arcSize=50;fillColor=#d5e8d4;strokeColor=#82b366;",
  "transaction.begin":
    "shape=partialRectangle;left=1;right=0;top=1;bottom=1;fillColor=#35343d;strokeColor=#b09dce;",
  "transaction.commit":
    "shape=partialRectangle;left=0;right=1;top=1;bottom=1;fillColor=#303b35;strokeColor=#87b799;",
  "transaction.rollback":
    "shape=partialRectangle;left=0;right=1;top=1;bottom=1;fillColor=#493238;strokeColor=#d18490;",
};
export function flowToXml(flow: Flow): string {
  const previous = flow.ui?.drawioXml
    ? new DOMParser().parseFromString(flow.ui.drawioXml, "text/xml")
    : null;
  const previousNodes = new Map<string, Element>(),
    previousEdges = new Map<string, Element>();
  if (previous && !previous.querySelector("parsererror")) {
    for (const c of Array.from(previous.querySelectorAll("mxCell"))) {
      if (c.getAttribute("vertex") === "1")
        previousNodes.set(c.parentElement?.getAttribute("id") ?? c.getAttribute("id") ?? "", c);
      if (c.getAttribute("edge") === "1")
        previousEdges.set(
          [
            c.getAttribute("source"),
            c.getAttribute("value") || "success",
            c.getAttribute("target"),
          ].join("|"),
          c,
        );
    }
  }
  const doc = document.implementation.createDocument("", "mxGraphModel");
  const model = doc.documentElement;
  for (const [k, v] of Object.entries({
    dx: "1000",
    dy: "600",
    grid: "1",
    gridSize: "10",
    guides: "1",
    tooltips: "1",
    connect: "1",
    arrows: "1",
    fold: "1",
    page: "0",
    background: "#ffffff",
  }))
    model.setAttribute(k, v);
  const root = doc.createElement("root");
  model.appendChild(root);
  const cell = (attributes: Record<string, string>) => {
    const e = doc.createElement("mxCell");
    Object.entries(attributes).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  };
  root.append(cell({ id: "0" }), cell({ id: "1", parent: "0" }));
  flow.nodes.forEach((node, index) => {
    const obj = doc.createElement("object");
    obj.setAttribute("id", node.id);
    const icon = nodeKinds.find((k) => k[0] === node.type)?.[2] ?? "◇";
    obj.setAttribute("label", icon + " " + node.name);
    obj.setAttribute("flowIcon", icon);
    obj.setAttribute("flowType", node.type);
    obj.setAttribute("flowConfig", JSON.stringify(node.config));
    const c = cell({
      vertex: "1",
      parent: "1",
      style:
        (styles[node.type] ?? "rounded=1;") +
        "whiteSpace=wrap;html=0;fontColor=#333333;fontSize=12;fontFamily=Arial;spacing=12;",
    });
    const prior = previousNodes.get(node.id);
    if (prior?.getAttribute("style")) c.setAttribute("style", prior.getAttribute("style")!);
    const g = doc.createElement("mxGeometry");
    const p = flow.ui?.positions?.[node.id] ?? { x: 80 + index * 240, y: 160 };
    Object.entries({
      x: String(p.x),
      y: String(p.y),
      width: node.type === "branch" ? "150" : "180",
      height: node.type === "branch" ? "110" : "76",
      as: "geometry",
    }).forEach(([k, v]) => g.setAttribute(k, v));
    const previousGeometry = prior?.querySelector("mxGeometry");
    c.appendChild(previousGeometry ? doc.importNode(previousGeometry, true) : g);
    obj.appendChild(c);
    root.appendChild(obj);
  });
  flow.edges.forEach((edge, index) => {
    let edgeId = "__flow_edge_" + index;
    while (flow.nodes.some((n) => n.id === edgeId)) edgeId += "_";
    const c = cell({
      id: edgeId,
      edge: "1",
      parent: "1",
      source: edge.from,
      target: edge.to,
      value: edge.port,
      style:
        "edgeStyle=orthogonalEdgeStyle;rounded=1;html=0;strokeColor=" +
        (edge.port === "error" ? "#c77a7a" : "#7f8c9b") +
        ";fontColor=#b9c0cb;fontSize=10;endArrow=blockThin;endFill=1;",
    });
    const g = doc.createElement("mxGeometry");
    g.setAttribute("relative", "1");
    g.setAttribute("as", "geometry");
    const prior = previousEdges.get([edge.from, edge.port, edge.to].join("|"));
    const previousGeometry = prior?.querySelector("mxGeometry");
    if (prior?.getAttribute("style")) c.setAttribute("style", prior.getAttribute("style")!);
    c.appendChild(previousGeometry ? doc.importNode(previousGeometry, true) : g);
    root.appendChild(c);
  });
  return new XMLSerializer().serializeToString(doc);
}
