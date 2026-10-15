import { useEffect, useState } from "react";
import type { Flow } from "./types";

type Edge = Flow["edges"][number];
const ports = [
  ["success", "성공 — 다음 업무로 진행"],
  ["error", "오류 — 오류 처리 경로로 진행"],
  ["true", "참 — 분기 조건을 만족"],
  ["false", "거짓 — 분기 조건을 만족하지 않음"],
] as const;

export default function EdgeInspector({
  edge,
  flow,
  apply,
  close,
}: {
  edge: Edge;
  flow: Flow;
  apply: (port: string) => void;
  close: () => void;
}) {
  const [port, setPort] = useState(edge.port);
  useEffect(() => setPort(edge.port), [edge.from, edge.to, edge.port]);
  const source = flow.nodes.find((node) => node.id === edge.from);
  const target = flow.nodes.find((node) => node.id === edge.to);
  return (
    <aside className="node-inspector edge-inspector">
      <div className="inspector-title">
        <h3>연결선 설정</h3>
        <button className="icon-button" aria-label="연결선 설정 닫기" onClick={close}>
          ×
        </button>
      </div>
      <label>
        시작 노드<strong>{source?.name ?? edge.from}</strong>
        <code>{edge.from}</code>
      </label>
      <label>
        도착 노드<strong>{target?.name ?? edge.to}</strong>
        <code>{edge.to}</code>
      </label>
      <label>
        실행 경로
        <select aria-label="실행 경로" value={port} onChange={(e) => setPort(e.target.value)}>
          {ports.map(([value, description]) => (
            <option key={value} value={value}>
              {value} · {description}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        조건 분기 노드는 true / false, 일반 노드는 success / error를 사용합니다. 지원하지 않는
        경로와 중복 경로는 Flow 검증에서 확인합니다.
      </p>
      <button className="orange" onClick={() => apply(port)}>
        설정 적용
      </button>
    </aside>
  );
}
