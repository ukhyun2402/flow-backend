import React, { useEffect, useRef, useState, forwardRef, useImperativeHandle } from "react";
import type { Flow } from "./types";
import { flowToXml } from "./drawio";

export type DrawioHandle = {
  ready: () => boolean;
  sync: () => Promise<string>;
  undo: () => void;
  redo: () => void;
  fit: () => void;
};
type Props = {
  flow: Flow;
  loadKey: number;
  installed: boolean;
  editorUrl: string;
  onXml: (xml: string) => Promise<void>;
  onError: (text: string) => void;
  onSelect: (id: string) => void;
  onEdgeSelect: (edge: Flow["edges"][number]) => void;
  onCanvasClick: () => void;
};
export default forwardRef<DrawioHandle, Props>(function DrawioEditor(
  { flow, loadKey, installed, editorUrl, onXml, onError, onSelect, onEdgeSelect, onCanvasClick },
  ref,
) {
  const frame = useRef<HTMLIFrameElement>(null),
    current = useRef(flow),
    graph = useRef<any>(null),
    callbacks = useRef({ onXml, onError, onSelect, onEdgeSelect, onCanvasClick }),
    pending = useRef<
      {
        resolve: (xml: string) => void;
        reject: (error: Error) => void;
        timer: ReturnType<typeof setTimeout>;
      }[]
    >([]);
  const [ready, setReady] = useState(false),
    [failed, setFailed] = useState(false);
  const origin = new URL(editorUrl, window.location.href).origin;
  current.current = flow;
  callbacks.current = { onXml, onError, onSelect, onEdgeSelect, onCanvasClick };
  function post(message: Record<string, unknown>) {
    frame.current?.contentWindow?.postMessage(JSON.stringify(message), origin);
  }
  function load(initial = false) {
    const g = graph.current;
    const view =
      !initial && g
        ? {
            scale: g.view.scale,
            scroll: {
              x: g.container.scrollLeft / g.view.scale - g.view.translate.x,
              y: g.container.scrollTop / g.view.scale - g.view.translate.y,
            },
          }
        : initial
          ? { fit: 1 }
          : {};
    post({
      action: "load",
      xml: flowToXml(current.current),
      autosave: 1,
      ...view,
      noExitBtn: 1,
      saveAndExit: 0,
      modified: "Flow",
      exportProtocol: true,
    });
  }
  useImperativeHandle(
    ref,
    () => ({
      ready: () => ready,
      sync: () =>
        new Promise((resolve, reject) => {
          if (!ready) {
            reject(new Error("draw.io 편집기가 아직 준비되지 않았습니다."));
            return;
          }
          const request = {
            resolve,
            reject,
            timer: setTimeout(() => {
              pending.current = pending.current.filter((p) => p !== request);
              reject(new Error("draw.io 동기화 시간이 초과되었습니다."));
            }, 10000),
          };
          pending.current.push(request);
          post({ action: "export", format: "xml" });
        }),
      undo: () => post({ action: "invokeAction", actionName: "undo" }),
      redo: () => post({ action: "invokeAction", actionName: "redo" }),
      fit: () => post({ action: "fit", border: 20, maxScale: 1 }),
    }),
    [ready, origin],
  );
  useEffect(() => {
    const listener = (event: MessageEvent) => {
      if (event.origin !== origin || event.source !== frame.current?.contentWindow) return;
      let data;
      try {
        data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }
      if (data?.event === "configure") {
        post({
          action: "configure",
          config: {
            defaultLibraries: [],
            enableCustomLibraries: false,
            allowCustomFonts: false,
            showStartScreen: false,
            offline: true,
            suppressNewWindows: true,
          },
        });
      }
      if (data?.event === "init") {
        const win = frame.current?.contentWindow as
          | (Window & {
              mxGraph?: { prototype: { fireEvent: (event: any, sender?: unknown) => void } };
            })
          | null;
        if (win) {
          const style = win.document.createElement("style");
          style.textContent =
            ".geMenubarContainer > .geButtonGroup:nth-of-type(-n+2) { display:none !important; }";
          win.document.head.appendChild(style);
          // Bridge native clicks from the pinned, same-origin local editor.
          const prototype = win.mxGraph?.prototype;
          if (prototype) {
            const fireEvent = prototype.fireEvent;
            prototype.fireEvent = function (event, sender) {
              if ((this as any).container === win.document.querySelector(".geDiagramContainer"))
                graph.current = this;
              fireEvent.call(this, event, sender);
              if (event.getName() === "click") {
                const cell = event.getProperty("cell");
                if (!cell) callbacks.current.onCanvasClick();
                if (cell?.vertex && current.current.nodes.some((node) => node.id === cell.id))
                  callbacks.current.onSelect(cell.id);
                if (cell?.edge && cell.source && cell.target) {
                  const edge = {
                    from: cell.source.id,
                    to: cell.target.id,
                    port:
                      typeof cell.value === "string" ? cell.value.trim() || "success" : "success",
                  };
                  callbacks.current.onEdgeSelect(edge);
                }
              }
            };
          }
        }
        setReady(true);
        setFailed(false);
        load(true);
      }
      if (data?.event === "autosave" || data?.event === "save") {
        if (typeof data.xml === "string")
          void callbacks.current.onXml(data.xml).catch((e) => callbacks.current.onError(e.message));
      }
      if (data?.event === "export" && typeof data.xml === "string") {
        for (const request of pending.current) {
          clearTimeout(request.timer);
          request.resolve(data.xml);
        }
        pending.current = [];
      }
      if (data?.error) callbacks.current.onError("draw.io: " + String(data.error));
    };
    window.addEventListener("message", listener);
    const timer = setTimeout(() => setFailed(true), 20000);
    return () => {
      window.removeEventListener("message", listener);
      clearTimeout(timer);
      for (const p of pending.current) {
        clearTimeout(p.timer);
        p.reject(new Error("편집기가 닫혔습니다."));
      }
      pending.current = [];
    };
  }, [origin, editorUrl]);
  useEffect(() => {
    if (ready) load();
  }, [loadKey]);
  if (!installed)
    return (
      <div className="editor-empty">
        <div className="drawio-mark">▧</div>
        <h3>로컬 draw.io 편집기를 설치하세요</h3>
        <p>다이어그램을 외부 서버로 전송하지 않고 편집할 수 있습니다.</p>
        <code>.venv\Scripts\python.exe scripts/install_drawio.py</code>
        <p>설치 후 서버를 다시 실행하세요.</p>
      </div>
    );
  return (
    <div className="drawio-editor">
      <iframe
        ref={frame}
        title="draw.io 프로세스 편집기"
        src={`${editorUrl}?embed=1&proto=json&configure=1&ui=min&spin=1&noExitBtn=1&noSaveBtn=1&saveAndExit=0&lang=ko&dark=1&offline=1&local=1&sidebar=0&format=0&windows=0&shape-picker=0&pages=0&suppressNewWindows=1`}
        sandbox="allow-scripts allow-same-origin allow-downloads"
      />
      {!ready && (
        <div className="editor-loading">
          <span className="spinner" />
          {failed
            ? "draw.io 연결을 확인하세요. 서버 로그 또는 새로고침을 확인하세요."
            : "로컬 draw.io 편집기 준비 중…"}
        </div>
      )}
    </div>
  );
});
