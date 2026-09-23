"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, {
  ApiErrorState,
  EmptyState,
  StatusBadge,
} from "@/components/pharma/PharmaScopeShell";
import { Event, getEvents } from "@/components/pharma/pharmaApi";
const labels: Record<string, string> = {
  enrollment_change: "入组目标变化",
  status_change: "状态变化",
  correction: "更正",
  date_change: "日期变化",
  other: "其他",
};
export default function EventsPage() {
  const [category, setCategory] = useState("all");
  const [events, setEvents] = useState<Event[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    getEvents()
      .then(setEvents)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  const filtered = useMemo(
    () =>
      events.filter(
        (event) =>
          (category === "all" || event.category === category) &&
          `${event.title} ${event.record_id}`.toLowerCase().includes(query.toLowerCase())
      ),
    [events, query, category]
  );
  return (
    <PharmaScopeShell
      title="变化追踪"
      description="基于前后观察识别字段变化，保留版本、时间和证据定位。"
      actions={
        <button
          className="ps-btn"
          type="button"
          onClick={() => {
            const url = URL.createObjectURL(
              new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" })
            );
            const link = document.createElement("a");
            link.href = url;
            link.download = "pharmascope-events.json";
            link.click();
            URL.revokeObjectURL(url);
          }}
        >
          导出变化清单
        </button>
      }
    >
      <section className="ps-card">
        <div className="ps-filterbar">
          <input
            className="ps-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索变化标题或记录 ID"
            aria-label="搜索变化"
          />
          <select
            className="ps-input"
            aria-label="变化类型"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="all">全部类型</option>
            <option value="enrollment_change">入组目标变化</option>
            <option value="status_change">状态变化</option>
            <option value="correction">更正</option>
          </select>
          <span className="ps-chip blue">{filtered.length} 条变化</span>
        </div>
        {loading ? (
          <div className="ps-card-body">
            <div className="ps-skeleton-list">
              <i />
              <i />
              <i />
            </div>
          </div>
        ) : error ? (
          <ApiErrorState error={error} onRetry={load} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title="没有可显示的变化"
            detail={query ? "没有记录匹配当前筛选。" : "完成首次同步后，变化会在下一次观察中产生。"}
          />
        ) : (
          <div className="ps-table-wrap">
            <table className="ps-table">
              <thead>
                <tr>
                  <th>变化</th>
                  <th>类型</th>
                  <th>记录</th>
                  <th>观察时间</th>
                  <th>修订</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <strong>{event.title}</strong>
                      <small>字段级差异可在详情中查看</small>
                    </td>
                    <td>
                      <StatusBadge
                        status={labels[event.category] || event.category}
                        tone={
                          event.category === "correction"
                            ? "danger"
                            : event.category === "status_change"
                              ? "warning"
                              : "info"
                        }
                      />
                    </td>
                    <td>
                      <span className="ps-subtle">{event.record_id}</span>
                    </td>
                    <td>
                      <span className="ps-subtle">
                        {new Date(event.updated_at).toLocaleString("zh-CN")}
                      </span>
                    </td>
                    <td>
                      <span className="ps-subtle">{event.latest_revision_id || "—"}</span>
                    </td>
                    <td>
                      <Link
                        className="ps-text-link"
                        href={`/events/detail/?id=${encodeURIComponent(event.id)}`}
                      >
                        查看前后 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </PharmaScopeShell>
  );
}
