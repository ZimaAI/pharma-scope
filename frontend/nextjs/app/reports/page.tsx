"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, {
  ApiErrorState,
  EmptyState,
  StatusBadge,
} from "@/components/pharma/PharmaScopeShell";
import { getReports, Report } from "@/components/pharma/pharmaApi";
const labels: Record<string, string> = {
  draft: "草稿",
  in_review: "审核中",
  changes_requested: "需修改",
  approved: "已批准",
  published: "已发布",
  retracted: "已撤回",
};
export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    getReports()
      .then(setReports)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  return (
    <PharmaScopeShell
      title="报告中心"
      description="报告版本、证据核验和审核发布状态。"
      actions={
        <Link className="ps-btn primary" href="/research/new" data-guest-mutation>
          ＋ 新建研究
        </Link>
      }
    >
      <section className="ps-card">
        <div className="ps-filterbar">
          <span className="ps-chip blue">全部报告</span>
          <span className="ps-chip">当前工作区</span>
          <span className="ps-subtle" style={{ marginLeft: "auto" }}>
            版本发布不可变
          </span>
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
        ) : reports.length === 0 ? (
          <EmptyState
            title="还没有报告"
            detail="完成一个研究任务后，报告草稿会出现在这里。"
            action={
              <Link className="ps-btn primary" href="/research/new" data-guest-mutation>
                开始研究
              </Link>
            }
          />
        ) : (
          <div className="ps-table-wrap">
            <table className="ps-table">
              <thead>
                <tr>
                  <th>报告</th>
                  <th>状态</th>
                  <th>当前版本</th>
                  <th>更新时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr key={report.id}>
                    <td>
                      <strong>
                        <Link href={`/reports/detail/?id=${encodeURIComponent(report.id)}`}>
                          {report.title}
                        </Link>
                      </strong>
                      <small>{report.id}</small>
                    </td>
                    <td>
                      <StatusBadge
                        status={labels[report.state] || report.state}
                        tone={
                          report.state === "published"
                            ? "success"
                            : report.state === "changes_requested"
                              ? "danger"
                              : report.state === "in_review"
                                ? "warning"
                                : "info"
                        }
                      />
                    </td>
                    <td>
                      <span className="ps-subtle">{report.current_version_id || "尚未生成"}</span>
                    </td>
                    <td>
                      <span className="ps-subtle">
                        {new Date(report.updated_at).toLocaleString("zh-CN")}
                      </span>
                    </td>
                    <td>
                      <Link
                        className="ps-text-link"
                        href={`/reports/detail/?id=${encodeURIComponent(report.id)}`}
                      >
                        阅读 →
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
