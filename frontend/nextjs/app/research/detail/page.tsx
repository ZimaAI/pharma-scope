"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import {
  cancelResearchRun,
  getResearchRun,
  ResearchRun,
  retryResearchRun,
  PHARMA_API_BASE,
  workspacePath,
  formatApiError,
} from "@/components/pharma/pharmaApi";
const terminal = ["completed", "partial", "failed", "cancelled"];
export default function ResearchDetailPage() {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [connection, setConnection] = useState("连接中");
  const [busy, setBusy] = useState(false);
  const load = () => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少运行 ID"));
      return;
    }
    setError(null);
    getResearchRun(id).then(setRun).catch(setError);
  };
  useEffect(load, []);
  useEffect(() => {
    if (!run?.id) return;
    const id = run.id;
    const controller = new AbortController();
    let cursor = 0;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    setEvents([]);
    const connect = async () => {
      try {
        const path = await workspacePath(`/research/runs/${encodeURIComponent(id)}/events`);
        const response = await fetch(`${PHARMA_API_BASE}${path}`, {
          credentials: "include",
          signal: controller.signal,
          headers: {
            Accept: "text/event-stream",
            ...(cursor ? { "Last-Event-ID": String(cursor) } : {}),
          },
        });
        if (!response.ok || !response.body) throw new Error(`SSE HTTP ${response.status}`);
        setConnection("已连接");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const lines = frame.split("\n");
            const data = lines
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (!data) continue;
            const payload = JSON.parse(data);
            const seq = Number(
              lines.find((line) => line.startsWith("id:"))?.slice(3) || payload.seq || 0
            );
            if (seq > cursor) {
              cursor = seq;
              setEvents((current) => [...current, payload].slice(-500));
            }
            getResearchRun(id).then(setRun).catch(setError);
          }
        }
        if (stopped) return;
        const current = await getResearchRun(id);
        setRun(current);
        if (terminal.includes(current.status)) {
          setConnection("事件已同步");
          return;
        }
        setConnection("连接结束，正在重连");
      } catch (failure) {
        if (stopped) return;
        setConnection(`连接中断，正在重连：${formatApiError(failure)}`);
      }
      if (!stopped) timer = setTimeout(connect, 2000);
    };
    connect();
    const poll = setInterval(() => getResearchRun(id).then(setRun).catch(setError), 5000);
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      clearInterval(poll);
    };
  }, [run?.id]);
  async function mutate(action: "cancel" | "retry") {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      const next =
        action === "cancel" ? await cancelResearchRun(run.id) : await retryResearchRun(run.id);
      setRun(next);
      window.history.replaceState(null, "", `/research/detail/?id=${encodeURIComponent(next.id)}`);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PharmaScopeShell
      title="研究任务"
      description={run ? `运行 ${run.id} · ${run.runtime_mode || "live"}` : "加载运行…"}
      actions={
        <>
          <button
            className="ps-btn"
            data-guest-mutation
            disabled={busy || !run || terminal.includes(run.status)}
            onClick={() => mutate("cancel")}
          >
            取消任务
          </button>
          <button
            className="ps-btn"
            data-guest-mutation
            disabled={busy || !run || !terminal.includes(run.status)}
            onClick={() => mutate("retry")}
          >
            重试运行
          </button>
        </>
      }
    >
      {!!error && <ApiErrorState error={error} onRetry={load} />}
      {!run ? (
        <p>加载中…</p>
      ) : (
        <div className="ps-grid-2">
          <section className="ps-card">
            <div className="ps-card-head">
              <h2>{run.question}</h2>
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
            </div>
            <div className="ps-card-body">
              <p role="status">SSE：{connection}</p>
              <div className="ps-callout amber">
                {run.error_message || run.stop_reason || "研究执行中"}
                {run.error_code && ` · ${run.error_code}`}
              </div>
              <h3>执行事件</h3>
              <div className="ps-timeline">
                {events.map((event) => (
                  <div className="ps-timeline-item active" key={event.seq}>
                    <strong>
                      {event.seq} · {event.type}
                    </strong>
                    <pre className="ps-json">
                      {JSON.stringify(event.payload || event.data || event, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          </section>
          <section className="ps-card">
            <div className="ps-card-head">
              <h2>资料覆盖与报告</h2>
            </div>
            <div className="ps-card-body">
              <h3>预算消耗</h3>
              <pre className="ps-json">{JSON.stringify(run.usage || {}, null, 2)}</pre>
              <h3>来源覆盖 / 资料缺口</h3>
              <pre className="ps-json">{JSON.stringify(run.coverage || [], null, 2)}</pre>
              {run.report_id ? (
                <Link
                  className="ps-btn primary"
                  href={`/reports/detail/?id=${encodeURIComponent(run.report_id)}`}
                >
                  查看报告与证据 →
                </Link>
              ) : (
                <p>报告尚未生成。</p>
              )}
            </div>
          </section>
        </div>
      )}
    </PharmaScopeShell>
  );
}
