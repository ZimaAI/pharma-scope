"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PharmaScopeShell, {
  ApiErrorState,
  MetricCard,
  StatusBadge,
} from "@/components/pharma/PharmaScopeShell";
import {
  Dashboard,
  Event,
  getDashboard,
  getEvents,
  getResearchRuns,
  ResearchRun,
} from "@/components/pharma/pharmaApi";

const eventIcon: Record<string, string> = {
  enrollment_change: "↕",
  status_change: "⇄",
  correction: "⌁",
  date_change: "◷",
};
const eventTone: Record<string, "info" | "warning" | "danger"> = {
  enrollment_change: "info",
  status_change: "warning",
  correction: "danger",
};
const sourceLabels: Record<string, string> = {
  clinicaltrials_gov: "ClinicalTrials.gov",
  ctgov: "ClinicalTrials.gov",
  pubmed: "PubMed",
  manual: "人工导入",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

export default function DashboardPage() {
  const [question, setQuestion] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([getDashboard(), getEvents(), getResearchRuns()])
      .then(([summary, recent, currentRuns]) => {
        setDashboard(summary);
        setEvents(recent);
        setRuns(currentRuns);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);

  return (
    <PharmaScopeShell title="工作台" description="在一个工作区内查看研发对象、登记变化与证据覆盖。">
      <section className="ps-card ps-hero-card">
        <div>
          <span className="ps-kicker">RESEARCH INTELLIGENCE WORKSPACE</span>
          <h2><span className="ps-normal-only">今天想了解什么？</span><span className="ps-guest-only">浏览演示研究资料</span></h2>
          <p>从药物、临床试验和文献开始，建立可追溯的变化记录与研究报告。</p>
          <div className="ps-hero-search" data-guest-mutation>
            <span aria-hidden>⌕</span>
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="输入需要核对的登记变化问题"
              aria-label="输入研究问题"
            />
            <Link
              href={`/research/new/?question=${encodeURIComponent(question)}`}
              className="ps-btn primary"
            >
              新建研究 →
            </Link>
          </div>
          <small className="ps-hero-foot">
            <span>◷ 资料截止由服务端返回</span>
            <span>▣ 仅搜索当前工作区</span>
            <span>⚑ 结论绑定证据</span>
          </small>
        </div>
        <div className="ps-hero-mark" aria-hidden>
          ✦
        </div>
      </section>
      <div className="ps-metric-grid" style={{ marginTop: 20 }}>
        <MetricCard
          label="我的关注"
          value={loading ? "—" : (dashboard?.watched_drugs ?? "—")}
          detail="启用订阅中的药物"
          icon="◉"
        />
        <MetricCard
          label="近 7 天观察变化"
          value={loading ? "—" : (dashboard?.events_last_7_days ?? "—")}
          detail="排除首次基线"
          icon="↗"
          tone="green"
        />
        <MetricCard
          label="待审核报告"
          value={loading ? "—" : (dashboard?.pending_reviews ?? "—")}
          detail="需要独立审核员处理"
          icon="✓"
          tone="purple"
        />
        <MetricCard
          label="来源健康"
          value={
            loading
              ? "—"
              : `${dashboard?.source_health.filter((x) => x.state === "healthy").length ?? 0}/${dashboard?.source_health.length ?? 0}`
          }
          detail="已配置来源"
          icon="⊙"
          tone="amber"
        />
      </div>
      {error ? (
        <ApiErrorState error={error} onRetry={load} />
      ) : (
        <div className="ps-grid-2">
          <section className="ps-card">
            <div className="ps-card-head">
              <div>
                <h2>近期登记变化</h2>
                <small>
                  版本化观察 · {dashboard ? `截至 ${formatDate(dashboard.as_of)}` : "加载中"}
                </small>
              </div>
              <Link href="/events" className="ps-btn tiny">
                查看全部 →
              </Link>
            </div>
            <div className="ps-card-body">
              {loading ? (
                <div className="ps-skeleton-list">
                  <i />
                  <i />
                  <i />
                </div>
              ) : events.length ? (
                events.slice(0, 4).map((event) => (
                  <Link
                    key={event.id}
                    href={`/events/detail/?id=${encodeURIComponent(event.id)}`}
                    className="ps-event-row ps-event-link"
                  >
                    <div className="ps-event-marker">{eventIcon[event.category] || "↗"}</div>
                    <div style={{ flex: 1 }}>
                      <h3>{event.title}</h3>
                      <p>
                        <span className="ps-chip blue">
                          {event.category === "correction"
                            ? "更正"
                            : event.category === "status_change"
                              ? "状态"
                              : "字段变化"}
                        </span>{" "}
                        <span className="ps-subtle">记录 {event.record_id}</span>
                      </p>
                      <small>{formatDate(event.updated_at)} · 点击查看前后证据</small>
                    </div>
                    <span className="ps-arrow" aria-hidden>
                      ›
                    </span>
                  </Link>
                ))
              ) : (
                <div className="ps-empty">
                  <h3>尚未同步变化</h3>
                  <p>完成来源同步后，这里会显示工作区内的新观察。</p>
                  <Link href="/settings" className="ps-btn" data-guest-mutation>
                    查看来源设置
                  </Link>
                </div>
              )}
            </div>
          </section>
          <div className="ps-stack">
            <section className="ps-card">
              <div className="ps-card-head">
                <div>
                  <h2>我的研究任务</h2>
                  <small>当前工作区可访问的运行</small>
                </div>
                <Link href="/research/new" className="ps-btn tiny" data-guest-mutation>
                  新建
                </Link>
              </div>
              <div className="ps-card-body">
                {runs.length === 0 ? (
                  <p className="ps-subtle">暂无研究任务。</p>
                ) : (
                  runs.slice(0, 3).map((run) => (
                    <Link
                      className="ps-run-item"
                      key={run.id}
                      href={`/research/detail/?id=${encodeURIComponent(run.id)}`}
                    >
                      <span className={`ps-run-dot ${run.status === "running" ? "running" : ""}`} />
                      <div>
                        <strong>{run.question}</strong>
                        <small>
                          {run.status} · {run.runtime_mode || "live"}
                        </small>
                      </div>
                      <StatusBadge
                        status={run.status}
                        tone={
                          run.status === "completed"
                            ? "success"
                            : run.status === "failed"
                              ? "danger"
                              : "warning"
                        }
                      />
                    </Link>
                  ))
                )}
              </div>
            </section>
            <section className="ps-card">
              <div className="ps-card-head">
                <div>
                  <h2>来源健康</h2>
                  <small>状态来自最近一次同步</small>
                </div>
                <Link href="/settings" className="ps-btn tiny" data-guest-mutation>
                  管理
                </Link>
              </div>
              <div className="ps-card-body">
                {(dashboard?.source_health || []).map((source) => (
                  <div className="ps-source-row" key={source.source}>
                    <span
                      className={`ps-source-dot ${source.state === "healthy" ? "" : source.state === "degraded" ? "warning" : "danger"}`}
                    />
                    <div className="ps-source-name">
                      <strong>{sourceLabels[source.source] || source.source}</strong>
                      <small>
                        {source.last_success_at
                          ? `最近成功 ${formatDate(source.last_success_at)}`
                          : "尚未成功同步"}
                      </small>
                    </div>
                    <StatusBadge
                      status={
                        source.state === "healthy"
                          ? "正常"
                          : source.state === "degraded"
                            ? "降级"
                            : "不可用"
                      }
                      tone={
                        source.state === "healthy"
                          ? "success"
                          : source.state === "degraded"
                            ? "warning"
                            : "danger"
                      }
                    />
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </PharmaScopeShell>
  );
}
