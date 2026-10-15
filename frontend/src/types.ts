export type Json = Record<string, any>;
export type FlowNode = { id: string; type: string; name: string; config: Json };
export type Flow = {
  specVersion: string;
  id: string;
  revision: number;
  name: string;
  inputSchema: Json;
  outputSchema: Json;
  resources: { databases: string[]; services: string[] };
  nodes: FlowNode[];
  edges: { from: string; port: string; to: string }[];
  settings: Json;
  ui: Json;
};
export type Database = {
  id: string;
  name: string;
  vendor: "mysql" | "oracle" | "tibero";
  host: string;
  port: number;
  database: string;
  username: string;
  passwordSecretRef: string;
  environment: string;
  readonly: boolean;
  rollbackSafetyVerified: boolean;
  tls: boolean;
  dsn: string;
  schemaName: string;
  configured?: boolean;
  secretAvailable?: boolean;
};
export type ProcessSummary = {
  id: string;
  process_id: string;
  name: string;
  latest_revision: number;
  draft_version: number;
  method?: string;
};
export type Unit = {
  id: string;
  name: string;
  code: string;
  project_id: string;
  processes: ProcessSummary[];
};
export type Project = {
  id: string;
  name: string;
  code: string;
  primary_db_id: string;
  databaseIds: string[];
  units: Unit[];
};
export type Process = ProcessSummary & {
  unit_id: string;
  unit_name: string;
  project_id: string;
  flow: Flow;
  project: Project;
  versions: { revision: number; hash: string; created_at: string }[];
};
export type Workspace = {
  databases: Database[];
  projects: Project[];
  drawioInstalled: boolean;
  editorUrl: string;
  version: string;
};
export const nodeKinds = [
  ["trigger.http", "HTTP 진입", "↪"],
  ["validate", "입력 검증", "✓"],
  ["transform", "데이터 변환", "ƒ"],
  ["branch", "조건 분기", "◇"],
  ["db.query", "SQL 조회", "▤"],
  ["db.command", "SQL 변경", "✎"],
  ["http.call", "외부 API 호출", "⬡"],
  ["transaction.begin", "트랜잭션 시작", "["],
  ["transaction.commit", "커밋", "]✓"],
  ["transaction.rollback", "롤백", "]↶"],
  ["error.raise", "업무 오류", "!"],
  ["response.http", "HTTP 응답", "↗"],
] as const;
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export const defaults: Record<string, Json> = {
  "trigger.http": { method: "POST", path: "/endpoint", input: {} },
  validate: { schema: { type: "object" } },
  transform: { mapping: {} },
  branch: { condition: { op: "eq", args: [1, 1] } },
  "db.query": {
    databaseRef: "main",
    sql: "SELECT id FROM users WHERE id = :id",
    parameters: { id: { ref: "input.id" } },
    resultMode: "zeroOrOne",
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
  "error.raise": { code: "BUSINESS_ERROR", status: 400, message: "업무 처리 오류" },
  "response.http": { status: 200, body: { message: "ok" } },
};
