import React, { useEffect, useState } from "react";
import type { FlowNode, Database } from "./types";
import { nodeKinds, pretty } from "./types";
type Props = {
  node: FlowNode;
  databases: Database[];
  apply: (node: FlowNode) => void;
  close: () => void;
  remove: () => void;
};
export default function NodeInspector({ node, databases, apply, close, remove }: Props) {
  const [name, setName] = useState(node.name),
    [text, setText] = useState(pretty(node.config)),
    [error, setError] = useState("");
  useEffect(() => {
    setName(node.name);
    setText(pretty(node.config));
    setError("");
  }, [node.id, node.config]);
  function patch(key: string, value: unknown) {
    try {
      setText(pretty({ ...JSON.parse(text), [key]: value }));
    } catch {
      setError("JSON 형식을 먼저 확인하세요.");
    }
  }
  let cfg: Record<string, any> = {};
  try {
    cfg = JSON.parse(text);
  } catch {}
  function jsonField(key: string, label: string, fallback: unknown = {}) {
    return (
      <label key={node.id + key}>
        {label}
        <textarea
          key={node.id + key + pretty(node.config[key])}
          className="code-input"
          defaultValue={pretty(cfg[key] ?? fallback)}
          spellCheck={false}
          onBlur={(e) => {
            try {
              patch(key, JSON.parse(e.target.value));
              setError("");
            } catch {
              setError(label + "의 JSON 형식을 확인하세요.");
            }
          }}
        />
      </label>
    );
  }
  return (
    <aside className="node-inspector">
      <div className="inspector-title">
        <h3>노드 설정</h3>
        <button className="icon-button" aria-label="노드 설정 닫기" onClick={close}>
          ×
        </button>
      </div>
      <span className="type-badge">
        {nodeKinds.find((k) => k[0] === node.type)?.[1]} · {node.type}
      </span>
      <label>
        표시 이름
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="node-id">
        ID <code>{node.id}</code>
      </div>
      {(node.type.startsWith("db.") || node.type === "transaction.begin") && (
        <label>
          실행 DB
          <select
            value={cfg.databaseRef ?? ""}
            onChange={(e) => patch("databaseRef", e.target.value)}
          >
            <option value="">DB 선택</option>
            {databases.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {d.vendor}
              </option>
            ))}
          </select>
        </label>
      )}
      {node.type === "response.http" && (
        <label>
          상태 코드
          <input
            type="number"
            value={cfg.status ?? 200}
            onChange={(e) => patch("status", Number(e.target.value))}
          />
        </label>
      )}
      {node.type === "trigger.http" && (
        <label>
          API 경로
          <input value={cfg.path ?? ""} onChange={(e) => patch("path", e.target.value)} />
        </label>
      )}
      {node.type.startsWith("db.") && (
        <>
          <label>
            SQL
            <textarea
              className="code-input"
              value={cfg.sql ?? ""}
              onChange={(e) => patch("sql", e.target.value)}
              spellCheck={false}
            />
          </label>
          {jsonField("parameters", "SQL 바인딩 값 · JSON")}
          {node.type === "db.query" && (
            <label>
              조회 결과
              <select
                value={cfg.resultMode ?? "many"}
                onChange={(e) => patch("resultMode", e.target.value)}
              >
                <option value="many">여러 행</option>
                <option value="zeroOrOne">0개 또는 1개 행</option>
              </select>
            </label>
          )}
        </>
      )}
      {node.type === "branch" && jsonField("condition", "분기 조건 · 표현식", true)}
      {node.type === "transform" && jsonField("mapping", "변환할 필드 · 표현식")}
      {node.type === "validate" && (
        <>
          {jsonField("schema", "검증 스키마")}
          {jsonField("value", "검증 대상 · 표현식", { ref: "input" })}
        </>
      )}
      {node.type === "response.http" && jsonField("body", "출력값 · 표현식")}
      {node.type === "trigger.http" && jsonField("input", "외부 요청 입력 매핑")}
      {node.type === "http.call" && (
        <>
          <label>
            외부 서비스 ID
            <input
              value={cfg.serviceRef ?? ""}
              onChange={(e) => patch("serviceRef", e.target.value)}
            />
          </label>
          <label>
            호출 경로
            <input value={cfg.path ?? ""} onChange={(e) => patch("path", e.target.value)} />
          </label>
          {jsonField("body", "전달할 값 · 표현식")}
        </>
      )}
      {node.type === "transaction.begin" && (
        <label>
          격리 수준
          <select
            value={cfg.isolation ?? "READ_COMMITTED"}
            onChange={(e) => patch("isolation", e.target.value)}
          >
            {["READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
      )}
      {node.type === "error.raise" && (
        <>
          <label>
            업무 오류 코드
            <input value={cfg.code ?? ""} onChange={(e) => patch("code", e.target.value)} />
          </label>
          <label>
            업무 오류 메시지
            <input value={cfg.message ?? ""} onChange={(e) => patch("message", e.target.value)} />
          </label>
          <label>
            상태 코드
            <input
              type="number"
              value={cfg.status ?? 400}
              onChange={(e) => patch("status", Number(e.target.value))}
            />
          </label>
        </>
      )}
      {["transaction.commit", "transaction.rollback"].includes(node.type) && (
        <p className="muted">
          앞선 트랜잭션 시작 노드의 DB 연결을 사용합니다. 추가 설정은 필요하지 않습니다.
        </p>
      )}
      <details>
        <summary>전체 설정 · 고급</summary>
        <label className="grow-label">
          노드 계약 · JSON
          <textarea
            className="code-input"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
      </details>
      {error && <p className="error-text">{error}</p>}
      <button
        className="orange"
        disabled={!!error}
        onClick={() => {
          try {
            const config = JSON.parse(text);
            if (!config || Array.isArray(config) || typeof config !== "object") throw new Error();
            apply({ ...node, name, config });
          } catch {
            setError("유효한 설정 JSON 객체를 입력하세요.");
          }
        }}
      >
        설정 적용
      </button>
      <button className="danger-subtle" onClick={remove}>
        노드 삭제
      </button>
    </aside>
  );
}
