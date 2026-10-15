import React, { useState } from "react";
import type { Workspace, Database, Project, Json } from "./types";
export type DialogKind = "database" | "project" | "unit" | "process" | "bindings";
type Props = {
  kind: DialogKind;
  workspace: Workspace;
  databaseId: string;
  project?: Project;
  unitId?: string;
  close: () => void;
  submit: (data: Json) => Promise<void>;
};
const blank: Database = {
  id: "",
  name: "",
  vendor: "oracle",
  host: "",
  port: 1521,
  database: "",
  username: "",
  passwordSecretRef: "",
  environment: "development",
  readonly: true,
  rollbackSafetyVerified: false,
  tls: true,
  dsn: "",
  schemaName: "",
};
export default function ManagementDialog({
  kind,
  workspace,
  databaseId,
  project,
  unitId,
  close,
  submit,
}: Props) {
  const [db, setDb] = useState<Database>(blank),
    [name, setName] = useState(""),
    [code, setCode] = useState(""),
    [projectId, setProjectId] = useState(project?.id ?? workspace.projects[0]?.id ?? ""),
    [selectedUnit, setUnit] = useState(unitId ?? project?.units[0]?.id ?? ""),
    [dbs, setDbs] = useState<string[]>(
      kind === "bindings" ? (project?.databaseIds ?? []) : [databaseId],
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const selectedProject = workspace.projects.find((p) => p.id === projectId);
  const titles = {
    database: "데이터베이스 연결 관리",
    project: "프로젝트 만들기",
    unit: "업무 단위 만들기",
    process: "프로세스 만들기",
    bindings: "프로젝트 DB 연결",
  };
  function toggle(id: string) {
    setDbs((values) => (values.includes(id) ? values.filter((v) => v !== id) : [...values, id]));
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { configured, secretAvailable, ...config } = db;
      await submit(
        kind === "database"
          ? config
          : kind === "project"
            ? { code, name, primaryDatabaseId: databaseId, databaseIds: dbs }
            : kind === "bindings"
              ? { databaseIds: dbs }
              : kind === "unit"
                ? { code, name, projectId }
                : { code, name, unitId: selectedUnit },
      );
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <form className="modal" onSubmit={save}>
        <div className="modal-heading">
          <div>
            <span className="eyebrow">WORKSPACE ORGANIZATION</span>
            <h2>{titles[kind]}</h2>
          </div>
          <button type="button" className="icon-button" aria-label="닫기" onClick={close}>
            ×
          </button>
        </div>
        {kind === "database" ? (
          <>
            <label>
              등록된 연결
              <select
                aria-label="등록된 연결"
                value={db.id}
                onChange={(e) =>
                  setDb(workspace.databases.find((d) => d.id === e.target.value) ?? blank)
                }
              >
                <option value="">새 DB 연결</option>
                {workspace.databases.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.vendor}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-grid">
              <label>
                DB ID
                <input
                  required
                  pattern="[A-Za-z0-9_-]+"
                  value={db.id}
                  onChange={(e) => setDb({ ...db, id: e.target.value })}
                />
              </label>
              <label>
                표시 이름
                <input
                  required
                  value={db.name}
                  onChange={(e) => setDb({ ...db, name: e.target.value })}
                />
              </label>
              <label>
                DB 종류
                <select
                  value={db.vendor}
                  onChange={(e) =>
                    setDb({
                      ...db,
                      vendor: e.target.value as Database["vendor"],
                      port: { oracle: 1521, mysql: 3306, tibero: 8629 }[
                        e.target.value as Database["vendor"]
                      ],
                    })
                  }
                >
                  <option value="oracle">Oracle</option>
                  <option value="mysql">MySQL</option>
                  <option value="tibero">Tibero · ODBC</option>
                </select>
              </label>
              <label>
                환경
                <select
                  value={db.environment}
                  onChange={(e) => setDb({ ...db, environment: e.target.value })}
                >
                  <option value="development">Development</option>
                  <option value="test">Test</option>
                  <option value="production">Production</option>
                </select>
              </label>
              <label>
                호스트
                <input value={db.host} onChange={(e) => setDb({ ...db, host: e.target.value })} />
              </label>
              <label>
                포트
                <input
                  type="number"
                  value={db.port}
                  min="1"
                  max="65535"
                  onChange={(e) => setDb({ ...db, port: Number(e.target.value) })}
                />
              </label>
              <label>
                DB / Service name
                <input
                  value={db.database}
                  onChange={(e) => setDb({ ...db, database: e.target.value })}
                />
              </label>
              <label>
                사용자
                <input
                  value={db.username}
                  onChange={(e) => setDb({ ...db, username: e.target.value })}
                />
              </label>
            </div>
            <label>
              비밀번호 환경 변수명
              <input
                placeholder="MAIN_DB_PASSWORD"
                value={db.passwordSecretRef}
                onChange={(e) => setDb({ ...db, passwordSecretRef: e.target.value })}
              />
              <small>비밀번호 값은 서버 환경 변수에 설정합니다.</small>
            </label>
            {db.vendor === "tibero" && (
              <label>
                ODBC DSN
                <input value={db.dsn} onChange={(e) => setDb({ ...db, dsn: e.target.value })} />
              </label>
            )}
            <div className="checks">
              <label>
                <input
                  type="checkbox"
                  checked={db.readonly}
                  onChange={(e) => setDb({ ...db, readonly: e.target.checked })}
                />
                읽기 전용
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={db.tls}
                  onChange={(e) => setDb({ ...db, tls: e.target.checked })}
                />
                TLS 사용 (ODBC는 DSN에서 설정)
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={db.rollbackSafetyVerified}
                  onChange={(e) => setDb({ ...db, rollbackSafetyVerified: e.target.checked })}
                />
                테이블·트리거의 롤백 안전성 확인
              </label>
            </div>
          </>
        ) : (
          <>
            {(kind === "unit" || kind === "process") && (
              <label>
                프로젝트
                <select
                  value={projectId}
                  onChange={(e) => {
                    setProjectId(e.target.value);
                    setUnit(
                      workspace.projects.find((p) => p.id === e.target.value)?.units[0]?.id ?? "",
                    );
                  }}
                >
                  {workspace.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {kind === "process" && (
              <label>
                업무 단위
                <select value={selectedUnit} onChange={(e) => setUnit(e.target.value)} required>
                  <option value="">업무 단위를 선택하세요</option>
                  {selectedProject?.units.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} · {u.code}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {kind !== "bindings" && (
              <>
                <label>
                  {kind === "process" ? "프로세스 ID" : "코드"}
                  <input
                    required
                    pattern="[A-Za-z0-9_-]{1,80}"
                    placeholder={kind === "process" ? "USR-002" : "PROJECT_CODE"}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </label>
                <label>
                  이름
                  <input required value={name} onChange={(e) => setName(e.target.value)} />
                </label>
              </>
            )}
            {(kind === "project" || kind === "bindings") && (
              <>
                <p className="muted">
                  한 프로젝트에서 여러 DB를 사용할 수 있습니다. 각 SQL 노드에서 실행 DB를
                  선택합니다.
                </p>
                <div className="db-checks">
                  {workspace.databases.map((d) => (
                    <label key={d.id}>
                      <input
                        type="checkbox"
                        checked={dbs.includes(d.id)}
                        disabled={
                          d.id === (kind === "project" ? databaseId : project?.primary_db_id)
                        }
                        onChange={() => toggle(d.id)}
                      />
                      <span className={"vendor-dot " + d.vendor} />
                      <span>
                        {d.name}
                        <small>
                          {d.vendor.toUpperCase()} · {d.id}
                        </small>
                      </span>
                      {d.id === (kind === "project" ? databaseId : project?.primary_db_id) && (
                        <em>기준 DB</em>
                      )}
                    </label>
                  ))}
                </div>
              </>
            )}
          </>
        )}
        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button type="button" onClick={close}>
            취소
          </button>
          <button className="orange" disabled={busy || (kind === "process" && !selectedUnit)}>
            {busy ? "저장 중…" : "저장"}
          </button>
        </div>
      </form>
    </div>
  );
}
