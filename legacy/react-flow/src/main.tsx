import React, { useState, useCallback, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./style.css";

const Editor = React.lazy(() => import("./SqlEditor"));
type Json = Record<string, any>;
type FlowNode = { id: string; type: string; name: string; config: Json };
type Flow = {
  specVersion: string;
  id: string;
  revision: number;
  name: string;
  inputSchema: Json;
  outputSchema: Json;
  resources: Json;
  nodes: FlowNode[];
  edges: { from: string; port: string; to: string }[];
  settings: Json;
  ui: Json;
};
type Canvas = Node<{
  label: string;
  kind: string;
  failed?: boolean;
  executed?: boolean;
}>;
const palette: [string, string, string][] = [
  ["trigger.http", "HTTP 진입", "↪"],
  ["validate", "입력 검증", "✓"],
  ["transform", "데이터 변환", "ƒ"],
  ["branch", "조건 분기", "◇"],
  ["db.query", "SQL 조회", "▤"],
  ["db.command", "SQL 변경", "✎"],
  ["http.call", "외부 API", "⬡"],
  ["transaction.begin", "트랜잭션 시작", "["],
  ["transaction.commit", "커밋", "]✓"],
  ["transaction.rollback", "롤백", "]↶"],
  ["error.raise", "업무 오류", "!"],
  ["response.http", "HTTP 응답", "↗"],
];
const defaults: Record<string, Json> = {
  "trigger.http": { method: "POST", path: "/endpoint", input: {} },
  validate: { schema: { type: "object" } },
  transform: { mapping: {} },
  branch: { condition: { op: "eq", args: [1, 1] } },
  "db.query": {
    databaseRef: "main",
    sql: "SELECT id FROM users WHERE id = :id",
    parameters: { id: { ref: "input.id" } },
    resultMode: "many",
  },
  "db.command": {
    databaseRef: "main",
    sql: "UPDATE users SET name = :name WHERE id = :id",
    parameters: { id: { ref: "input.id" }, name: { ref: "input.name" } },
  },
  "http.call": { serviceRef: "main", method: "GET", path: "/status" },
  "transaction.begin": { databaseRef: "main" },
  "transaction.commit": {},
  "transaction.rollback": {},
  "error.raise": { code: "BUSINESS_ERROR", status: 400, message: "업무 오류" },
  "response.http": { status: 200, body: { message: "ok" } },
};
const initial: Flow = {
  specVersion: "1.0",
  id: "hello",
  revision: 1,
  name: "인사 API",
  inputSchema: {
    type: "object",
    properties: { name: { type: "string" } },
    required: ["name"],
    additionalProperties: false,
  },
  outputSchema: {
    type: "object",
    properties: { message: { type: "string" } },
    required: ["message"],
  },
  resources: { databases: [], services: [] },
  nodes: [
    {
      id: "start",
      type: "trigger.http",
      name: "요청 수신",
      config: {
        method: "POST",
        path: "/hello",
        input: { name: { source: "body.name" } },
      },
    },
    {
      id: "greeting",
      type: "transform",
      name: "인사 만들기",
      config: {
        mapping: {
          message: {
            op: "concat",
            args: ["안녕하세요, ", { ref: "input.name" }, "님!"],
          },
        },
      },
    },
    {
      id: "response",
      type: "response.http",
      name: "응답 반환",
      config: { status: 200, body: { ref: "nodes.greeting.output" } },
    },
  ],
  edges: [
    { from: "start", port: "success", to: "greeting" },
    { from: "greeting", port: "success", to: "response" },
  ],
  settings: { timeoutMs: 10000, authentication: "bearer" },
  ui: {
    positions: {
      start: { x: 50, y: 150 },
      greeting: { x: 330, y: 150 },
      response: { x: 610, y: 150 },
    },
  },
};
const pretty = (v: unknown) => JSON.stringify(v, null, 2);
function ShapeNode({ data }: { data: Canvas["data"] }) {
  const item = palette.find((p) => p[0] === data.kind)!;
  const ports =
    data.kind === "response.http"
      ? []
      : data.kind === "branch"
        ? ["true", "false", "error"]
        : data.kind === "error.raise"
          ? ["error"]
          : ["success", "error"];
  return (
    <div
      className={`flow-node ${data.kind.replaceAll(".", "-")} ${data.failed ? "failed" : data.executed ? "executed" : ""}`}
    >
      <svg
        className="node-shape"
        viewBox="0 0 190 90"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {data.kind === "branch" ? (
          <polygon points="95,2 188,45 95,88 2,45" />
        ) : data.kind === "validate" ? (
          <polygon points="3,2 187,2 187,55 95,88 3,55" />
        ) : data.kind === "transform" ? (
          <polygon points="20,2 188,2 170,88 2,88" />
        ) : data.kind === "http.call" ? (
          <polygon points="25,2 165,2 188,45 165,88 25,88 2,45" />
        ) : data.kind === "error.raise" ? (
          <polygon points="22,2 168,2 188,22 188,68 168,88 22,88 2,68 2,22" />
        ) : data.kind.startsWith("db.") ? (
          <>
            <path d="M2 14 C2 -2 188 -2 188 14 L188 76 C188 92 2 92 2 76 Z" />
            <path d="M2 14 C2 30 188 30 188 14" fill="none" />
          </>
        ) : data.kind === "transaction.begin" ? (
          <path d="M188 2 H3 V88 H188" fill="none" />
        ) : data.kind.startsWith("transaction.") ? (
          <path d="M2 2 H187 V88 H2" fill="none" />
        ) : (
          <rect x="2" y="2" width="186" height="86" rx="42" />
        )}
      </svg>
      {data.kind !== "trigger.http" && <Handle type="target" position={Position.Left} />}
      <span className="node-icon">{item?.[2]}</span>
      <div>
        <small>{item?.[1]}</small>
        <strong>{data.label}</strong>
      </div>
      {ports.map((port, i) => (
        <React.Fragment key={port}>
          <span className="port-label" style={{ top: `${((i + 1) * 100) / (ports.length + 1)}%` }}>
            {port}
          </span>
          <Handle
            id={port}
            type="source"
            position={Position.Right}
            style={{
              top: `${((i + 1) * 100) / (ports.length + 1)}%`,
              background: port === "error" ? "#df7272" : "#5d82f5",
            }}
          />
        </React.Fragment>
      ))}
    </div>
  );
}
const nodeTypes = { flow: ShapeNode };
function normalizeFlow(value: Flow): Flow {
  if (
    !value ||
    typeof value.id !== "string" ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges) ||
    !value.settings ||
    !value.inputSchema ||
    !value.outputSchema ||
    !value.resources ||
    value.nodes.some(
      (n) =>
        !n ||
        !palette.some((p) => p[0] === n.type) ||
        typeof n.id !== "string" ||
        !n.config ||
        typeof n.config !== "object",
    ) ||
    value.edges.some((e) => !e || typeof e.from !== "string" || typeof e.to !== "string")
  )
    throw new Error("Flow 명세 구조를 확인하세요.");
  return { ...value, ui: value.ui ?? {} };
}
function App() {
  const { fitView } = useReactFlow();
  const [search, setSearch] = useState("");
  const [paletteOpen, setPaletteOpen] = useState(false),
    [propertiesOpen, setPropertiesOpen] = useState(false);
  const [flow, setFlow] = useState<Flow>(initial),
    [selected, setSelected] = useState<string>("greeting"),
    [configText, setConfigText] = useState(pretty(initial.nodes[1].config));
  const [token, setToken] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(
      "예제 Flow가 열려 있습니다. 토큰을 입력한 뒤 검증·실행하세요.",
    );
  const [issues, setIssues] = useState<Json[]>([]),
    [trace, setTrace] = useState<Json[]>([]),
    [result, setResult] = useState<unknown>(null),
    [input, setInput] = useState('{"name":"개발자"}');
  const [tab, setTab] = useState("실행"),
    [library, setLibrary] = useState<Json[]>([]),
    [jsonText, setJsonText] = useState(""),
    [sqlResult, setSqlResult] = useState<Json | null>(null);
  const [sqlParams, setSqlParams] = useState("{}"),
    [metadata, setMetadata] = useState<Json | null>(null),
    [executionId, setExecutionId] = useState("");
  const [past, setPast] = useState<Flow[]>([]),
    [future, setFuture] = useState<Flow[]>([]);
  const file = useRef<HTMLInputElement>(null);
  const node = flow.nodes.find((n) => n.id === selected);
  function change(next: Flow) {
    next = normalizeFlow(next);
    setPast((p) => [...p.slice(-49), flow]);
    setFuture([]);
    setFlow(next);
  }
  function focusNode(id: string) {
    const n = flow.nodes.find((n) => n.id === id);
    if (!n) return;
    setSelected(id);
    setConfigText(pretty(n.config));
    setPropertiesOpen(true);
    setPaletteOpen(false);
    void fitView({ nodes: [{ id }], duration: 200, minZoom: 0.8, maxZoom: 1 });
  }
  function restore(next: Flow) {
    setFlow(next);
    setSelected("");
    setConfigText("");
    setTrace([]);
    setIssues([]);
  }
  function undo() {
    if (!past.length) return;
    setFuture((p) => [flow, ...p]);
    restore(past[past.length - 1]);
    setPast((p) => p.slice(0, -1));
  }
  function redo() {
    if (!future.length) return;
    setPast((p) => [...p, flow]);
    restore(future[0]);
    setFuture((p) => p.slice(1));
  }
  const nodes: Canvas[] = flow.nodes.map((n) => ({
    id: n.id,
    type: "flow",
    position: flow.ui.positions?.[n.id] ?? { x: 50, y: 50 },
    selected: n.id === selected,
    data: {
      label: n.name,
      kind: n.type,
      failed: trace.some((t) => t.nodeId === n.id && t.status === "ERROR"),
      executed: trace.some((t) => t.nodeId === n.id && t.status === "SUCCESS"),
    },
  }));
  const edges: Edge[] = flow.edges.map((e, i) => ({
    id: `${e.from}:${e.port}:${e.to}`,
    source: e.from,
    target: e.to,
    sourceHandle: e.port,
    label: e.port,
    style: { stroke: e.port === "error" ? "#cf7272" : "#62718c" },
    animated: trace.some((t) => t.nodeId === e.from) && trace.some((t) => t.nodeId === e.to),
  }));
  const onNodesChange = useCallback(
    (changes: NodeChange<Canvas>[]) => {
      const moved = applyNodeChanges(changes, nodes);
      if (changes.some((c) => c.type === "remove")) {
        const ids = new Set(moved.map((n) => n.id));
        change({
          ...flow,
          nodes: flow.nodes.filter((n) => ids.has(n.id)),
          edges: flow.edges.filter((e) => ids.has(e.from) && ids.has(e.to)),
        });
      } else if (changes.some((c) => c.type === "position"))
        setFlow((f) => ({
          ...f,
          ui: {
            ...f.ui,
            positions: Object.fromEntries(moved.map((n) => [n.id, n.position])),
          },
        }));
    },
    [nodes, flow],
  );
  function onEdgesChange(changes: EdgeChange[]) {
    const remaining = applyEdgeChanges(changes, edges);
    if (changes.some((c) => c.type === "remove"))
      change({
        ...flow,
        edges: flow.edges.filter((e) =>
          remaining.some(
            (r) => r.source === e.from && r.target === e.to && r.sourceHandle === e.port,
          ),
        ),
      });
  }
  function connect(c: Connection) {
    const next = addEdge(c, edges);
    change({
      ...flow,
      edges: next.map((e) => ({
        from: e.source,
        port: e.sourceHandle ?? "success",
        to: e.target,
      })),
    });
  }
  async function api(path: string, body?: unknown) {
    const r = await fetch("/api" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({ message: `HTTP ${r.status}` }));
      throw new Error(data.message ?? data.code);
    }
    return r;
  }
  async function action(task: () => Promise<void>) {
    setBusy(true);
    try {
      await task();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function validate() {
    const r = await (await api("/validate", flow)).json();
    setIssues(r.issues);
    setTab("검증");
    setMessage(r.valid ? "검증 통과" : `${r.issues.length}개 오류를 수정하세요.`);
    return r.valid;
  }
  async function preview() {
    if (await validate()) {
      const id = crypto.randomUUID();
      setExecutionId(id);
      try {
        const r = await (
          await api("/preview", {
            flow,
            input: JSON.parse(input),
            executionId: id,
          })
        ).json();
        setResult(r.body);
        setTrace(r.trace);
        setTab("실행");
        setMessage(`실행 종료 · HTTP ${r.status}`);
      } finally {
        setExecutionId("");
      }
    }
  }
  async function runSql() {
    const cfg = JSON.parse(configText),
      id = crypto.randomUUID();
    setExecutionId(id);
    try {
      setSqlResult(
        await (
          await api("/sql/preview", {
            databaseRef: cfg.databaseRef,
            sql: cfg.sql,
            parameters: JSON.parse(sqlParams),
            command: node?.type === "db.command",
            executionId: id,
          })
        ).json(),
      );
    } finally {
      setExecutionId("");
    }
  }
  function applyConfig() {
    try {
      const config = JSON.parse(configText);
      change({
        ...flow,
        nodes: flow.nodes.map((n) => (n.id === selected ? { ...n, config } : n)),
      });
      setMessage("노드 설정을 적용했습니다.");
    } catch {
      setMessage("설정 JSON 형식을 확인하세요.");
    }
  }
  function add(type: string) {
    const id = "n_" + crypto.randomUUID().slice(0, 8);
    change({
      ...flow,
      nodes: [
        ...flow.nodes,
        {
          id,
          type,
          name: palette.find((p) => p[0] === type)![1],
          config: structuredClone(defaults[type]),
        },
      ],
      ui: {
        ...flow.ui,
        positions: {
          ...flow.ui.positions,
          [id]: { x: 100 + Math.random() * 350, y: 100 + Math.random() * 250 },
        },
      },
    });
    setSelected(id);
    setConfigText(pretty(defaults[type]));
    setPaletteOpen(false);
    setPropertiesOpen(true);
  }
  function download(data: Blob, name: string) {
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="app">
      <header>
        <div className="brand">
          <b>F</b>
          <div>
            <strong>Flow Studio</strong>
            <small>JAVA BACKEND BUILDER · 0.1</small>
          </div>
        </div>
        <span className="badge">LOCAL WORKSPACE</span>
        <input
          className="token"
          type="password"
          aria-label="관리 API 토큰"
          placeholder="관리 API Bearer 토큰"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button
          onClick={() =>
            action(async () => {
              setLibrary(await (await api("/flows")).json());
              setTab("목록");
            })
          }
        >
          프로젝트 열기
        </button>
      </header>
      <div className="toolbar">
        <button
          className="panel-toggle"
          onClick={() => {
            setPaletteOpen(!paletteOpen);
            setPropertiesOpen(false);
          }}
        >
          ＋ 노드
        </button>
        <button
          className="panel-toggle"
          onClick={() => {
            setPropertiesOpen(!propertiesOpen);
            setPaletteOpen(false);
          }}
        >
          속성
        </button>
        <input
          className="title-input"
          aria-label="Flow 이름"
          value={flow.name}
          onChange={(e) => setFlow({ ...flow, name: e.target.value })}
        />
        <span className="revision">
          {flow.id} · rev {flow.revision}
        </span>
        <div className="spacer" />
        <button disabled={!past.length} onClick={undo}>
          ↶ 실행 취소
        </button>
        <button disabled={!future.length} onClick={redo}>
          ↷
        </button>
        <button
          onClick={() => {
            setJsonText(pretty(flow));
            setTab("명세");
          }}
        >
          JSON
        </button>
        <button onClick={() => file.current?.click()}>가져오기</button>
        <button
          disabled={busy}
          onClick={() =>
            action(async () => {
              await api("/flows", flow);
              setMessage("버전을 저장했습니다.");
            })
          }
        >
          저장
        </button>
        <button
          disabled={busy}
          onClick={() =>
            action(async () => {
              await validate();
            })
          }
        >
          검증
        </button>
        <button className="primary" disabled={busy} onClick={() => action(preview)}>
          ▶ 미리보기
        </button>
        <button
          className="dark"
          disabled={busy}
          onClick={() =>
            action(async () => {
              const r = await api("/generate", flow);
              download(await r.blob(), "generated-server.zip");
              setMessage("독립 Java 서버 프로젝트를 생성했습니다.");
            })
          }
        >
          서버 생성 ↓
        </button>
      </div>
      <main>
        <aside className={`palette ${paletteOpen ? "open" : ""}`}>
          <h3>노드 라이브러리</h3>
          <p>노드를 추가하고 포트를 연결하세요.</p>
          <input
            aria-label="노드 검색"
            placeholder="노드 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {palette
            .filter((p) => p[0].includes(search) || p[1].includes(search))
            .map(([type, label, icon]) => (
              <button key={type} onClick={() => add(type)}>
                <span>{icon}</span>
                {label}
                <b>+</b>
              </button>
            ))}
          <div className="aside-note">
            실행 순서는 연결선으로 결정됩니다. SQL은 선택 DB의 방언을 사용합니다.
          </div>
        </aside>
        <section className="workspace">
          <div className="canvas">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={connect}
              onNodeClick={(_, n) => {
                setPropertiesOpen(true);
                setPaletteOpen(false);
                setSelected(n.id);
                setConfigText(pretty(flow.nodes.find((x) => x.id === n.id)!.config));
              }}
              onNodeDragStart={() => {
                setPast((p) => [...p.slice(-49), structuredClone(flow)]);
                setFuture([]);
              }}
              fitView
              minZoom={0.2}
              maxZoom={2}
            >
              <Background gap={22} color="#d9dfeb" />
              <Controls />
              <MiniMap nodeColor="#8298ce" />
            </ReactFlow>
            <div className="canvas-label">
              {flow.nodes.length} NODES · {flow.edges.length} CONNECTIONS
            </div>
          </div>
          <section className="bottom">
            <nav>
              {["실행", "검증", "SQL", "명세", "목록"].map((t) => (
                <button
                  key={t}
                  className={tab === t ? "active" : ""}
                  onClick={() => {
                    setTab(t);
                    if (t === "명세") setJsonText(pretty(flow));
                  }}
                >
                  {t}
                  {t === "검증" && issues.length > 0 ? ` (${issues.length})` : ""}
                </button>
              ))}
            </nav>
            {tab === "실행" && (
              <div className="run-panel">
                <div>
                  <label>테스트 입력</label>
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    spellCheck={false}
                  />
                </div>
                <div>
                  <label>응답</label>
                  <pre>
                    {result === null ? "미리보기를 실행하면 결과가 표시됩니다." : pretty(result)}
                  </pre>
                </div>
                <div>
                  <label>노드 실행 추적</label>
                  {trace.map((t, i) => (
                    <button
                      className={`trace ${t.status === "ERROR" ? "error" : ""}`}
                      key={i}
                      onClick={() => focusNode(t.nodeId)}
                    >
                      {t.status === "SUCCESS" ? "✓" : "!"} {t.nodeId}
                      <span>{t.durationMs} ms</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {tab === "검증" && (
              <div className="issues">
                {issues.length === 0 ? (
                  <p>검증 오류가 없습니다. 설정을 바꾼 뒤에는 다시 검증하세요.</p>
                ) : (
                  issues.map((i, k) => (
                    <button key={k} onClick={() => focusNode(i.nodeId)}>
                      <b>{i.nodeId ?? "Flow"}</b>
                      <span>
                        {i.field} · {i.message}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
            {tab === "SQL" && (
              <div className="sql-panel">
                {node?.type.startsWith("db.") ? (
                  <>
                    <div className="sql-actions">
                      <span>DB: {node.config.databaseRef}</span>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(async () => {
                            setMetadata(
                              await (
                                await api(`/databases/${node.config.databaseRef}/metadata`)
                              ).json(),
                            );
                          })
                        }
                      >
                        테이블·컬럼 탐색
                      </button>
                      <button disabled={busy} onClick={() => action(runSql)}>
                        SQL 미리보기
                        {node.type === "db.command" ? " · 종료 시 롤백" : ""}
                      </button>
                    </div>
                    <div className="sql-edit">
                      <React.Suspense fallback={<p>SQL 편집기 준비 중…</p>}>
                        <Editor
                          height="120px"
                          language="sql"
                          value={(() => {
                            try {
                              return JSON.parse(configText).sql ?? "";
                            } catch {
                              return "";
                            }
                          })()}
                          onChange={(v) => {
                            try {
                              setConfigText(pretty({ ...JSON.parse(configText), sql: v }));
                            } catch {}
                          }}
                          options={{
                            minimap: { enabled: false },
                            fontSize: 13,
                            scrollBeyondLastLine: false,
                          }}
                        />
                      </React.Suspense>
                      <div>
                        <label>바인딩 테스트 값 · JSON</label>
                        <textarea
                          aria-label="SQL 테스트 파라미터"
                          value={sqlParams}
                          onChange={(e) => setSqlParams(e.target.value)}
                        />
                      </div>
                    </div>
                    {sqlResult && (
                      <>
                        <p>
                          {sqlResult.durationMs} ms ·{" "}
                          {sqlResult.truncated ? "결과 제한 적용" : "조회 완료"}
                          {sqlResult.affectedRows !== undefined
                            ? ` · 변경 ${sqlResult.affectedRows}행 (롤백)`
                            : ""}
                        </p>
                        {sqlResult.columns && (
                          <table>
                            <thead>
                              <tr>
                                {sqlResult.columns.map((c: Json) => (
                                  <th key={c.name}>
                                    {c.name}
                                    <small>
                                      {c.type} {c.nullable ? "NULL" : ""}
                                    </small>
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {sqlResult.rows.map((r: Json, i: number) => (
                                <tr key={i}>
                                  {sqlResult.columns.map((c: Json) => (
                                    <td key={c.name}>
                                      {typeof r[c.name] === "object"
                                        ? JSON.stringify(r[c.name])
                                        : String(r[c.name])}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </>
                    )}
                    {metadata && (
                      <details open>
                        <summary>DB 메타데이터</summary>
                        <pre>{pretty(metadata)}</pre>
                      </details>
                    )}
                  </>
                ) : (
                  <p>SQL 노드를 선택하세요. 편집한 SQL은 ‘설정 적용’ 후 Flow에 반영됩니다.</p>
                )}
              </div>
            )}
            {tab === "명세" && (
              <div className="spec-panel">
                <textarea
                  value={jsonText}
                  onChange={(e) => setJsonText(e.target.value)}
                  spellCheck={false}
                />
                <div>
                  <button
                    onClick={() => {
                      try {
                        const next = JSON.parse(jsonText);
                        change(next);
                        setSelected("");
                        setMessage("명세를 적용했습니다. 검증을 실행하세요.");
                      } catch {
                        setMessage("JSON 형식을 확인하세요.");
                      }
                    }}
                  >
                    명세 적용
                  </button>
                  <button
                    onClick={() =>
                      download(
                        new Blob([pretty(flow)], { type: "application/json" }),
                        flow.id + ".json",
                      )
                    }
                  >
                    JSON 내보내기
                  </button>
                  <button onClick={() => change({ ...flow, revision: flow.revision + 1 })}>
                    다음 버전 만들기
                  </button>
                </div>
              </div>
            )}
            {tab === "목록" && (
              <div className="issues">
                {library.length === 0 ? (
                  <p>저장된 버전이 없습니다.</p>
                ) : (
                  library.map((f) => (
                    <button
                      key={`${f.id}-${f.revision}`}
                      onClick={() =>
                        action(async () => {
                          const data = await (await api(`/flows/${f.id}/${f.revision}`)).json();
                          change(data);
                          setSelected("");
                          setMessage("저장된 Flow를 불러왔습니다.");
                        })
                      }
                    >
                      {f.name} · {f.id} · rev {f.revision}
                    </button>
                  ))
                )}
              </div>
            )}
          </section>
        </section>
        <aside className={`properties ${propertiesOpen ? "open" : ""}`}>
          <h3>노드 속성</h3>
          {node ? (
            <>
              <span className="node-kind">{node.type}</span>
              <label>표시 이름</label>
              <input
                value={node.name}
                onChange={(e) =>
                  setFlow({
                    ...flow,
                    nodes: flow.nodes.map((n) =>
                      n.id === selected ? { ...n, name: e.target.value } : n,
                    ),
                  })
                }
              />
              <label>고유 ID</label>
              <code>{node.id}</code>
              <label>노드 설정 · JSON</label>
              <textarea
                className="config"
                value={configText}
                onChange={(e) => setConfigText(e.target.value)}
                spellCheck={false}
              />
              <button className="primary" onClick={applyConfig}>
                설정 적용
              </button>
              <p>
                입력 매핑은 <code>ref</code>, 계산은 <code>op / args</code>를 사용합니다. DB·외부
                서비스의 비밀정보는 서버 환경에 설정하세요.
              </p>
              <button
                className="danger"
                onClick={() => {
                  change({
                    ...flow,
                    nodes: flow.nodes.filter((n) => n.id !== selected),
                    edges: flow.edges.filter((e) => e.from !== selected && e.to !== selected),
                  });
                  setSelected("");
                }}
              >
                노드 삭제
              </button>
            </>
          ) : (
            <p>캔버스에서 노드를 선택하세요.</p>
          )}
        </aside>
      </main>
      <footer>
        <span className={busy ? "working" : ""}>{busy ? "● 처리 중" : "● " + message}</span>
        {executionId && (
          <button
            onClick={() =>
              action(async () => {
                await api(`/executions/${executionId}/cancel`, {});
                setMessage("실행 중 SQL에 취소를 요청했습니다.");
              })
            }
          >
            SQL 취소 요청
          </button>
        )}
        <span>FLOW SPEC 1.0 · JAVA RUNTIME</span>
      </footer>
      <input
        type="file"
        ref={file}
        hidden
        accept=".json"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          if (f)
            try {
              const next = JSON.parse(await f.text());
              change(next);
              setSelected("");
              setMessage("명세를 가져왔습니다. 검증을 실행하세요.");
            } catch {
              setMessage("유효한 Flow JSON 파일을 선택하세요.");
            }
          e.target.value = "";
        }}
      />
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <ReactFlowProvider>
    <App />
  </ReactFlowProvider>,
);
