import React, { useState, useRef, useEffect, Suspense } from "react";
import { createRoot } from "react-dom/client";
import type { Flow, FlowNode, Workspace, Process, Project, Json } from "./types";
import { nodeKinds, defaults, pretty } from "./types";
import DrawioEditor, { type DrawioHandle } from "./DrawioEditor";
import ManagementDialog, { type DialogKind } from "./ManagementDialog";
import NodeInspector from "./NodeInspector";
import EdgeInspector from "./EdgeInspector";
import ActivityLog, { type LogEntry } from "./ActivityLog";
import "./style.css";
const SqlEditor = React.lazy(() => import("./SqlEditor"));
const emptyWorkspace: Workspace = {
  databases: [],
  projects: [],
  drawioInstalled: false,
  editorUrl: "/drawio/index.html",
  version: "0.2.0",
};
const tabs = ["Flow", "Params", "Body", "Authorization", "SQL", "Contract", "Settings"] as const;
type Tab = (typeof tabs)[number];
const configurationSnapshot = (value: Flow | null) =>
  value ? JSON.stringify({ ...value, ui: undefined }) : "";

function App() {
  const [workspace, setWorkspace] = useState<Workspace>(emptyWorkspace),
    [databaseId, setDatabaseId] = useState("main"),
    [connected, setConnected] = useState(false),
    [rail] = useState("collections");
  const [process, setProcess] = useState<Process | null>(null),
    [flow, setFlow] = useState<Flow | null>(null),
    [opened, setOpened] = useState<{ id: string; name: string; code: string }[]>([]),
    [tab, setTab] = useState<Tab>("Flow");
  const [body, setBody] = useState('{\n  "name": "World"\n}'),
    [values, setValues] = useState<Json>({}),
    [dirty, setDirty] = useState(false),
    [loadKey, setLoadKey] = useState(0),
    [busy, setBusy] = useState(false),
    [message, setStatusMessage] = useState("로컬 워크스페이스를 불러오는 중입니다.");
  const [logs, setLogs] = useState<LogEntry[]>([]),
    [showLogs, setShowLogs] = useState(false);
  function logEvent(message: string, level = "INFO", details?: unknown) {
    setLogs((previous) => [...previous, { at: new Date().toISOString(), level, message, details }]);
  }
  function setMessage(message: string) {
    setStatusMessage(message);
    logEvent(message);
  }
  const [selected, setSelected] = useState(""),
    [showNodes, setShowNodes] = useState(false),
    [showInspector, setShowInspector] = useState(false),
    [dialog, setDialog] = useState<DialogKind | null>(null),
    [search, setSearch] = useState(""),
    [collapsed, setCollapsed] = useState<string[]>([]);
  const [dialogContext, setDialogContext] = useState<{ projectId: string; unitId: string } | null>(
    null,
  );
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [verified, setVerified] = useState<{
    id: string;
    processId: string;
    snapshot: string;
  } | null>(null);
  const [applied, setApplied] = useState<Json | null>(null);
  const [edgeSelection, setEdgeSelection] = useState<Flow["edges"][number] | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [response, setResponse] = useState<Json | null>(null),
    [issues, setIssues] = useState<Json[]>([]),
    [bottomTab, setBottomTab] = useState("Body"),
    [executionId, setExecutionId] = useState(""),
    [history, setHistory] = useState<Json[]>([]);
  const [sqlParameters, setSqlParameters] = useState("{}"),
    [sqlResult, setSqlResult] = useState<Json | null>(null),
    [metadata, setMetadata] = useState<Json | null>(null),
    [contractInput, setContractInput] = useState(""),
    [contractOutput, setContractOutput] = useState(""),
    [jsonText, setJsonText] = useState("");
  const drawio = useRef<DrawioHandle>(null),
    flowRef = useRef(flow),
    processRef = useRef(process),
    sequence = useRef(0),
    sendCommand = useRef<() => void>(() => {}),
    upload = useRef<HTMLInputElement>(null),
    cache = useRef(
      new Map<
        string,
        {
          process: Process;
          flow: Flow;
          body: string;
          values: Json;
          dirty: boolean;
          response: Json | null;
        }
      >(),
    );
  flowRef.current = flow;
  processRef.current = process;
  const selectedDb = workspace.databases.find((d) => d.id === databaseId),
    project = workspace.projects.find((p) => p.id === process?.project_id) ?? workspace.projects[0];
  const projectDbs = workspace.databases.filter((d) => project?.databaseIds.includes(d.id));
  const selectedNode = flow?.nodes.find((n) => n.id === selected),
    sqlNodes = flow?.nodes.filter((n) => n.type.startsWith("db.")) ?? [],
    sqlNode = sqlNodes.find((n) => n.id === selected) ?? sqlNodes[0];
  const trigger = flow?.nodes.find((n) => n.type === "trigger.http");
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty || Array.from(cache.current.values()).some((v) => v.dirty)) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const command = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector<HTMLInputElement>('input[aria-label="프로세스 검색"]')?.focus();
      }
      if (event.key === "Enter") {
        event.preventDefault();
        sendCommand.current();
      }
    };
    window.addEventListener("keydown", command);
    return () => window.removeEventListener("keydown", command);
  }, []);

  useEffect(() => {
    void action(() => refresh("main", true).then(() => {}));
  }, []);

  async function api(path: string, data?: unknown, method?: string): Promise<any> {
    const r = await fetch("/api" + path, {
      method: method ?? (data === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({ message: `HTTP ${r.status}` }));
      logEvent(
        `${method ?? (data === undefined ? "GET" : "POST")} /api${path} · HTTP ${r.status}`,
        "ERROR",
        e,
      );
      if (r.status === 401) setConnected(false);
      throw new Error(e.message ?? "요청에 실패했습니다.");
    }
    logEvent(`${method ?? (data === undefined ? "GET" : "POST")} /api${path} · HTTP ${r.status}`);
    if (r.headers.get("content-type")?.includes("application/zip")) return await r.blob();
    return r.json();
  }
  async function action(task: () => Promise<void>) {
    setBusy(true);
    try {
      await task();
    } catch (e) {
      setStatusMessage((e as Error).message);
      logEvent((e as Error).message, "ERROR");
    } finally {
      setBusy(false);
    }
  }
  function adopt(next: Flow, external = true) {
    if (configurationSnapshot(next) !== configurationSnapshot(flowRef.current)) setVerified(null);
    const comparable = (value: Flow | null) =>
      value ? JSON.stringify({ ...value, ui: { ...value.ui, drawioXml: undefined } }) : "";
    const changed =
      comparable(next) !== comparable(flowRef.current) ||
      (!!flowRef.current?.ui.drawioXml && next.ui.drawioXml !== flowRef.current.ui.drawioXml);
    setFlow(next);
    flowRef.current = next;
    if (changed) {
      setDirty(true);
    }
    if (external) setLoadKey((k) => k + 1);
  }
  function switchSaved(next: Process, local?: ReturnType<typeof cache.current.get>) {
    setVerified(null);
    setApplied(null);
    const current = local?.flow ?? next.flow;
    setProcess(next);
    processRef.current = next;
    setFlow(current);
    flowRef.current = current;
    setBody(
      local?.body ??
        pretty(
          Object.fromEntries(
            Object.entries(current.inputSchema.properties ?? {})
              .filter(([, v]) => (v as Json).type !== "object")
              .map(([k, v]) => [
                k,
                (v as Json).type === "integer"
                  ? 1
                  : (v as Json).type === "boolean"
                    ? false
                    : "World",
              ]),
          ),
        ),
    );
    setValues(
      local?.values ??
        Object.fromEntries(
          Object.entries(current.inputSchema.properties ?? {}).map(([k, v]) => [
            k,
            (v as Json).type === "integer" ? "1" : "World",
          ]),
        ),
    );
    setDirty(local?.dirty ?? false);
    setResponse(local?.response ?? null);
    setIssues([]);
    setEdgeSelection(null);
    setSelected("");
    setShowInspector(false);
    setContractInput(pretty(current.inputSchema));
    setContractOutput(pretty(current.outputSchema));
    setSqlResult(null);
    setMetadata(null);
    setLoadKey((k) => k + 1);
    setOpened((list) =>
      list.some((p) => p.id === next.id)
        ? list
        : [...list, { id: next.id, name: next.name, code: next.process_id }],
    );
  }
  async function loadProcess(id: string) {
    if (processRef.current && flowRef.current)
      cache.current.set(processRef.current.id, {
        process: processRef.current,
        flow: flowRef.current,
        body,
        values,
        dirty,
        response,
      });
    const local = cache.current.get(id);
    switchSaved(local?.process ?? (await api("/processes/" + id)), local);
    setMessage("프로세스를 불러왔습니다.");
  }
  async function closeTab(id: string) {
    const next = opened.filter((p) => p.id !== id);
    setOpened(next);
    if (id !== process?.id) return;
    if (next.length) {
      await loadProcess(next.at(-1)!.id);
      return;
    }
    if (processRef.current && flowRef.current)
      cache.current.set(id, {
        process: processRef.current,
        flow: flowRef.current,
        body,
        values,
        dirty,
        response,
      });
    setProcess(null);
    processRef.current = null;
    setFlow(null);
    flowRef.current = null;
    setDirty(false);
  }
  async function refresh(db = databaseId, initial = false) {
    const data: Workspace = await api("/workspace?databaseId=" + encodeURIComponent(db));
    setWorkspace(data);
    setConnected(true);
    if (initial) {
      const p = data.projects.find((p) => p.code === "ERP") ?? data.projects[0];
      const item =
        p?.units.flatMap((u) => u.processes).find((p) => p.process_id === "SYS-001") ??
        p?.units[0]?.processes[0];
      if (item) await loadProcess(item.id);
    }
    return data;
  }
  async function changeDatabase(id: string) {
    setDatabaseId(id);
    const next = await refresh(id);
    if (!next.projects.some((p) => p.id === processRef.current?.project_id)) {
      const target = next.projects[0]?.units.flatMap((u) => u.processes)[0];
      if (target) await loadProcess(target.id);
      else {
        if (processRef.current && flowRef.current)
          cache.current.set(processRef.current.id, {
            process: processRef.current,
            flow: flowRef.current,
            body,
            values,
            dirty,
            response,
          });
        setProcess(null);
        processRef.current = null;
        setFlow(null);
        flowRef.current = null;
      }
    }
    setMessage("선택한 DB가 연결된 프로젝트를 표시합니다.");
  }
  async function convert(xml: string) {
    const base = flowRef.current,
      context = processRef.current?.id;
    if (!base) return null;
    const requestId = ++sequence.current;
    const result = await api("/drawio/convert", { flow: base, xml });
    if (context === processRef.current?.id && requestId === sequence.current) {
      adopt(result.flow, false);
      setIssues(result.issues);
    }
    return result.flow as Flow;
  }
  async function prepare(): Promise<Flow> {
    if (drawio.current?.ready()) {
      const xml = await drawio.current.sync();
      return (await convert(xml)) ?? flowRef.current!;
    }
    if (!flowRef.current) throw new Error("프로세스를 선택하세요.");
    return flowRef.current;
  }
  async function save() {
    if (!process) return;
    const current = await prepare();
    const saved: Process = await api(
      `/processes/${process.id}/draft`,
      { flow: current, expectedVersion: process.draft_version },
      "PUT",
    );
    setProcess(saved);
    processRef.current = saved;
    setDirty(false);
    cache.current.delete(saved.id);
    await refresh();
    setMessage("초안을 저장했습니다.");
  }
  async function publish() {
    if (!process) return;
    const current = await prepare();
    let saved: Process = await api(
      `/processes/${process.id}/draft`,
      { flow: current, expectedVersion: processRef.current!.draft_version },
      "PUT",
    );
    saved = await api(`/processes/${process.id}/versions`, {
      expectedVersion: saved.draft_version,
    });
    switchSaved(saved);
    cache.current.delete(saved.id);
    await refresh();
    setMessage(`버전 ${saved.latest_revision}을 확정했습니다.`);
  }
  async function check() {
    if (!project || !flow || !process) return false;
    setVerified(null);
    const current = await prepare();
    const snapshot = configurationSnapshot(current),
      id = process.id;
    const result = await api("/validate?projectId=" + project.id + "&processId=" + id, current);
    if (
      result.valid &&
      result.validationId &&
      processRef.current?.id === id &&
      configurationSnapshot(flowRef.current) === snapshot
    )
      setVerified({ id: result.validationId, processId: id, snapshot });
    setIssues(result.issues);
    setBottomTab("Validation");
    logEvent(
      result.valid ? "구성 검증 통과" : "구성 검증 실패",
      result.valid ? "INFO" : "WARN",
      result.issues,
    );
    setTestOpen(true);
    setMessage(
      result.valid
        ? "구성 검증을 통과했습니다. 서버에 반영할 수 있습니다."
        : `${result.issues.length}개 검증 오류를 확인하세요.`,
    );
    return result.valid;
  }
  async function send() {
    if (!process || !project) return;
    const current = await prepare();
    const validity = await api("/validate?projectId=" + project.id, current);
    setIssues(validity.issues);
    if (!validity.valid) {
      setBottomTab("Validation");
      setMessage("Flow 검증 오류를 먼저 수정하세요.");
      return;
    }
    const id = crypto.randomUUID();
    setExecutionId(id);
    try {
      const r = await api(`/processes/${process.id}/preview`, {
        flow: current,
        input: JSON.parse(body || "{}"),
        executionId: id,
      });
      setResponse(r);
      logEvent("프로세스 테스트 실행 추적", r.status < 400 ? "INFO" : "ERROR", r.trace);
      setBottomTab("Body");
      setMessage(`실행 완료 · HTTP ${r.status} · ${r.durationMs} ms`);
    } finally {
      setExecutionId("");
    }
  }
  sendCommand.current = () => {
    if (!busy && process) {
      setTestOpen(true);
      void action(send);
    }
  };
  async function applyServer() {
    if (!process || !verified) return;
    const proof = verified;
    const current = await prepare();
    if (
      proof.processId !== processRef.current?.id ||
      configurationSnapshot(current) !== proof.snapshot
    ) {
      setVerified(null);
      throw new Error("구성이 변경되었습니다. 구성 검증을 다시 수행하세요.");
    }
    try {
      const result = await api(`/processes/${process.id}/apply`, {
        flow: current,
        validationId: proof.id,
      });
      setApplied(result);
      logEvent("서버 반영 결과", "INFO", result);
      setMessage(`서버 반영 완료 · Python 코드: ${result.sourcePath}`);
    } catch (error) {
      setVerified(null);
      throw error;
    }
  }
  function updateNode(node: FlowNode) {
    if (!flow) return;
    const next = { ...flow, nodes: flow.nodes.map((n) => (n.id === node.id ? node : n)) };
    if (node.config.databaseRef && !next.resources.databases.includes(node.config.databaseRef))
      next.resources = {
        ...next.resources,
        databases: [...next.resources.databases, node.config.databaseRef],
      };
    adopt(next);
  }
  function addNode(kind: string) {
    if (!flow) return;
    const id = "n_" + crypto.randomUUID().slice(0, 8),
      config = structuredClone(defaults[kind]);
    if (config.databaseRef) config.databaseRef = projectDbs[0]?.id ?? databaseId;
    const node = { id, type: kind, name: nodeKinds.find((k) => k[0] === kind)![1], config };
    let resources = flow.resources;
    if (config.databaseRef && !resources.databases.includes(config.databaseRef))
      resources = { ...resources, databases: [...resources.databases, config.databaseRef] };
    if (config.serviceRef && !resources.services.includes(config.serviceRef))
      resources = { ...resources, services: [...resources.services, config.serviceRef] };
    adopt({
      ...flow,
      nodes: [...flow.nodes, node],
      resources,
      ui: {
        ...flow.ui,
        positions: { ...flow.ui.positions, [id]: { x: 100 + flow.nodes.length * 70, y: 320 } },
      },
    });
    setEdgeSelection(null);
    setSelected(id);
    setShowInspector(true);
    setShowNodes(false);
  }
  async function management(data: Json) {
    setVerified(null);
    let created;
    if (dialog === "database") await api("/databases/" + data.id, data, "PUT");
    if (dialog === "project") await api("/projects", data);
    if (dialog === "unit") {
      const { projectId, ...payload } = data;
      await api(`/projects/${projectId}/units`, payload);
    }
    if (dialog === "process") {
      const { unitId, ...payload } = data;
      created = await api(`/units/${unitId}/processes`, payload);
    }
    if (dialog === "bindings" && project) {
      await api(`/projects/${project.id}/databases`, data, "PUT");
      if (process) {
        const fresh = await api("/processes/" + process.id);
        setProcess(fresh);
      }
    }
    await refresh();
    if (created) switchSaved(created);
    setMessage("워크스페이스를 저장했습니다.");
  }
  async function runSql() {
    if (!sqlNode || !project) return;
    const id = crypto.randomUUID();
    setExecutionId(id);
    try {
      setSqlResult(
        await api("/sql/preview", {
          projectId: project.id,
          databaseRef: sqlNode.config.databaseRef,
          sql: sqlNode.config.sql,
          parameters: JSON.parse(sqlParameters),
          command: sqlNode.type === "db.command",
          executionId: id,
        }),
      );
      setMessage("SQL 미리보기를 완료했습니다.");
    } finally {
      setExecutionId("");
    }
  }
  function toggle(id: string) {
    setCollapsed((list) => (list.includes(id) ? list.filter((i) => i !== id) : [...list, id]));
  }
  function selectTab(next: Tab) {
    setTab(next);
    if (next === "Flow") requestAnimationFrame(() => drawio.current?.fit());
    if (next === "Contract" && flow) {
      setContractInput(pretty(flow.inputSchema));
      setContractOutput(pretty(flow.outputSchema));
    }
    if (next === "Settings" && flow) setJsonText(pretty(flow));
  }
  const requests = workspace.projects.flatMap((p) => p.units.flatMap((u) => u.processes));

  return (
    <div className="studio">
      <div className="app-body">
        <button
          className="sidebar-toggle"
          aria-label="왼쪽 메뉴 토글"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          {sidebarOpen ? "‹" : "›"}
        </button>
        <aside className="collection-sidebar" hidden={!sidebarOpen}>
          <div className="sidebar-title">
            <strong>
              {rail === "collections"
                ? "업무 프로세스"
                : rail === "databases"
                  ? "Databases"
                  : "History"}
            </strong>
            <button
              className="icon-button"
              aria-label="새 프로젝트"
              disabled={!connected}
              onClick={() => setDialog("project")}
            >
              ＋
            </button>
          </div>
          <div className="sidebar-search">
            <input
              aria-label="프로세스 검색"
              placeholder="프로세스 검색 · Ctrl K"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button className="sidebar-db-settings" onClick={() => setDialog("database")}>
            DB 연결 관리
          </button>
          <div className="database-filter">
            <span className={"vendor-dot " + selectedDb?.vendor} />
            <select
              aria-label="DB 선택"
              value={databaseId}
              onChange={(e) => action(() => changeDatabase(e.target.value))}
              disabled={!connected}
            >
              {workspace.databases.length ? (
                workspace.databases.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))
              ) : (
                <option value="main">데이터베이스 선택</option>
              )}
            </select>
            <span className="mini-count">{workspace.databases.length}</span>
          </div>
          {rail === "collections" ? (
            <>
              <div className="hierarchy-guide">
                DB <span>›</span> 프로젝트 <span>›</span> 업무 <span>›</span> 프로세스
              </div>
              <div className="tree">
                {workspace.projects.map((p) => (
                  <div key={p.id} className="project-group">
                    <div className="tree-project">
                      <button className="tree-label" onClick={() => toggle(p.id)}>
                        <span className="chevron">{collapsed.includes(p.id) ? "›" : "⌄"}</span>
                        <span className="folder-icon">▰</span>
                        <strong>{p.name}</strong>
                      </button>
                      <button
                        className="tree-add"
                        aria-label={p.name + " 업무 단위 추가"}
                        onClick={() => {
                          setDialogContext({ projectId: p.id, unitId: "" });
                          setDialog("unit");
                        }}
                      >
                        ＋
                      </button>
                    </div>
                    {!collapsed.includes(p.id) &&
                      p.units.map((u) => (
                        <div className="unit-group" key={u.id}>
                          <div className="tree-unit">
                            <button className="tree-label" onClick={() => toggle(u.id)}>
                              <span className="chevron">
                                {collapsed.includes(u.id) ? "›" : "⌄"}
                              </span>
                              <span>▱</span>
                              {u.name}
                            </button>
                            <span className="tree-count">{u.processes.length}</span>
                            <button
                              className="tree-add"
                              aria-label={u.name + " 프로세스 추가"}
                              onClick={() => {
                                setDialogContext({ projectId: p.id, unitId: u.id });
                                setDialog("process");
                              }}
                            >
                              ＋
                            </button>
                          </div>
                          {!collapsed.includes(u.id) &&
                            u.processes
                              .filter((item) =>
                                (item.name + " " + item.process_id)
                                  .toLowerCase()
                                  .includes(search.toLowerCase()),
                              )
                              .map((item) => (
                                <button
                                  key={item.id}
                                  className={
                                    "process-row " + (process?.id === item.id ? "selected" : "")
                                  }
                                  onClick={() => action(() => loadProcess(item.id))}
                                >
                                  <span>
                                    <strong>{item.name}</strong>
                                    <small>{item.process_id}</small>
                                  </span>
                                  {item.latest_revision > 0 && <em>v{item.latest_revision}</em>}
                                </button>
                              ))}
                          {!collapsed.includes(u.id) && u.processes.length === 0 && (
                            <span className="tree-empty">프로세스를 추가하세요</span>
                          )}
                        </div>
                      ))}
                    {!collapsed.includes(p.id) && p.units.length === 0 && (
                      <span className="tree-empty">업무 단위를 추가하세요</span>
                    )}
                  </div>
                ))}
                {!connected && (
                  <div className="sidebar-empty">
                    <span>↗</span>
                    <p>
                      API 토큰으로 연결하면
                      <br />
                      프로젝트가 표시됩니다.
                    </p>
                  </div>
                )}
              </div>
              <div className="sidebar-actions">
                <button disabled={!connected} onClick={() => setDialog("unit")}>
                  ＋ 업무 단위
                </button>
                <button
                  disabled={!connected || !workspace.projects.some((p) => p.units.length)}
                  onClick={() => setDialog("process")}
                >
                  ＋ 프로세스
                </button>
              </div>
            </>
          ) : rail === "databases" ? (
            <div className="database-list">
              {workspace.databases.map((d) => (
                <div className="database-card" key={d.id}>
                  <div>
                    <span className={"vendor-dot " + d.vendor} />
                    <strong>{d.name}</strong>
                    <small>{d.vendor.toUpperCase()}</small>
                  </div>
                  <p>{d.configured ? `${d.host || d.dsn}:${d.port}` : "연결 정보 미설정"}</p>
                  <span className={"db-state " + (d.secretAvailable ? "configured" : "")}>
                    {d.secretAvailable ? "Secret available" : "Secret not set"}
                  </span>
                  <button
                    onClick={() =>
                      action(async () => {
                        await api(`/databases/${d.id}/test`, {});
                        setMessage(d.name + " 연결 확인 완료");
                      })
                    }
                  >
                    연결 테스트
                  </button>
                </div>
              ))}
              <button disabled={!connected} onClick={() => setDialog("database")}>
                ＋ DB 연결 추가·수정
              </button>
            </div>
          ) : (
            <div className="history-list">
              {history.length ? (
                history.map((h) => (
                  <button
                    key={h.id}
                    onClick={() =>
                      action(async () => {
                        if (h.process_id !== process?.id) await loadProcess(h.process_id);
                        const traces = await api("/executions/" + h.id);
                        setResponse({
                          status: h.status,
                          durationMs: h.duration_ms,
                          trace: traces,
                          body: { message: "과거 실행의 입력·응답 원문은 보관하지 않습니다." },
                        });
                        setBottomTab("Trace");
                      })
                    }
                  >
                    <span className={h.status < 400 ? "ok-text" : "error-text"}>{h.status}</span>
                    <span>
                      {requests.find((p) => p.id === h.process_id)?.name ?? "프로세스"}
                      <small>{new Date(h.at).toLocaleString("ko-KR")}</small>
                    </span>
                    <em>{h.duration_ms}ms</em>
                  </button>
                ))
              ) : (
                <p className="muted padded">실행 기록이 없습니다.</p>
              )}
            </div>
          )}
          <div className="sidebar-bottom">
            <span className="status-dot online" />
            Python runtime <span>0.2</span>
          </div>
        </aside>
        <main className="workbench">
          <div className="process-tabs">
            {opened.map((item) => (
              <button
                key={item.id}
                className={process?.id === item.id ? "active" : ""}
                onClick={() => action(() => loadProcess(item.id))}
              >
                {item.code}
                <span
                  className="tab-dirty"
                  role="button"
                  tabIndex={0}
                  aria-label={item.code + " 탭 닫기"}
                  onClick={(e) => {
                    e.stopPropagation();
                    void action(() => closeTab(item.id));
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.stopPropagation();
                      void action(() => closeTab(item.id));
                    }
                  }}
                >
                  {item.id === process?.id && dirty ? "●" : "×"}
                </span>
              </button>
            ))}
            <button
              className="tab-plus"
              disabled={!connected}
              aria-label="프로세스 추가"
              onClick={() => setDialog("process")}
            >
              ＋
            </button>
            <div className="spacer" />
          </div>
          {flow && process ? (
            <>
              <div className="process-heading">
                <div className="breadcrumbs">
                  <span>{selectedDb?.name}</span>
                  <b>›</b>
                  <button onClick={() => setDialog("bindings")}>{process.project.name}</button>
                  <b>›</b>
                  <span>{process.unit_name}</span>
                  <b>›</b>
                  <strong>{process.process_id}</strong>
                </div>
                <div className="heading-actions">
                  <span className="draft-label">
                    {dirty ? "● Unsaved" : "Draft saved"} · v{process.latest_revision}
                  </span>
                  <button disabled={busy} onClick={() => action(save)}>
                    ♧ 저장
                  </button>
                  <button disabled={busy} onClick={() => action(publish)}>
                    버전 확정
                  </button>
                </div>
              </div>
              <div className="request-nav">
                {tabs
                  .filter((t) => !["Params", "Body", "Authorization"].includes(t))
                  .map((t) => (
                    <button
                      key={t}
                      className={tab === t ? "active" : ""}
                      onClick={() => selectTab(t)}
                    >
                      {t}
                      {t === "Params" && (
                        <span>
                          {
                            Object.keys(trigger?.config.input ?? {}).filter(
                              (k) =>
                                (trigger?.config.input[k].source ?? "").startsWith("path.") ||
                                (trigger?.config.input[k].source ?? "").startsWith("query."),
                            ).length
                          }
                        </span>
                      )}
                      {t === "Flow" && <i className="small-dot" />}
                    </button>
                  ))}
                <div className="spacer" />
                <button
                  className="validate-button"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      await check();
                    })
                  }
                >
                  ✓ 구성 검증
                </button>
                <button
                  className="apply-button"
                  disabled={
                    busy ||
                    !verified ||
                    verified.processId !== process.id ||
                    verified.snapshot !== configurationSnapshot(flow)
                  }
                  onClick={() => action(applyServer)}
                >
                  서버 반영
                </button>
              </div>
              {applied && (
                <div className="apply-summary" role="status">
                  반영된 코드 <code>{applied.sourcePath}</code>
                  <span>
                    변경 노드{" "}
                    {applied.changes.addedNodes.length +
                      applied.changes.changedNodes.length +
                      applied.changes.removedNodes.length}
                    개 · {verified ? "검증된 구성" : "변경 후 재검증 필요"}
                  </span>
                  <button
                    className="icon-button"
                    aria-label="서버 반영 알림 닫기"
                    onClick={() => setApplied(null)}
                  >
                    ×
                  </button>
                </div>
              )}
              <section className="request-content">
                <div className="flow-panel" style={{ display: tab === "Flow" ? "flex" : "none" }}>
                  <div className="flow-tools">
                    <span className="drawio-logo">▧</span>
                    <strong>draw.io</strong>
                    <span className="separator" />
                    <button onClick={() => setShowNodes(!showNodes)}>＋ 업무 노드</button>
                    <button onClick={() => drawio.current?.undo()} aria-label="실행 취소">
                      ↶
                    </button>
                    <button onClick={() => drawio.current?.redo()} aria-label="다시 실행">
                      ↷
                    </button>
                    <button onClick={() => drawio.current?.fit()}>맞춤 보기</button>
                    <div className="spacer" />
                    <span className="diagram-count">
                      {flow.nodes.length} nodes · {flow.edges.length} edges
                    </span>
                    <button onClick={() => setShowInspector(!showInspector)}>노드 설정</button>
                  </div>
                  <div className="diagram-wrap">
                    <DrawioEditor
                      key={process.id}
                      ref={drawio}
                      flow={flow}
                      loadKey={loadKey}
                      installed={workspace.drawioInstalled}
                      editorUrl={workspace.editorUrl}
                      onXml={async (xml) => {
                        await convert(xml);
                      }}
                      onError={setMessage}
                      onCanvasClick={() => setShowInspector(false)}
                      onSelect={(id) => {
                        setEdgeSelection(null);
                        setSelected(id);
                        setShowInspector(true);
                      }}
                      onEdgeSelect={(edge) => {
                        setSelected("");
                        setEdgeSelection(edge);
                        setShowInspector(true);
                      }}
                    />
                    {showNodes && (
                      <div className="node-menu">
                        <h3>업무 노드 추가</h3>
                        {nodeKinds.map(([kind, name, icon]) => (
                          <button key={kind} onClick={() => addNode(kind)}>
                            <span>{icon}</span>
                            {name}
                            <small>{kind}</small>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="node-strip">
                    {flow.nodes.map((n) => (
                      <button
                        key={n.id}
                        className={selected === n.id ? "selected" : ""}
                        onClick={() => {
                          setEdgeSelection(null);
                          setSelected(n.id);
                          setShowInspector(true);
                        }}
                      >
                        <span
                          className={
                            response?.trace?.some(
                              (t: Json) => t.nodeId === n.id && t.status === "ERROR",
                            )
                              ? "error-text"
                              : ""
                          }
                        >
                          {response?.trace?.some((t: Json) => t.nodeId === n.id) ? "●" : "◇"}
                        </span>
                        {n.name}
                        <small>{n.id}</small>
                      </button>
                    ))}
                  </div>
                </div>
                {tab === "Params" && (
                  <div className="parameters-panel">
                    <div className="panel-caption">
                      <h3>Request parameters</h3>
                      <span>진입 노드의 입력 매핑과 연결됩니다.</span>
                    </div>
                    <table className="params-table">
                      <thead>
                        <tr>
                          <th>Source</th>
                          <th>Key</th>
                          <th>Value</th>
                          <th>Input field</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(trigger?.config.input ?? {}).map(([key, mapping]) => {
                          const m = mapping as Json;
                          return (
                            <tr key={key}>
                              <td>
                                <span className="source-tag">{m.source.split(".")[0]}</span>
                              </td>
                              <td>{m.source.split(".").slice(1).join(".")}</td>
                              <td>
                                {m.source.startsWith("body.") ? (
                                  <span className="muted">Body 탭에서 설정</span>
                                ) : (
                                  <input
                                    aria-label={key + " 파라미터"}
                                    value={values[key] ?? ""}
                                    onChange={(e) =>
                                      setValues({ ...values, [key]: e.target.value })
                                    }
                                  />
                                )}
                              </td>
                              <td>
                                <code>{key}</code> <small>{m.convert ?? "original"}</small>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <p className="panel-hint">
                      입력 필드를 추가하거나 변경하려면 HTTP 진입 노드의 input 매핑을 편집하세요.
                    </p>
                  </div>
                )}
                {tab === "Body" && (
                  <div className="body-panel">
                    <div className="editor-caption">
                      <span className="radio-selected">●</span> raw{" "}
                      <span className="json-label">JSON ▾</span>
                      <div className="spacer" />
                      <button
                        onClick={() => {
                          try {
                            setBody(pretty(JSON.parse(body)));
                          } catch {
                            setMessage("Body JSON 형식을 확인하세요.");
                          }
                        }}
                      >
                        Beautify
                      </button>
                    </div>
                    <div className="text-editor">
                      <div className="line-numbers">
                        {body.split("\n").map((_, i) => (
                          <span key={i}>{i + 1}</span>
                        ))}
                      </div>
                      <textarea
                        spellCheck={false}
                        aria-label="요청 Body JSON"
                        value={body}
                        onChange={(e) => setBody(e.target.value)}
                      />
                    </div>
                  </div>
                )}
                {tab === "Authorization" && (
                  <div className="authorization-panel">
                    <div>
                      <h3>생성 API 인증</h3>
                      <p>워크스페이스 관리 토큰과 생성 서버의 API 토큰은 별개입니다.</p>
                      <label>
                        Type
                        <select
                          value={flow.settings.authentication}
                          onChange={(e) =>
                            adopt({
                              ...flow,
                              settings: { ...flow.settings, authentication: e.target.value },
                            })
                          }
                        >
                          <option value="bearer">Bearer Token</option>
                          <option value="public">No Auth · 공개 API</option>
                        </select>
                      </label>
                    </div>
                    <div className="auth-description">
                      <span className="type-badge">
                        {flow.settings.authentication === "bearer"
                          ? "Bearer authentication"
                          : "Public endpoint"}
                      </span>
                      <p>
                        {flow.settings.authentication === "bearer"
                          ? "생성 서버의 FLOW_RUNTIME_TOKEN 환경 변수에 토큰을 설정합니다. 요청에는 Authorization: Bearer <token> 헤더를 사용하세요."
                          : "이 프로세스의 생성 API는 인증 없이 호출할 수 있습니다."}
                      </p>
                      <p className="muted">
                        현재 Send는 내부 미리보기를 실행하며, 생성 서버의 인증 동작은 생성 서버에서
                        별도로 검증합니다.
                      </p>
                    </div>
                  </div>
                )}
                {tab === "SQL" && (
                  <div className="sql-panel">
                    {sqlNode ? (
                      <>
                        <div className="sql-toolbar">
                          <select
                            aria-label="SQL 노드 선택"
                            value={sqlNode.id}
                            onChange={(e) => {
                              setEdgeSelection(null);
                              setSelected(e.target.value);
                            }}
                          >
                            {sqlNodes.map((n) => (
                              <option key={n.id} value={n.id}>
                                {n.name}
                              </option>
                            ))}
                          </select>
                          <span>Database</span>
                          <select
                            aria-label="SQL 실행 DB"
                            value={sqlNode.config.databaseRef}
                            onChange={(e) => {
                              updateNode({
                                ...sqlNode,
                                config: { ...sqlNode.config, databaseRef: e.target.value },
                              });
                              setMetadata(null);
                            }}
                          >
                            {projectDbs.map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.name}
                              </option>
                            ))}
                          </select>
                          <button
                            onClick={() =>
                              action(async () => {
                                setMetadata(
                                  await api(
                                    "/databases/" + sqlNode.config.databaseRef + "/metadata",
                                  ),
                                );
                              })
                            }
                          >
                            Schema
                          </button>
                          <div className="spacer" />
                          <button className="orange" disabled={busy} onClick={() => action(runSql)}>
                            ▷ Run SQL{sqlNode.type === "db.command" ? " · Rollback" : ""}
                          </button>
                        </div>
                        <div className="sql-workspace">
                          <div className="sql-main">
                            <Suspense
                              fallback={<p className="padded muted">SQL 편집기 준비 중…</p>}
                            >
                              <SqlEditor
                                height="165px"
                                language="sql"
                                theme="vs-dark"
                                value={sqlNode.config.sql}
                                onChange={(value) =>
                                  updateNode({
                                    ...sqlNode,
                                    config: { ...sqlNode.config, sql: value ?? "" },
                                  })
                                }
                                options={{
                                  minimap: { enabled: false },
                                  fontSize: 12,
                                  scrollBeyondLastLine: false,
                                  wordWrap: "on",
                                }}
                              />
                            </Suspense>
                            <label className="sql-parameters">
                              바인딩 테스트 값 · JSON
                              <textarea
                                className="code-input"
                                aria-label="SQL 파라미터 JSON"
                                value={sqlParameters}
                                onChange={(e) => setSqlParameters(e.target.value)}
                              />
                            </label>
                          </div>
                          {metadata && (
                            <aside className="schema-browser">
                              <h4>
                                Schema{" "}
                                <button className="icon-button" onClick={() => setMetadata(null)}>
                                  ×
                                </button>
                              </h4>
                              {Object.entries(
                                (metadata.columns as Json[]).reduce(
                                  (result: Json, c: Json) => ({
                                    ...result,
                                    [c.table]: [...(result[c.table] ?? []), c],
                                  }),
                                  {},
                                ),
                              ).map(([table, cols]) => (
                                <details key={table}>
                                  <summary>▤ {table}</summary>
                                  {(cols as Json[]).map((c) => (
                                    <div key={c.name}>
                                      {c.name}
                                      <small>{c.type}</small>
                                    </div>
                                  ))}
                                </details>
                              ))}
                            </aside>
                          )}
                        </div>
                        {sqlResult && (
                          <div className="sql-results">
                            <div className="panel-caption">
                              <strong>
                                {sqlResult.rolledBack
                                  ? `${sqlResult.affectedRows}행 변경 후 롤백`
                                  : `${sqlResult.rows?.length ?? 0} rows`}
                              </strong>
                              <span>
                                {sqlResult.durationMs} ms ·{" "}
                                {sqlResult.truncated ? "결과 제한 적용" : "Complete"}
                              </span>
                            </div>
                            {sqlResult.columns && (
                              <div className="table-scroll">
                                <table>
                                  <thead>
                                    <tr>
                                      {sqlResult.columns.map((c: Json) => (
                                        <th key={c.name}>
                                          {c.name}
                                          <small>{c.type}</small>
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
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="panel-empty">
                        <span>▤</span>
                        <h3>SQL 노드를 추가하세요</h3>
                        <p>각 SQL 노드에서 프로젝트에 연결된 DB를 선택할 수 있습니다.</p>
                        <button
                          onClick={() => {
                            addNode("db.query");
                          }}
                        >
                          ＋ SQL 조회 노드
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {tab === "Contract" && (
                  <div className="contract-panel">
                    <div>
                      <label>Input · JSON Schema</label>
                      <textarea
                        className="code-input"
                        value={contractInput}
                        onChange={(e) => setContractInput(e.target.value)}
                      />
                    </div>
                    <div>
                      <label>Output · JSON Schema</label>
                      <textarea
                        className="code-input"
                        value={contractOutput}
                        onChange={(e) => setContractOutput(e.target.value)}
                      />
                    </div>
                    <button
                      className="orange"
                      onClick={() => {
                        try {
                          adopt({
                            ...flow,
                            inputSchema: JSON.parse(contractInput),
                            outputSchema: JSON.parse(contractOutput),
                          });
                          setMessage("데이터 계약을 적용했습니다.");
                        } catch {
                          setMessage("계약 JSON 형식을 확인하세요.");
                        }
                      }}
                    >
                      계약 적용
                    </button>
                  </div>
                )}
                {tab === "Settings" && (
                  <div className="settings-panel">
                    <div className="settings-actions">
                      <label>
                        시간 제한 (ms)
                        <input
                          type="number"
                          value={flow.settings.timeoutMs}
                          min="1"
                          max="60000"
                          onChange={(e) =>
                            adopt({
                              ...flow,
                              settings: { ...flow.settings, timeoutMs: Number(e.target.value) },
                            })
                          }
                        />
                      </label>
                      <button
                        onClick={() => {
                          setJsonText(pretty(flow));
                        }}
                      >
                        최신 명세 보기
                      </button>

                      <div className="versions">
                        <strong>Saved versions</strong>
                        {process.versions.length ? (
                          process.versions.map((v) => (
                            <button
                              key={v.revision}
                              onClick={() =>
                                action(async () => {
                                  const old = await api(
                                    `/processes/${process.id}/versions/${v.revision}`,
                                  );
                                  adopt(old);
                                  setJsonText(pretty(old));
                                  setMessage(
                                    `v${v.revision}을 초안으로 복원했습니다. 저장 전 검증하세요.`,
                                  );
                                })
                              }
                            >
                              v{v.revision} · {v.hash.slice(0, 8)}
                            </button>
                          ))
                        ) : (
                          <span className="muted">확정된 버전 없음</span>
                        )}
                      </div>
                    </div>
                    <div className="raw-spec">
                      <textarea
                        className="code-input"
                        value={jsonText}
                        onChange={(e) => setJsonText(e.target.value)}
                      />
                      <button
                        onClick={() => {
                          try {
                            const next = JSON.parse(jsonText);
                            if (
                              !Array.isArray(next.nodes) ||
                              !Array.isArray(next.edges) ||
                              next.id !== process.process_id
                            )
                              throw new Error();
                            adopt({ ...next, ui: next.ui ?? {} });
                            setMessage("명세를 적용했습니다.");
                          } catch {
                            setMessage("프로세스 ID와 Flow JSON 구조를 확인하세요.");
                          }
                        }}
                      >
                        명세 적용
                      </button>
                    </div>
                  </div>
                )}
              </section>
              <section
                className={"response-panel process-test " + (testOpen ? "expanded" : "collapsed")}
              >
                <div className="test-toggle-bar">
                  <button aria-expanded={testOpen} onClick={() => setTestOpen(!testOpen)}>
                    {testOpen ? "▾" : "▸"} 프로세스 테스트
                  </button>
                  <span>입력값 → 업무 실행 → 출력값</span>
                  <div className="spacer" />
                  <button
                    className="send-button"
                    disabled={busy}
                    onClick={() => {
                      setTestOpen(true);
                      void action(send);
                    }}
                  >
                    {busy ? "실행 중…" : "프로세스 실행"}
                  </button>
                </div>
                {testOpen && (
                  <div className="test-workspace">
                    <div className="test-input">
                      <label>
                        수동 입력값 · JSON
                        <textarea
                          aria-label="프로세스 입력값 JSON"
                          value={body}
                          onChange={(e) => setBody(e.target.value)}
                          spellCheck={false}
                        />
                      </label>
                    </div>
                    <div className="test-output">
                      <div className="response-top">
                        <span>Response</span>
                        <div className="response-tabs">
                          {["Body", "Trace", "Validation"].map((t) => (
                            <button
                              className={bottomTab === t ? "active" : ""}
                              key={t}
                              onClick={() => setBottomTab(t)}
                            >
                              {t}
                              {t === "Validation" && issues.length > 0 && <b>{issues.length}</b>}
                            </button>
                          ))}
                        </div>
                        <div className="spacer" />
                        {response && (
                          <div className="response-meta">
                            <span className={response.status < 400 ? "ok-text" : "error-text"}>
                              Status: <strong>{response.status}</strong>
                            </span>
                            <span>
                              Time: <strong>{response.durationMs} ms</strong>
                            </span>
                            <span>
                              Size:{" "}
                              <strong>
                                {new TextEncoder().encode(JSON.stringify(response.body)).length} B
                              </strong>
                            </span>
                          </div>
                        )}
                        {executionId && (
                          <button
                            className="cancel-button"
                            onClick={() =>
                              action(async () => {
                                const r = await api("/executions/" + executionId + "/cancel", {});
                                setMessage(
                                  r.cancelRequested
                                    ? "실행 취소를 요청했습니다."
                                    : "이미 종료된 실행입니다.",
                                );
                              })
                            }
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                      <div className="response-body">
                        {bottomTab === "Body" ? (
                          response ? (
                            <div className="response-json">
                              <div className="json-toolbar">
                                <span className="active">Pretty</span>
                                <span>JSON</span>
                                <button
                                  onClick={() =>
                                    navigator.clipboard.writeText(pretty(response.body))
                                  }
                                >
                                  Copy
                                </button>
                              </div>
                              <pre>{pretty(response.body)}</pre>
                            </div>
                          ) : (
                            <div className="response-empty">
                              <span>↗</span>
                              <div>
                                <strong>프로세스 실행 결과</strong>
                                <p>입력값을 작성하고 프로세스 실행을 눌러 출력값을 확인하세요.</p>
                              </div>
                            </div>
                          )
                        ) : bottomTab === "Trace" ? (
                          <div className="trace-list">
                            {response?.trace?.length ? (
                              response.trace.map((t: Json, i: number) => (
                                <button
                                  key={i}
                                  onClick={() => {
                                    setEdgeSelection(null);
                                    setSelected(t.nodeId);
                                    setShowInspector(true);
                                    setTab("Flow");
                                  }}
                                >
                                  <span
                                    className={t.status === "SUCCESS" ? "ok-text" : "error-text"}
                                  >
                                    {t.status === "SUCCESS" ? "✓" : "!"}
                                  </span>
                                  <strong>
                                    {flow.nodes.find((n) => n.id === t.nodeId)?.name ?? t.nodeId}
                                  </strong>
                                  <code>{t.nodeId}</code>
                                  <span>{t.errorCode ?? t.status}</span>
                                  <em>{t.durationMs} ms</em>
                                </button>
                              ))
                            ) : (
                              <p className="muted padded">
                                실행한 노드의 상태와 시간이 표시됩니다.
                              </p>
                            )}
                          </div>
                        ) : (
                          <div className="validation-list">
                            {issues.length ? (
                              issues.map((issue, i) => (
                                <button
                                  key={i}
                                  onClick={() => {
                                    if (issue.nodeId) {
                                      setEdgeSelection(null);
                                      setSelected(issue.nodeId);
                                      setShowInspector(true);
                                      setTab("Flow");
                                    }
                                  }}
                                >
                                  <span>!</span>
                                  <strong>{issue.nodeId ?? "Flow"}</strong>
                                  <span>{issue.message}</span>
                                  <code>{issue.field}</code>
                                </button>
                              ))
                            ) : (
                              <p className="muted padded">
                                표시할 검증 오류가 없습니다. 구성 검증으로 최신 명세를 검사하세요.
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </section>
              {showInspector && !edgeSelection && selectedNode && (
                <NodeInspector
                  node={selectedNode}
                  databases={projectDbs}
                  apply={(n) => {
                    updateNode(n);
                    setMessage("노드 설정을 적용했습니다.");
                  }}
                  close={() => setShowInspector(false)}
                  remove={() => {
                    adopt({
                      ...flow,
                      nodes: flow.nodes.filter((n) => n.id !== selected),
                      edges: flow.edges.filter((e) => e.from !== selected && e.to !== selected),
                    });
                    setSelected("");
                    setShowInspector(false);
                  }}
                />
              )}
              {showInspector &&
                edgeSelection &&
                flow.edges.some(
                  (e) =>
                    e.from === edgeSelection.from &&
                    e.to === edgeSelection.to &&
                    e.port === edgeSelection.port,
                ) && (
                  <EdgeInspector
                    edge={edgeSelection}
                    flow={flow}
                    close={() => setShowInspector(false)}
                    apply={(port) => {
                      const same = (edge: Flow["edges"][number]) =>
                        edge.from === edgeSelection.from &&
                        edge.to === edgeSelection.to &&
                        edge.port === edgeSelection.port;
                      const ui = { ...flow.ui };
                      if (ui.drawioXml) {
                        const xml = new DOMParser().parseFromString(ui.drawioXml, "text/xml");
                        for (const cell of Array.from(xml.querySelectorAll('mxCell[edge="1"]'))) {
                          if (
                            cell.getAttribute("source") === edgeSelection.from &&
                            cell.getAttribute("target") === edgeSelection.to &&
                            (cell.getAttribute("value")?.trim() || "success") === edgeSelection.port
                          )
                            cell.setAttribute("value", port);
                        }
                        ui.drawioXml = new XMLSerializer().serializeToString(xml);
                      }
                      adopt({
                        ...flow,
                        ui,
                        edges: flow.edges.map((edge) => (same(edge) ? { ...edge, port } : edge)),
                      });
                      setEdgeSelection({ ...edgeSelection, port });
                      setMessage("연결선 실행 경로를 적용했습니다.");
                    }}
                  />
                )}
            </>
          ) : (
            <div className="welcome">
              <div className="welcome-icon">
                f<span>•</span>
              </div>
              <span className="eyebrow">DESIGN. CONNECT. RUN.</span>
              <h1>Your APIs, connected.</h1>
              <p>
                DB부터 프로젝트, 업무, 프로세스까지.
                <br />
                draw.io로 설계하고 Python 서버로 실행하세요.
              </p>
              <div className="welcome-steps">
                <span>
                  01 <b>DB 선택</b>
                </span>
                <i>→</i>
                <span>
                  02 <b>프로젝트</b>
                </span>
                <i>→</i>
                <span>
                  03 <b>업무 단위</b>
                </span>
                <i>→</i>
                <span>
                  04 <b>프로세스 ID</b>
                </span>
              </div>
              <p className="welcome-hint">왼쪽에서 DB와 업무 프로세스를 선택하세요.</p>
            </div>
          )}
        </main>
      </div>
      <footer>
        <button
          className={"footer-status " + (busy ? "working" : "")}
          aria-label="작업 로그 열기"
          title={message}
          onClick={() => setShowLogs(true)}
        >
          {busy ? "● 작업 중…" : "● " + message}
        </button>
        <div className="spacer" />
        <span>Flow Spec 1.0</span>
        <span>Local draw.io</span>
        <span>Python 3.12+</span>
      </footer>
      {showLogs && <ActivityLog entries={logs} close={() => setShowLogs(false)} />}
      {dialog && (
        <ManagementDialog
          kind={dialog}
          workspace={workspace}
          databaseId={databaseId}
          project={
            dialogContext
              ? workspace.projects.find((p) => p.id === dialogContext.projectId)
              : project
          }
          unitId={dialogContext?.unitId || process?.unit_id}
          close={() => {
            setDialog(null);
            setDialogContext(null);
          }}
          submit={management}
        />
      )}
      <input
        ref={upload}
        hidden
        type="file"
        accept=".json,.drawio,.xml"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file && flow) {
            await action(async () => {
              if (file.size > 2_000_000) throw new Error("파일은 2MB 이하여야 합니다.");
              const text = await file.text();
              if (text.trim().startsWith("<")) {
                const result = await api("/drawio/convert", { flow, xml: text });
                adopt(result.flow);
                setIssues(result.issues);
              } else {
                const next = JSON.parse(text);
                if (!Array.isArray(next.nodes) || !Array.isArray(next.edges))
                  throw new Error("Flow JSON 구조를 확인하세요.");
                adopt({ ...next, id: process!.process_id, ui: next.ui ?? {} });
              }
              setMessage("Flow를 가져왔습니다. 검증 후 저장하세요.");
            });
          }
          e.target.value = "";
        }}
      />
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
