"use client";
import { useCallback, useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getEvent, Event, IS_REPLAY_MODE, workspaceFetch } from "@/components/pharma/pharmaApi";
import EvidenceDrawer from "@/components/pharma/EvidenceDrawer";
export default function EventDetailPage() {
  const [revisions, setRevisions] = useState<any[]>([]);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const closeEvidence = useCallback(() => setEvidenceId(null), []);
  const [event, setEvent] = useState<Event | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少变化 ID"));
      return;
    }
    Promise.all([
      getEvent(id),
      workspaceFetch<{ items: any[] }>(`/events/${encodeURIComponent(id)}/revisions`),
    ])
      .then(([value, rows]) => {
        setEvent(value);
        setRevisions(rows.items);
      })
      .catch(setError);
  }, []);
  return (
    <PharmaScopeShell title="变化详情" description="对照两个观察与对应快照，查看字段级变化和证据。">
      {error ? (
        <ApiErrorState error={error} />
      ) : !event ? (
        <section className="ps-card">
          <div className="ps-card-body">加载中…</div>
        </section>
      ) : (
        <div className="ps-grid-2">
          <section className="ps-card">
            <div className="ps-card-head">
              <div>
                <h2>{event.title}</h2>
                <small>
                  {event.id} · {event.record_id}
                </small>
              </div>
              <StatusBadge
                status={IS_REPLAY_MODE ? "REPLAY / DEMO" : "可核验"}
                tone={IS_REPLAY_MODE ? "info" : "success"}
              />
            </div>
            <div className="ps-card-body">
              <div className="ps-callout">
                变化描述仅针对登记字段，不推断疗效、安全性或监管结论。
              </div>
              <h3 style={{ marginTop: 20 }}>字段变化</h3>
              {revisions.map((revision) => (
                <div key={revision.id}>
                  <h4>
                    修订 {revision.revision_no} · {revision.observed_at}
                  </h4>
                  {revision.changes?.map((change: any, index: number) => (
                    <p key={index}>
                      <code>{change.path}</code>：{JSON.stringify(change.before)} →{" "}
                      {JSON.stringify(change.after)}
                    </p>
                  ))}
                </div>
              ))}
              <h3 style={{ marginTop: 22 }}>修订说明</h3>
              <p className="ps-subtle">最新修订：{event.latest_revision_id || "—"}。</p>
            </div>
          </section>
          <section className="ps-card">
            <div className="ps-card-head">
              <h2>证据摘要</h2>
            </div>
            <div className="ps-card-body">
              <p className="ps-subtle">打开证据抽屉查看关联快照与字段路径。</p>
              {revisions
                .flatMap((revision) => revision.evidence_ids || [])
                .map((id: string) => (
                  <button key={id} className="ps-btn" onClick={() => setEvidenceId(id)}>
                    查看证据 {id.slice(0, 8)}
                  </button>
                ))}
            </div>
          </section>
        </div>
      )}
      {evidenceId && <EvidenceDrawer id={evidenceId} onClose={closeEvidence} />}
    </PharmaScopeShell>
  );
}
