"use client";
import { useCallback, useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import EvidenceDrawer from "@/components/pharma/EvidenceDrawer";
import {
  getAuthMe,
  getReport,
  getReportVersion,
  Report,
  submitReportReview,
  workspaceFetch,
  jsonBody,
  mutationKey,
} from "@/components/pharma/pharmaApi";
const labels: Record<string, string> = {
  draft: "草稿",
  in_review: "审核中",
  changes_requested: "需修改",
  approved: "已批准",
  published: "已发布",
  retracted: "已撤回",
};
export default function ReportDetailPage() {
  const [editSummary, setEditSummary] = useState("");
  const [editSections, setEditSections] = useState<any[]>([]);
  const [editNote, setEditNote] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [version, setVersion] = useState<any>(null);
  const [versions, setVersions] = useState<any[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [auth, setAuth] = useState<any>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const closeEvidence = useCallback(() => setEvidenceId(null), []);
  const load = async () => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少报告 ID"));
      return;
    }
    try {
      setError(null);
      const item = await getReport(id);
      setReport(item);
      const [v, all, me] = await Promise.all([
        getReportVersion(id),
        workspaceFetch<{ items: any[] }>(`/reports/${id}/versions`),
        getAuthMe(),
      ]);
      setVersion(v);
      setVersions(all.items);
      setAuth(me);
    } catch (failure) {
      setError(failure);
    }
  };
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    setEditSummary(version?.content?.summary || "");
    setEditSections(version?.content?.sections || []);
  }, [version]);
  async function revise() {
    if (!report || !version) return;
    setBusy(true);
    try {
      await workspaceFetch(
        `/reports/${report.id}/versions`,
        jsonBody({
          base_version_id: version.id,
          edit_note: editNote,
          content: { ...version.content, summary: editSummary, sections: editSections },
        })
      );
      setEditNote("");
      await load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function action(kind: string) {
    if (!report || !version) return;
    setBusy(true);
    setError(null);
    try {
      if (kind === "approve" || kind === "request_changes")
        await submitReportReview(report.id, kind, note);
      else
        await workspaceFetch(
          `/reports/${report.id}/${kind}`,
          jsonBody({ version_id: version.id, content_hash: version.content_hash }, "POST", {
            "Idempotency-Key": mutationKey(),
          })
        );
      await load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const content = version?.content;
  const isAuthor = auth?.user?.id === version?.created_by;
  const selectedWorkspace =
    typeof window !== "undefined" ? sessionStorage.getItem("pharmascope_workspace") : null;
  const role =
    auth?.memberships?.find((m: any) => m.workspace_id === selectedWorkspace)?.role ||
    auth?.memberships?.[0]?.role;
  const canReview = ["reviewer", "admin"].includes(role) && !isAuthor;
  const current = version?.id === report?.current_version_id;
  return (
    <PharmaScopeShell
      title="报告阅读与审核"
      description={report ? `运行 ${report.run_id || "—"} · 内容版本和 hash 可核验` : "加载报告…"}
    >
      {!!error && <ApiErrorState error={error} onRetry={load} />}
      {!report ? (
        <p>加载中…</p>
      ) : (
        <div className="ps-grid-2">
          <article className="ps-card">
            <div className="ps-card-head">
              <h2>{report.title}</h2>
              <StatusBadge
                status={labels[report.state] || report.state}
                tone={report.state === "published" ? "success" : "info"}
              />
            </div>
            <div className="ps-report-body">
              <label className="ps-form-label" htmlFor="version">
                报告版本
              </label>
              <select
                id="version"
                className="ps-input"
                value={version?.id || ""}
                onChange={(event) =>
                  getReportVersion(report.id, event.target.value).then(setVersion).catch(setError)
                }
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version_no} · {v.id}
                  </option>
                ))}
              </select>
              <p className="ps-subtle">版本哈希：{version?.content_hash}</p>
              {content ? (
                <>
                  <p>{content.summary}</p>
                  {content.sections?.map((section: any, index: number) => (
                    <section key={index}>
                      <h3>{section.heading}</h3>
                      <p>{section.text}</p>
                    </section>
                  ))}
                  {content.markdown && <pre className="ps-json">{content.markdown}</pre>}
                  <h3>资料范围</h3>
                  <pre className="ps-json">{JSON.stringify(content.scope || {}, null, 2)}</pre>
                  <h3>来源覆盖</h3>
                  <pre className="ps-json">{JSON.stringify(content.coverage || [], null, 2)}</pre>
                  <h3>结论与证据</h3>
                  {content.claims?.map((claim: any, index: number) => (
                    <div key={claim.claim_key || index}>
                      <p>
                        <strong>{claim.claim_key}</strong> {claim.statement}
                      </p>
                      {claim.evidence_links?.map((link: any) => (
                        <button
                          key={link.evidence_id}
                          className="ps-btn tiny"
                          onClick={() => setEvidenceId(link.evidence_id)}
                        >
                          查看证据 {link.evidence_id.slice(0, 8)}
                        </button>
                      ))}
                    </div>
                  ))}
                  <h3>限制与未解决问题</h3>
                  {[...(content.limitations || []), ...(content.unanswered_questions || [])].map(
                    (item: string, index: number) => (
                      <p key={index}>{item}</p>
                    )
                  )}
                </>
              ) : (
                <p>当前版本正文尚未生成。</p>
              )}
            </div>
          </article>
          <section className="ps-card" data-guest-mutation>
            <div className="ps-card-head">
              <h2>审核与发布</h2>
            </div>
            <div className="ps-card-body">
              <div className="ps-callout">
                {isAuthor
                  ? "你是此版本作者，需由其他审核员批准。"
                  : "独立审核员需核对当前版本及关联证据。"}
              </div>
              {role !== "reader" && current && (
                <details>
                  <summary>创建修订版本</summary>
                  <label className="ps-form-label" htmlFor="edit-summary">
                    报告摘要
                  </label>
                  <textarea
                    id="edit-summary"
                    className="ps-input"
                    value={editSummary}
                    onChange={(event) => setEditSummary(event.target.value)}
                  />
                  {editSections.map((section, index) => (
                    <label key={index} className="ps-form-label">
                      {section.heading}
                      <textarea
                        className="ps-input"
                        value={section.text}
                        onChange={(event) =>
                          setEditSections(
                            editSections.map((item, i) =>
                              i === index ? { ...item, text: event.target.value } : item
                            )
                          )
                        }
                      />
                    </label>
                  ))}
                  <label className="ps-form-label" htmlFor="edit-note">
                    修订说明
                  </label>
                  <input
                    id="edit-note"
                    className="ps-input"
                    value={editNote}
                    onChange={(event) => setEditNote(event.target.value)}
                  />
                  <button className="ps-btn" disabled={busy || !editNote.trim()} onClick={revise}>
                    保存新版本
                  </button>
                </details>
              )}
              <label className="ps-form-label" htmlFor="review-note">
                审核备注
              </label>
              <textarea
                id="review-note"
                className="ps-input"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <label className="ps-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => setChecked(event.target.checked)}
                />{" "}
                我已核对范围、时间、关键数字和资料缺口
              </label>
              <div className="ps-form-actions">
                {["analyst", "admin"].includes(role) &&
                  ["draft", "changes_requested"].includes(report.state) && (
                    <button
                      className="ps-btn"
                      disabled={busy || !current}
                      onClick={() => action("submit-review")}
                    >
                      提交审核
                    </button>
                  )}
                <button
                  className="ps-btn"
                  disabled={
                    busy || !canReview || !current || !note.trim() || report.state !== "in_review"
                  }
                  onClick={() => action("request_changes")}
                >
                  退回修改
                </button>
                <button
                  className="ps-btn primary"
                  disabled={
                    busy ||
                    !canReview ||
                    !current ||
                    !checked ||
                    !note.trim() ||
                    report.state !== "in_review"
                  }
                  onClick={() => action("approve")}
                >
                  批准版本
                </button>
                <button
                  className="ps-btn primary"
                  disabled={busy || !canReview || !current || report.state !== "approved"}
                  onClick={() => action("publish")}
                >
                  发布报告
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
      {evidenceId && <EvidenceDrawer id={evidenceId} onClose={closeEvidence} />}
    </PharmaScopeShell>
  );
}
