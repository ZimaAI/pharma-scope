"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  apiFetch,
  IS_REPLAY_MODE,
  formatApiError,
  getRuntimeMode,
} from "@/components/pharma/pharmaApi";

export default function LoginPage() {
  const [replay, setReplay] = useState<boolean | null>(null);
  useEffect(() => {
    getRuntimeMode()
      .then(setReplay)
      .catch(() => setReplay(null));
  }, []);
  const [email, setEmail] = useState(IS_REPLAY_MODE ? "analyst@pharmascope.invalid" : "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      window.location.assign("/");
    } catch (requestError) {
      setError(formatApiError(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="ps-login">
      <section className="ps-login-card ps-card">
        <div className="ps-brand-mark">P</div>
        <span className="ps-kicker">
          PHARMASCOPE LITE · {replay === null ? "模式待确认" : replay ? "REPLAY / DEMO" : "LIVE"}
        </span>
        <h1>登录研发情报工作台</h1>
        <p>使用工作区账号查看可追溯的登记变化、证据和研究报告。</p>
        <form onSubmit={submit}>
          <label className="ps-form-label" htmlFor="email">
            邮箱
          </label>
          <input
            id="email"
            className="ps-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <label className="ps-form-label" htmlFor="password">
            密码
          </label>
          <input
            id="password"
            className="ps-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && (
            <p className="ps-form-error" role="alert">
              {error}
            </p>
          )}
          <button className="ps-btn primary ps-login-submit" disabled={busy}>
            {busy ? "登录中…" : "登录"}
          </button>
        </form>
        {replay ? (
          <div className="ps-callout" style={{ marginTop: 18 }}>
            REPLAY / DEMO 演示账号：analyst@pharmascope.invalid。密码由管理员通过
            PHARMA_DEMO_PASSWORD 设置。不会访问真实来源或模型。
          </div>
        ) : (
          <div className="ps-callout" style={{ marginTop: 18 }}>
            LIVE 模式需要由管理员创建账号并配置真实凭据。
          </div>
        )}
      </section>
    </main>
  );
}
