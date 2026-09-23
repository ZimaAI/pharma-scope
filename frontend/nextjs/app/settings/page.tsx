"use client";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import {
  Drug,
  getDrugs,
  getSources,
  SourceConfig,
  workspaceFetch,
  jsonBody,
  mutationKey,
  getAuthMe,
} from "@/components/pharma/pharmaApi";
const labels: Record<string, string> = {
  clinicaltrials_gov: "ClinicalTrials.gov",
  ctgov: "ClinicalTrials.gov",
  pubmed: "PubMed",
};
export default function SettingsPage() {
  const [sources, setSources] = useState<SourceConfig[]>([]);
  const [drugs, setDrugs] = useState<Drug[]>([]);
  const [drug, setDrug] = useState("");
  const [syncMode, setSyncMode] = useState("discovery");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [admin, setAdmin] = useState(false);
  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([getSources(), getDrugs(), getAuthMe()])
      .then(([rows, objects, auth]) => {
        setSources(rows);
        setDrugs(objects);
        setDrug((value) => value || objects[0]?.id || "");
        const membership =
          auth.memberships.find(
            (m) => m.workspace_id === sessionStorage.getItem("pharmascope_workspace")
          ) || auth.memberships[0];
        setAdmin(membership?.role === "admin");
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(load, []);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("job_id");
    if (id) workspaceFetch(`/jobs/${encodeURIComponent(id)}`).then(setJob).catch(setError);
  }, []);
  useEffect(() => {
    if (job?.id) window.history.replaceState(null, "", `/settings?job_id=${encodeURIComponent(job.id)}`);
  }, [job?.id]);
  useEffect(() => {
    if (!job || !["queued", "running", "retrying"].includes(job.state)) return;
    const timer = setInterval(
      () => workspaceFetch(`/jobs/${job.id}`).then(setJob).catch(setError),
      2000
    );
    return () => clearInterval(timer);
  }, [job]);
  async function check(source: string) {
    setBusy(true);
    setError(null);
    try {
      setJob(await workspaceFetch(`/sources/${source}/check`, { method: "POST" }));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function sync(source: string) {
    setBusy(true);
    setError(null);
    try {
      setJob(
        await workspaceFetch(
          "/source-syncs",
          jsonBody({ sources: [source], drug_ids: [drug], mode: syncMode, limit: 100 }, "POST", {
            "Idempotency-Key": mutationKey(),
          })
        )
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(source: SourceConfig) {
    setBusy(true);
    try {
      await workspaceFetch(
        `/sources/${source.source}`,
        jsonBody({ enabled: !source.enabled }, "PATCH")
      );
      load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PharmaScopeShell
      title="来源与设置"
      description="来源状态来自真实同步结果；失败不会当作零结果。"
      actions={
        <button className="ps-btn" onClick={load}>
          刷新状态
        </button>
      }
    >
      {!!error && <ApiErrorState error={error} onRetry={load} />}
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>来源同步</h2>
        </div>
        <div className="ps-card-body">
          <label className="ps-form-label" htmlFor="sync-drug">
            研究对象
          </label>
          <select
            id="sync-drug"
            className="ps-input"
            value={drug}
            onChange={(event) => setDrug(event.target.value)}
          >
            {drugs.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
          <label className="ps-form-label" htmlFor="sync-mode">
            同步范围
          </label>
          <select
            id="sync-mode"
            className="ps-input"
            value={syncMode}
            onChange={(event) => setSyncMode(event.target.value)}
          >
            <option value="discovery">检索新候选记录</option>
            <option value="refresh_linked">更新已确认关联记录</option>
          </select>
          {loading ? (
            <p>加载中…</p>
          ) : (
            sources.map((source) => (
              <div className="ps-source-row" key={source.source}>
                <div className="ps-source-name">
                  <strong>{labels[source.source] || source.source}</strong>
                  <small>
                    {source.last_success_at ? `最近成功 ${source.last_success_at}` : "尚未成功同步"}
                    {source.last_error_code && ` · ${source.last_error_code}`}
                  </small>
                </div>
                <StatusBadge
                  status={!source.enabled ? "已停用" : source.state}
                  tone={source.state === "healthy" ? "success" : "warning"}
                />
                <button
                  className="ps-btn tiny"
                  disabled={busy || !drug || !source.enabled}
                  onClick={() => sync(source.source)}
                >
                  同步 {labels[source.source] || source.source}
                </button>
                {admin && (
                  <button
                    className="ps-btn tiny"
                    disabled={busy}
                    onClick={() => check(source.source)}
                  >
                    检查 {labels[source.source] || source.source}
                  </button>
                )}
                {admin && (
                  <button className="ps-btn tiny" disabled={busy} onClick={() => toggle(source)}>
                    {source.enabled ? "停用" : "启用"}
                  </button>
                )}
              </div>
            ))
          )}
          {!drug && <p>请先建立药物档案，然后同步来源。</p>}
          {job && (
            <div role="status">
              <h3>
                任务 {job.id} · {job.state}
              </h3>
              <pre className="ps-json">
                {JSON.stringify(
                  { progress: job.progress, coverage: job.coverage, error_code: job.error_code },
                  null,
                  2
                )}
              </pre>
            </div>
          )}
        </div>
      </section>
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>配置与安全</h2>
        </div>
        <div className="ps-card-body">
          <p>模型、NCBI email/API key 和 SMTP 凭据由服务器环境配置，浏览器不会接收或保存密钥。</p>
          <p>
            LIVE 模式需要 PostgreSQL、独立 worker 和可用的 OpenAI 兼容模型。SMTP 默认
            dry-run，站内通知由投递记录提供。
          </p>
        </div>
      </section>
    </PharmaScopeShell>
  );
}
