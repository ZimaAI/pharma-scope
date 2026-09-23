"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getDrug, Drug, IS_REPLAY_MODE } from "@/components/pharma/pharmaApi";

export default function DrugDetailPage() {
  const [drug, setDrug] = useState<Drug | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setError(new Error("缺少药物 ID"));
      return;
    }
    getDrug(id).then(setDrug).catch(setError);
  }, []);
  return (
    <PharmaScopeShell title="药物详情" description="对象身份、关联记录与资料更新时间.">
      {error ? (
        <ApiErrorState error={error} />
      ) : !drug ? (
        <section className="ps-card">
          <div className="ps-card-body">加载中…</div>
        </section>
      ) : (
        <div className="ps-grid-2">
          <section className="ps-card">
            <div className="ps-card-head">
              <div className="ps-detail-title">
                <div className="ps-drug-badge">
                  {(drug.development_code || drug.display_name).slice(-3)}
                </div>
                <div>
                  <h2>{drug.display_name}</h2>
                  <small>{drug.id}</small>
                </div>
              </div>
              <StatusBadge
                status={drug.is_demo || IS_REPLAY_MODE ? "REPLAY / DEMO" : "当前档案"}
                tone={drug.is_demo || IS_REPLAY_MODE ? "info" : "success"}
              />
            </div>
            <div className="ps-card-body">
              <dl className="ps-kv">
                <dt>研发代号</dt>
                <dd>{drug.development_code}</dd>
                <dt>研究标签</dt>
                <dd>{drug.indications?.join("、") || "未设置"}</dd>
                <dt>靶点</dt>
                <dd>{drug.targets?.join("、") || "未设置"}</dd>
                <dt>档案版本</dt>
                <dd>v{drug.revision}</dd>
                <dt>最近更新</dt>
                <dd>{new Date(drug.updated_at).toLocaleString("zh-CN")}</dd>
              </dl>
              <div className="ps-callout amber" style={{ marginTop: 22 }}>
                档案字段来自工作区同步，未知内容保持为空，不从其他对象推断。
              </div>
            </div>
          </section>
          <div className="ps-stack">
            <section className="ps-card">
              <div className="ps-card-head">
                <h2>关联记录</h2>
              </div>
              <div className="ps-card-body">
                <p className="ps-subtle">关联试验和文献数量由服务端返回。</p>
                <Link
                  href={`/trials/?drug_id=${encodeURIComponent(drug.id)}`}
                  className="ps-text-link"
                >
                  查看关联试验 →
                </Link>
                <br />
                <Link
                  href={`/events/?drug_id=${encodeURIComponent(drug.id)}`}
                  className="ps-text-link"
                >
                  查看变化时间线 →
                </Link>
              </div>
            </section>
            <section className="ps-card">
              <div className="ps-card-body">
                <Link
                  href={`/research/new?drug_id=${encodeURIComponent(drug.id)}`}
                  className="ps-btn primary"
                >
                  基于此对象发起研究
                </Link>
              </div>
            </section>
          </div>
        </div>
      )}
    </PharmaScopeShell>
  );
}
