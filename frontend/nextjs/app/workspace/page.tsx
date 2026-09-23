"use client";
import { useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { getAuthMe, workspaceFetch, jsonBody } from "@/components/pharma/pharmaApi";
export default function WorkspacePage() {
  const [members, setMembers] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const [role, setRole] = useState("");
  const [self, setSelf] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const load = () => {
    setError(null);
    Promise.all([
      workspaceFetch<{ items: any[] }>("/members?limit=100"),
      workspaceFetch<{ items: any[] }>("/entity-links?limit=100"),
      getAuthMe(),
    ])
      .then(([people, relations, auth]) => {
        setMembers(people.items);
        setLinks(relations.items);
        setSelf(auth.user.id);
        const membership =
          auth.memberships.find(
            (m) => m.workspace_id === sessionStorage.getItem("pharmascope_workspace")
          ) || auth.memberships[0];
        setRole(membership?.role || "");
      })
      .catch(setError);
  };
  useEffect(load, []);
  async function update(path: string, payload: any, method = "POST") {
    setBusy(true);
    try {
      await workspaceFetch(path, jsonBody(payload, method));
      load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PharmaScopeShell
      title="工作区与关联审核"
      description="成员权限和药物来源记录关联由服务端校验。"
      actions={
        <button className="ps-btn" onClick={load}>
          刷新
        </button>
      }
    >
      {!!error && <ApiErrorState error={error} onRetry={load} />}
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>工作区成员</h2>
        </div>
        <div className="ps-card-body">
          {members.map((member) => (
            <div className="ps-source-row" key={member.user.id}>
              <div className="ps-source-name">
                <strong>{member.user.display_name || member.user.email}</strong>
                <small>{member.user.email}</small>
              </div>
              <select
                aria-label={`${member.user.email} 角色`}
                className="ps-input"
                value={member.role}
                disabled={busy || role !== "admin" || member.user.id === self}
                onChange={(event) =>
                  update(`/members/${member.user.id}`, { role: event.target.value }, "PATCH")
                }
              >
                {["reader", "analyst", "reviewer", "admin"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
              <button
                className="ps-btn tiny"
                disabled={busy || role !== "admin" || member.user.id === self}
                onClick={() =>
                  update(`/members/${member.user.id}`, { enabled: !member.enabled }, "PATCH")
                }
              >
                {member.enabled ? "停用成员" : "启用成员"}
              </button>
            </div>
          ))}
        </div>
      </section>
      <section className="ps-card">
        <div className="ps-card-head">
          <h2>来源记录关联审核</h2>
        </div>
        <div className="ps-card-body">
          <p>检索匹配产生候选关联。审核确认身份后，研究任务才会引用记录。</p>
          <label className="ps-form-label" htmlFor="link-note">
            关联审核备注
          </label>
          <textarea
            id="link-note"
            className="ps-input"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          {links.length ? (
            links.map((link) => (
              <div className="ps-subscription" key={link.id}>
                <div>
                  <strong>药物 {link.drug_id}</strong>
                  <p>记录 {link.record_id}</p>
                  <small>
                    {link.relation} · {link.note}
                  </small>
                </div>
                <StatusBadge status={link.status} />
                <button
                  className="ps-btn tiny"
                  disabled={
                    busy ||
                    !["reviewer", "admin"].includes(role) ||
                    !note.trim() ||
                    link.status === "approved"
                  }
                  onClick={() =>
                    update(`/entity-links/${link.id}/decision`, { decision: "approve", note })
                  }
                >
                  确认关联
                </button>
                <button
                  className="ps-btn tiny"
                  disabled={busy || !["reviewer", "admin"].includes(role) || !note.trim()}
                  onClick={() =>
                    update(`/entity-links/${link.id}/decision`, {
                      decision: link.status === "approved" ? "revoke" : "reject",
                      note,
                    })
                  }
                >
                  {link.status === "approved" ? "撤销关联" : "拒绝关联"}
                </button>
              </div>
            ))
          ) : (
            <p>尚无候选关联；请先同步来源。</p>
          )}
        </div>
      </section>
    </PharmaScopeShell>
  );
}
