"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  formatApiError,
  getRuntimeMode,
  loginAsGuest,
  loginWithPassword,
} from "@/components/pharma/pharmaApi";

export default function LoginPage() {
  const [replay, setReplay] = useState<boolean | null>(null);
  const [showAccount, setShowAccount] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRuntimeMode()
      .then(setReplay)
      .catch(() => setReplay(null));
  }, []);

  async function guestLogin() {
    setBusy(true);
    setError("");
    try {
      await loginAsGuest();
      window.location.assign("/");
    } catch (requestError) {
      setError(formatApiError(requestError));
      setBusy(false);
    }
  }

  async function accountLogin(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await loginWithPassword(email, password);
      window.location.assign("/");
    } catch (requestError) {
      setError(formatApiError(requestError));
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
        <p>点击登录，以只读游客身份浏览演示数据。</p>
        <button
          className="ps-btn primary ps-login-submit"
          type="button"
          disabled={busy}
          onClick={guestLogin}
        >
          {busy ? "登录中…" : "登录"}
        </button>
        {error && (
          <p className="ps-form-error" role="alert">
            {error}
          </p>
        )}
        <button
          className="ps-account-entry"
          type="button"
          aria-expanded={showAccount}
          aria-controls="ps-account-login"
          onClick={() => {
            setShowAccount((value) => !value);
            setError("");
          }}
        >
          {showAccount ? "收起账号登录" : "使用工作区账号"}
        </button>
        {showAccount && (
          <form id="ps-account-login" className="ps-account-form" onSubmit={accountLogin}>
            <label className="ps-form-label" htmlFor="email">
              邮箱
            </label>
            <input
              id="email"
              className="ps-input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <label className="ps-form-label" htmlFor="password">
              密码
            </label>
            <input
              id="password"
              className="ps-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <button className="ps-btn ps-login-submit" disabled={busy}>
              {busy ? "登录中…" : "账号密码登录"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
