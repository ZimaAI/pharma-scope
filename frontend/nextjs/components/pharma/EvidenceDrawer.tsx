"use client";
import { useEffect, useRef, useState } from "react";
import { ApiErrorState } from "./PharmaScopeShell";
import { workspaceFetch } from "./pharmaApi";
export default function EvidenceDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [evidence, setEvidence] = useState<any>(null);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [error, setError] = useState<unknown>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement;
    closeRef.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    workspaceFetch<any>(`/evidence/${encodeURIComponent(id)}`)
      .then(async (value) => {
        setEvidence(value);
        setSnapshot(await workspaceFetch(`/snapshots/${encodeURIComponent(value.snapshot_id)}`));
      })
      .catch(setError);
    return () => {
      document.removeEventListener("keydown", key);
      prior?.focus();
    };
  }, [id, onClose]);
  return (
    <div className="ps-evidence-overlay" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label="来源证据"
        className="ps-evidence-drawer"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="ps-card-head">
          <h2>来源证据</h2>
          <button ref={closeRef} className="ps-btn" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="ps-card-body">
          {error ? (
            <ApiErrorState error={error} />
          ) : !evidence ? (
            <p>加载证据…</p>
          ) : (
            <>
              <dl className="ps-kv">
                <dt>证据 ID</dt>
                <dd>{evidence.id}</dd>
                <dt>字段路径</dt>
                <dd>{evidence.locator?.path || "—"}</dd>
                <dt>原文</dt>
                <dd>{evidence.quoted_text}</dd>
                <dt>片段哈希</dt>
                <dd>{evidence.snippet_hash}</dd>
                <dt>快照哈希</dt>
                <dd>{snapshot?.content_hash || snapshot?.raw_hash || "—"}</dd>
                <dt>抓取时间</dt>
                <dd>{snapshot?.fetched_at || snapshot?.first_observed_at || "—"}</dd>
                <dt>来源更新时间</dt>
                <dd>
                  {snapshot?.source_updated_at || snapshot?.source_updated?.value || "来源未提供"}
                </dd>
              </dl>
              <details>
                <summary>查看完整快照</summary>
                <pre className="ps-json">{JSON.stringify(snapshot, null, 2)}</pre>
              </details>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
