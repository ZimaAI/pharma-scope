"use client";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getTrial, Trial, IS_REPLAY_MODE } from "@/components/pharma/pharmaApi";
import RecordHistory from "@/components/pharma/RecordHistory";
export default function TrialDetailPage() {
  const [trial, setTrial] = useState<Trial | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少试验 ID"));
      return;
    }
    getTrial(id).then(setTrial).catch(setError);
  }, []);
  const p = trial?.current_projection || {};
  return (
    <PharmaScopeShell title="试验详情" description="当前投影、原始字段与观察版本。">
      {error ? (
        <ApiErrorState error={error} />
      ) : !trial ? (
        <section className="ps-card">
          <div className="ps-card-body">加载中…</div>
        </section>
      ) : (
        <section className="ps-card">
          <div className="ps-card-head">
            <div>
              <h2>{trial.external_id}</h2>
              <small>{p.brief_title || "暂无标题"}</small>
            </div>
            <StatusBadge
              status={
                trial.is_demo || IS_REPLAY_MODE ? "REPLAY / DEMO" : p.overall_status || "未知"
              }
              tone={trial.is_demo || IS_REPLAY_MODE ? "info" : "success"}
            />
          </div>
          <div className="ps-card-body">
            <dl className="ps-kv">
              <dt>来源</dt>
              <dd>{trial.source}</dd>
              <dt>阶段</dt>
              <dd>{p.phase?.join(", ") || "未知"}</dd>
              <dt>目标入组</dt>
              <dd>{p.enrollment ?? "未知"}</dd>
              <dt>最近观察</dt>
              <dd>{new Date(trial.updated_at).toLocaleString("zh-CN")}</dd>
            </dl>
            <RecordHistory recordId={trial.id} />
            <div className="ps-callout" style={{ marginTop: 20 }}>
              状态和人数均为登记字段原值。页面不会把状态变更解释为试验成功或疗效结论。
            </div>
          </div>
        </section>
      )}
    </PharmaScopeShell>
  );
}
