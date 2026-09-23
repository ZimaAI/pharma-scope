"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, {
  ApiErrorState,
  EmptyState,
  StatusBadge,
} from "@/components/pharma/PharmaScopeShell";
import { Trial, getTrials } from "@/components/pharma/pharmaApi";
export default function TrialsPage() {
  const [trials, setTrials] = useState<Trial[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    getTrials()
      .then(setTrials)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  const filtered = useMemo(
    () =>
      trials.filter(
        (t) =>
          (!query ||
            `${t.external_id} ${t.current_projection?.brief_title || ""}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (status === "all" || t.current_projection?.overall_status === status)
      ),
    [trials, query, status]
  );
  return (
    <PharmaScopeShell title="临床试验" description="查看工作区内登记记录的当前投影与来源状态。">
      <section className="ps-card">
        <div className="ps-filterbar">
          <input
            className="ps-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索试验编号或标题"
            aria-label="搜索临床试验"
          />
          <select
            className="ps-input"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="按登记状态筛选"
          >
            <option value="all">全部状态</option>
            <option value="RECRUITING">RECRUITING</option>
            <option value="ACTIVE_NOT_RECRUITING">ACTIVE_NOT_RECRUITING</option>
            <option value="COMPLETED">COMPLETED</option>
          </select>
          <span className="ps-chip blue">{filtered.length} 条记录</span>
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
        ) : filtered.length === 0 ? (
          <EmptyState
            title="没有匹配的试验"
            detail={query ? "调整筛选后重试。" : "当前工作区尚未同步试验记录。"}
          />
        ) : (
          <div className="ps-table-wrap">
            <table className="ps-table">
              <thead>
                <tr>
                  <th>试验</th>
                  <th>状态</th>
                  <th>阶段</th>
                  <th>目标入组</th>
                  <th>来源 / 更新</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((trial) => {
                  const p = trial.current_projection || {};
                  const statusTone =
                    p.overall_status === "COMPLETED"
                      ? "success"
                      : p.overall_status === "RECRUITING"
                        ? "info"
                        : "warning";
                  return (
                    <tr key={trial.id}>
                      <td>
                        <strong>
                          <Link href={`/trials/detail/?id=${encodeURIComponent(trial.id)}`}>
                            {trial.external_id}
                          </Link>
                        </strong>
                        <small>{p.brief_title || "暂无标题"}</small>
                      </td>
                      <td>
                        <StatusBadge status={p.overall_status || "未知"} tone={statusTone as any} />
                      </td>
                      <td>
                        <span className="ps-subtle">{p.phase?.join(", ") || "未知"}</span>
                      </td>
                      <td>
                        <span className="ps-subtle">{p.enrollment ?? "未知"}</span>
                      </td>
                      <td>
                        <span className="ps-subtle">
                          {trial.source}
                          <br />
                          {new Date(trial.updated_at).toLocaleDateString("zh-CN")}
                        </span>
                      </td>
                      <td>
                        <Link
                          className="ps-text-link"
                          href={`/trials/detail/?id=${encodeURIComponent(trial.id)}`}
                        >
                          详情 →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="ps-table-foot">
              <span>状态显示来源原值</span>
              <span>横向滚动查看完整字段</span>
            </div>
          </div>
        )}
      </section>
    </PharmaScopeShell>
  );
}
