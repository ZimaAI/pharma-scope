"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/components/pharma/pharmaApi";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("analyst@pharmascope.invalid");
  const [password, setPassword] = useState("demo");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const result = await apiFetch("/api/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
    setBusy(false);
    if (!result) { setError("登录失败，请检查账号或确认 API 服务已启动。"); return; }
    router.push("/");
  }

  return <main className="ps-login"><section className="ps-login-card ps-card"><div className="ps-brand-mark">P</div><span className="ps-kicker">PHARMASCOPE LITE</span><h1>登录研发情报工作台</h1><p>使用工作区账号查看可追溯的登记变化、证据和研究报告。</p><form onSubmit={submit}><label className="ps-form-label" htmlFor="email">邮箱</label><input id="email" className="ps-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /><label className="ps-form-label" htmlFor="password">密码</label><input id="password" className="ps-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />{error && <p className="ps-form-error" role="alert">{error}</p>}<button className="ps-btn primary ps-login-submit" disabled={busy}>{busy ? "登录中…" : "登录"}</button></form><div className="ps-callout" style={{ marginTop: 18 }}>DEMO 模式示例账号：`analyst@pharmascope.invalid` / `demo`。正式环境由管理员 CLI 创建账号。</div></section></main>;
}
