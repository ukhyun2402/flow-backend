import { useEffect, useRef, useState } from "react";

export type LogEntry = { at: string; level: string; message: string; details?: unknown };
export default function ActivityLog({
  entries,
  close,
}: {
  entries: LogEntry[];
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const fullText = entries
    .map(
      (entry) =>
        `[${entry.at}] ${entry.level} ${entry.message}${entry.details === undefined ? "" : "\n" + JSON.stringify(entry.details, null, 2)}`,
    )
    .join("\n\n");
  return (
    <dialog className="activity-log" ref={dialog} onClose={close} aria-labelledby="log-title">
      <div className="inspector-title">
        <h2 id="log-title">작업 로그 전체</h2>
        <button aria-label="작업 로그 닫기" onClick={() => dialog.current?.close()}>
          ×
        </button>
      </div>
      <p className="muted">
        이 화면을 연 이후의 작업 상태, API 응답 상태, 검증 결과와 실행 추적입니다. 서버 콘솔의 전체
        출력은 포함하지 않습니다. 새로고침하면 초기화됩니다.
      </p>
      <div className="activity-log-actions">
        <span>{entries.length}개 기록</span>
        <button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(fullText);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "복사 완료" : "전체 로그 복사"}
        </button>
      </div>
      <div className="activity-log-entries">
        <pre tabIndex={0}>{fullText || "기록된 작업이 없습니다."}</pre>
      </div>
    </dialog>
  );
}
