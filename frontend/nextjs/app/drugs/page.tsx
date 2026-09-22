"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PharmaScopeShell, { EmptyState } from "@/components/pharma/PharmaScopeShell";
import { Drug, getDrugs } from "@/components/pharma/pharmaApi";

export default function DrugsPage() {
  const [drugs, setDrugs] = useState<Drug[]>([]); const [query, setQuery] = useState(""); const [loading, setLoading] = useState(true);
  useEffect(() => { getDrugs().then(setDrugs).finally(() => setLoading(false)); }, []);
  const filtered = useMemo(() => drugs.filter((d) => `${d.display_name} ${d.development_code} ${d.description}`.toLowerCase().includes(query.toLowerCase())), [drugs, query]);
  return <PharmaScopeShell title="药物档案" description="工作区内已建立的研发对象、别名与资料新鲜度。" actions={<button className="ps-btn primary" type="button">＋ 建立药物档案</button>}>
    <section className="ps-card"><div className="ps-filterbar"><input className="ps-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索研发代号或名称" aria-label="搜索药物" /><select className="ps-input" aria-label="档案状态"><option>全部状态</option><option>当前档案</option><option>已归档</option></select><span className="ps-chip blue">{filtered.length} 个对象</span></div>
      {loading ? <div className="ps-card-body"><div className="ps-skeleton-list"><i /><i /><i /></div></div> : filtered.length === 0 ? <EmptyState title="没有匹配的药物档案" detail={query ? "调整搜索词后重试。" : "当前工作区尚未同步药物档案。"} /> : <div className="ps-table-wrap"><table className="ps-table"><thead><tr><th>研发对象</th><th>研究标签</th><th>关联资料</th><th>最近更新</th><th>版本</th><th /></tr></thead><tbody>{filtered.map((drug) => <tr key={drug.id}><td><strong><Link href={`/drugs/detail/?id=${encodeURIComponent(drug.id)}`}>{drug.display_name}</Link></strong><small>{drug.description}</small></td><td><span className="ps-chip">{drug.indications?.[0] || "未设置"}</span></td><td><span className="ps-subtle">—</span></td><td><span className="ps-subtle">{new Date(drug.updated_at).toLocaleDateString("zh-CN")}</span></td><td><span className="ps-subtle">v{drug.revision}</span></td><td><Link className="ps-text-link" href={`/drugs/detail/?id=${encodeURIComponent(drug.id)}`}>查看 →</Link></td></tr>)}</tbody></table><div className="ps-table-foot"><span>显示当前工作区可访问对象</span><span className="ps-subtle">游标分页由 API 提供</span></div></div>}
    </section>
  </PharmaScopeShell>;
}
