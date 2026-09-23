"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, EmptyState } from "@/components/pharma/PharmaScopeShell";
import { getPublications, Publication } from "@/components/pharma/pharmaApi";
export default function LiteraturePage() {
  const [query, setQuery] = useState("");
  const [papers, setPapers] = useState<Publication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    getPublications()
      .then(setPapers)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  const filtered = papers.filter((paper) =>
    `${paper.title || ""} ${paper.external_id} ${JSON.stringify(paper.current_projection?.authors || [])}`
      .toLowerCase()
      .includes(query.toLowerCase())
  );
  return (
    <PharmaScopeShell title="研究文献" description="当前工作区已摄入的文献元数据与摘要覆盖。">
      <section className="ps-card">
        <div className="ps-filterbar">
          <input
            className="ps-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、作者或外部 ID"
            aria-label="搜索文献"
          />
          <span className="ps-chip">PubMed</span>
          <span className="ps-chip blue">{loading ? "加载中" : `${filtered.length} 条记录`}</span>
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
            title={query ? "没有匹配的文献" : "尚未同步文献"}
            detail={
              query ? "调整搜索词后重试。" : "完成 PubMed 来源同步后，这里会出现可访问的元数据。"
            }
          />
        ) : (
          <div>
            {filtered.map((paper) => (
              <article className="ps-paper-row" key={paper.id}>
                <div className="ps-paper-main">
                  <h3>
                    <Link href={`/literature/detail/?id=${paper.id}`}>
                      {paper.title || paper.external_id}
                    </Link>
                  </h3>
                  <p>{paper.abstract || "摘要缺失；不能补造摘要内容。"}</p>
                  <small>
                    {paper.source} · {new Date(paper.updated_at).toLocaleDateString("zh-CN")} ·{" "}
                    {paper.external_id}
                  </small>
                </div>
                <span className={`ps-chip ${paper.abstract ? "green" : "amber"}`}>
                  {paper.abstract ? "摘要可用" : "摘要缺失"}
                </span>
              </article>
            ))}
          </div>
        )}
        <div className="ps-callout amber" style={{ margin: 18 }}>
          文献内容由来源快照提供。摘要缺失和来源失败是不同状态，会分别呈现。
        </div>
      </section>
    </PharmaScopeShell>
  );
}
