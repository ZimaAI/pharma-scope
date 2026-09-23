"use client";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getPublication, Publication, IS_REPLAY_MODE } from "@/components/pharma/pharmaApi";
import RecordHistory from "@/components/pharma/RecordHistory";
export default function LiteratureDetailPage() {
  const [paper, setPaper] = useState<Publication | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少文献 ID"));
      return;
    }
    getPublication(id).then(setPaper).catch(setError);
  }, []);
  return (
    <PharmaScopeShell title="文献详情" description="元数据、摘要可用性与来源快照。">
      {error ? (
        <ApiErrorState error={error} />
      ) : !paper ? (
        <section className="ps-card">
          <div className="ps-card-body">加载中…</div>
        </section>
      ) : (
        <section className="ps-card">
          <div className="ps-card-head">
            <div>
              <h2>{paper.title || paper.external_id}</h2>
              <small>
                {paper.external_id} · {paper.source}
              </small>
            </div>
            <StatusBadge
              status={paper.is_demo || IS_REPLAY_MODE ? "REPLAY / DEMO" : "LIVE"}
              tone={paper.is_demo || IS_REPLAY_MODE ? "info" : "success"}
            />
          </div>
          <div className="ps-card-body">
            <dl className="ps-kv">
              <dt>更新时间</dt>
              <dd>{new Date(paper.updated_at).toLocaleString("zh-CN")}</dd>
              <dt>摘要</dt>
              <dd>{paper.abstract ? "可获得摘要" : "摘要缺失"}</dd>
            </dl>
            {paper.abstract && <p className="ps-report-body">{paper.abstract}</p>}
            <RecordHistory recordId={paper.id} />
            <div className="ps-callout amber" style={{ marginTop: 22 }}>
              文献内容来自来源快照。摘要缺失和来源失败是不同状态。
            </div>
          </div>
        </section>
      )}
    </PharmaScopeShell>
  );
}
