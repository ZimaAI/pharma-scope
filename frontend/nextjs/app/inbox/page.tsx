"use client";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getInbox, InboxItem, markInboxRead } from "@/components/pharma/pharmaApi";
export default function InboxPage() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = () => {
    setLoading(true);
    setError(null);
    getInbox()
      .then(setItems)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  async function markAllRead() {
    setBusy(true);
    try {
      const unread = items.filter((item) => !item.read_at);
      const updates = await Promise.all(unread.map((item) => markInboxRead(item.id)));
      const now = new Date().toISOString();
      setItems((current) =>
        current.map((item) =>
          unread.some((next) => next.id === item.id)
            ? { ...item, read_at: updates.find((next) => next.id === item.id)?.read_at || now }
            : item
        )
      );
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PharmaScopeShell title="通知" description="研究完成、审核状态和来源变化提示。">
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>收件箱</h2>
          <button
            className="ps-btn tiny"
            disabled={busy || !items.some((item) => !item.read_at)}
            onClick={markAllRead}
          >
            全部标为已读
          </button>
        </div>
        {loading ? (
          <div className="ps-card-body">
            <div className="ps-skeleton-list">
              <i />
              <i />
            </div>
          </div>
        ) : error ? (
          <ApiErrorState error={error} onRetry={load} />
        ) : (
          <div className="ps-card-body">
            {items.length === 0 ? (
              <p className="ps-subtle">暂无通知。</p>
            ) : (
              items.map((item) => (
                <div className="ps-event-row" key={item.id}>
                  <div className="ps-event-marker">{item.read_at ? "✓" : "!"}</div>
                  <div style={{ flex: 1 }}>
                    <h3>{item.title || `报告投递 · ${item.report_id || item.id}`}</h3>
                    <p>{item.body || `${item.channel || "in_app"} · ${item.state || "已送达"}`}</p>
                    <small>
                      {new Date(item.created_at).toLocaleString("zh-CN")} · {item.id}
                    </small>
                  </div>
                  <StatusBadge
                    status={item.read_at ? "已读" : "未读"}
                    tone={item.read_at ? "success" : "info"}
                  />
                </div>
              ))
            )}
          </div>
        )}
      </section>
    </PharmaScopeShell>
  );
}
