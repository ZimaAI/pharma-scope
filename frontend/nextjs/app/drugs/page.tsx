"use client";
import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, { ApiErrorState, EmptyState } from "@/components/pharma/PharmaScopeShell";
import { Drug, getDrugs, createDrug } from "@/components/pharma/pharmaApi";

export default function DrugsPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [archived, setArchived] = useState("all");
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createDrug({
        display_name: name,
        development_code: code,
        description: "",
        indications: [],
        targets: [],
      });
      setShowCreate(false);
      setName("");
      setCode("");
      load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const [drugs, setDrugs] = useState<Drug[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = () => {
    setLoading(true);
    setError(null);
    getDrugs()
      .then(setDrugs)
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, []);
  const filtered = useMemo(
    () =>
      drugs.filter(
        (d) =>
          (archived === "all" || d.archived === (archived === "archived")) &&
          `${d.display_name} ${d.development_code} ${d.description}`
            .toLowerCase()
            .includes(query.toLowerCase())
      ),
    [drugs, query, archived]
  );
  return (
    <PharmaScopeShell
      title="药物档案"
      description="工作区内已建立的研发对象、别名与资料新鲜度。"
      actions={
        <button className="ps-btn primary" type="button" onClick={() => setShowCreate(!showCreate)}>
          ＋ 建立药物档案
        </button>
      }
    >
      {showCreate && (
        <form className="ps-card ps-card-body" onSubmit={create}>
          <h2>建立药物档案</h2>
          <div className="ps-form-grid">
            <label>
              药物名称
              <input
                className="ps-input"
                aria-label="药物名称"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              研发代号
              <input
                className="ps-input"
                aria-label="研发代号"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
          </div>
          <button className="ps-btn primary" disabled={busy}>
            保存档案
          </button>
        </form>
      )}
      <section className="ps-card">
        <div className="ps-filterbar">
          <input
            className="ps-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索研发代号或名称"
            aria-label="搜索药物"
          />
          <select
            className="ps-input"
            aria-label="档案状态"
            value={archived}
            onChange={(event) => setArchived(event.target.value)}
          >
            <option value="all">全部状态</option>
            <option value="active">当前档案</option>
            <option value="archived">已归档</option>
          </select>
          <span className="ps-chip blue">{filtered.length} 个对象</span>
        </div>
        {loading ? (
          <div className="ps-card-body">
            <div className="ps-skeleton-list">
              <i />
              <i />
              <i />
            </div>
          </div>
        ) : error ? (
          <ApiErrorState error={error} onRetry={load} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title="没有匹配的药物档案"
            detail={query ? "调整搜索词后重试。" : "当前工作区尚未同步药物档案。"}
          />
        ) : (
          <div className="ps-table-wrap">
            <table className="ps-table">
              <thead>
                <tr>
                  <th>研发对象</th>
                  <th>研究标签</th>
                  <th>关联资料</th>
                  <th>最近更新</th>
                  <th>版本</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((drug) => (
                  <tr key={drug.id}>
                    <td>
                      <strong>
                        <Link href={`/drugs/detail/?id=${encodeURIComponent(drug.id)}`}>
                          {drug.display_name}
                        </Link>
                      </strong>
                      <small>{drug.description}</small>
                    </td>
                    <td>
                      <span className="ps-chip">{drug.indications?.[0] || "未设置"}</span>
                    </td>
                    <td>
                      <span className="ps-subtle">—</span>
                    </td>
                    <td>
                      <span className="ps-subtle">
                        {new Date(drug.updated_at).toLocaleDateString("zh-CN")}
                      </span>
                    </td>
                    <td>
                      <span className="ps-subtle">v{drug.revision}</span>
                    </td>
                    <td>
                      <Link
                        className="ps-text-link"
                        href={`/drugs/detail/?id=${encodeURIComponent(drug.id)}`}
                      >
                        查看 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="ps-table-foot">
              <span>显示当前工作区可访问对象</span>
              <span className="ps-subtle">游标分页由 API 提供</span>
            </div>
          </div>
        )}
      </section>
    </PharmaScopeShell>
  );
}
