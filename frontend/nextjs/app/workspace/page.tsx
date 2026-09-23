"use client";
import { FormEvent, useEffect, useState } from "react";
import PharmaScopeShell, { ApiErrorState, StatusBadge } from "@/components/pharma/PharmaScopeShell";
import { apiFetch, getAuthMe, isGuest, workspaceFetch, jsonBody } from "@/components/pharma/pharmaApi";

type DemoAccount = {
  user_id: string | null;
  user: { id: string; email: string; display_name?: string } | null;
  enabled: boolean;
};

export default function WorkspacePage() {
  const [members, setMembers] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const [role, setRole] = useState("");
  const [self, setSelf] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [demoAccount, setDemoAccount] = useState<DemoAccount | null>(null);
  const [demoUserId, setDemoUserId] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("reader");
  const [newPassword, setNewPassword] = useState("");
  const [resetUserId, setResetUserId] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [ownNewPassword, setOwnNewPassword] = useState("");
  const load = async () => {
    setError(null);
    try {
      const auth = await getAuthMe();
      if (isGuest(auth)) return;
      const membership =
        auth.memberships.find(
          (m) => m.workspace_id === sessionStorage.getItem("pharmascope_workspace")
        ) || auth.memberships[0];
      const admin = membership?.role === "admin";
      const [people, relations, demo] = await Promise.all([
        workspaceFetch<{ items: any[] }>("/members?limit=100"),
        workspaceFetch<{ items: any[] }>("/entity-links?limit=100"),
        admin ? workspaceFetch<DemoAccount>("/settings/demo-account") : Promise.resolve(null),
      ]);
      setMembers(people.items);
      setLinks(relations.items);
      setSelf(auth.user.id);
      setRole(membership?.role || "");
      setDemoAccount(demo);
      setDemoUserId(demo?.user_id || "");
      setResetUserId((value) => value || people.items.find((item) => item.user.id !== auth.user.id)?.user.id || "");
    } catch (failure) {
      setError(failure);
    }
  };
  useEffect(() => { void load(); }, []);
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
  async function createMember(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workspaceFetch("/members", jsonBody({
        email: newEmail.trim(), display_name: newName.trim(), password: newPassword, role: newRole,
      }));
      setNewEmail("");
      setNewName("");
      setNewPassword("");
      setMessage("成员账号已创建。");
      await load();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function saveDemoAccount() {
    setBusy(true);
    setError(null);
    try {
      const next = await workspaceFetch<DemoAccount>("/settings/demo-account", jsonBody({ user_id: demoUserId || null }, "PATCH"));
      setDemoAccount(next);
      setDemoUserId(next.user_id || "");
      setMessage(next.enabled ? "游客演示账号已更新。" : "游客演示账号已关闭。");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function resetMember(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workspaceFetch(`/members/${encodeURIComponent(resetUserId)}/password`, jsonBody({ new_password: resetPassword }));
      setResetPassword("");
      setMessage("成员密码已重置。");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/v1/auth/password", jsonBody({ current_password: currentPassword, new_password: ownNewPassword }));
      setCurrentPassword("");
      setOwnNewPassword("");
      setMessage("你的密码已更新。");
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
      {message && <div className="ps-callout green" role="status">{message}</div>}
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
      {role === "admin" && (
        <section className="ps-card" style={{ marginTop: 20 }}>
          <div className="ps-card-head"><h2>账号与游客演示</h2></div>
          <div className="ps-card-body">
            <h3>游客可浏览的账号</h3>
            <p className="ps-subtle">游客以独立只读会话查看所选账号在当前工作区的数据。</p>
            <div className="ps-form-grid">
              <label>演示账号
                <select className="ps-input" aria-label="游客演示账号" value={demoUserId} onChange={(event) => setDemoUserId(event.target.value)}>
                  <option value="">关闭游客演示</option>
                  {members.filter((member) => member.enabled !== false && member.user.is_active !== false).map((member) => (
                    <option key={member.user.id} value={member.user.id}>{member.user.display_name || member.user.email} · {member.user.email}</option>
                  ))}
                </select>
              </label>
            </div>
            <button className="ps-btn primary" type="button" disabled={busy || demoUserId === (demoAccount?.user_id || "")} onClick={saveDemoAccount}>保存演示账号</button>
            <div className="ps-divider" />
            <h3>创建成员账号</h3>
            <form onSubmit={createMember}>
              <div className="ps-form-grid">
                <label>邮箱<input className="ps-input" aria-label="新成员邮箱" type="email" autoComplete="off" required value={newEmail} onChange={(event) => setNewEmail(event.target.value)} /></label>
                <label>显示名称<input className="ps-input" aria-label="新成员名称" required value={newName} onChange={(event) => setNewName(event.target.value)} /></label>
                <label>初始密码<input className="ps-input" aria-label="新成员初始密码" type="password" autoComplete="new-password" minLength={12} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
                <label>角色<select className="ps-input" aria-label="新成员角色" value={newRole} onChange={(event) => setNewRole(event.target.value)}>
                  {["reader", "analyst", "reviewer", "admin"].map((value) => <option key={value} value={value}>{value}</option>)}
                </select></label>
              </div>
              <button className="ps-btn primary" disabled={busy}>创建账号</button>
            </form>
            <div className="ps-divider" />
            <h3>重置成员密码</h3>
            <form onSubmit={resetMember}>
              <div className="ps-form-grid">
                <label>成员<select className="ps-input" aria-label="重置密码成员" value={resetUserId} onChange={(event) => setResetUserId(event.target.value)} required>
                  {members.filter((member) => member.user.id !== self).map((member) => <option key={member.user.id} value={member.user.id}>{member.user.email}</option>)}
                </select></label>
                <label>新密码<input className="ps-input" aria-label="成员新密码" type="password" autoComplete="new-password" minLength={12} required value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} /></label>
              </div>
              <button className="ps-btn" disabled={busy || !resetUserId}>重置密码</button>
            </form>
          </div>
        </section>
      )}
      <section className="ps-card" style={{ marginTop: 20 }}>
        <div className="ps-card-head"><h2>修改我的密码</h2></div>
        <div className="ps-card-body">
          <form onSubmit={changePassword}>
            <div className="ps-form-grid">
              <label>当前密码<input className="ps-input" aria-label="当前密码" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
              <label>新密码<input className="ps-input" aria-label="我的新密码" type="password" autoComplete="new-password" minLength={12} required value={ownNewPassword} onChange={(event) => setOwnNewPassword(event.target.value)} /></label>
            </div>
            <button className="ps-btn" disabled={busy}>更新密码</button>
          </form>
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
