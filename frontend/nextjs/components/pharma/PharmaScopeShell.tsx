"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import {
  formatApiError,
  getAuthMe,
  IS_REPLAY_MODE,
  logout as apiLogout,
  AuthMe,
  isGuest,
  selectWorkspace,
  PharmaApiError,
} from "@/components/pharma/pharmaApi";

export const navItems = [
  { href: "/", label: "工作台", icon: "⌂" },
  { href: "/drugs", label: "药物档案", icon: "▣" },
  { href: "/trials", label: "临床试验", icon: "◫" },
  { href: "/events", label: "变化追踪", icon: "↗" },
  { href: "/literature", label: "研究文献", icon: "▤" },
  { href: "/research/new", label: "研究任务", icon: "✦" },
  { href: "/reports", label: "报告中心", icon: "▥" },
  { href: "/subscriptions", label: "我的订阅", icon: "◉" },
  { href: "/inbox", label: "通知", icon: "◌" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

type Props = {
  children: ReactNode;
  title?: string;
  description?: string;
  actions?: ReactNode;
};

export default function PharmaScopeShell({ children, title, description, actions }: Props) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [auth, setAuth] = useState<AuthMe | null>(null);
  const [authError, setAuthError] = useState("");
  useEffect(() => {
    getAuthMe()
      .then(setAuth)
      .catch((error) => {
        if (error instanceof PharmaApiError && error.status === 401) {
          window.location.replace("/login");
          return;
        }
        setAuthError(formatApiError(error));
      });
  }, []);
  const guest = isGuest(auth);
  const membership =
    auth?.memberships?.find(
      (item) =>
        item.workspace_id ===
        (typeof window !== "undefined" ? sessionStorage.getItem("pharmascope_workspace") : null)
    ) || auth?.memberships?.[0];
  const workspaceName =
    membership?.workspace_name ||
    membership?.workspace?.name ||
    (IS_REPLAY_MODE ? "PharmaScope 演示研究组" : "当前工作区");
  const userName =
    auth?.user?.display_name ||
    auth?.user?.name ||
    auth?.user?.email ||
    (IS_REPLAY_MODE ? "演示研究员" : "未登录");
  const modeLabel = guest ? "游客 · 只读" : !auth ? "模式待确认" : IS_REPLAY_MODE ? "REPLAY / DEMO" : "LIVE";
  async function handleLogout() {
    try {
      await apiLogout();
      window.location.href = "/login";
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "登出失败");
    }
  }

  if (!auth) {
    return (
      <div className="ps-auth-check" role="status">
        {authError ? (
          <>
            <p>身份状态暂不可用：{authError}</p>
            <Link href="/login" className="ps-btn primary">前往登录</Link>
          </>
        ) : "正在验证登录状态…"}
      </div>
    );
  }

  return (
    <div className={`ps-app ${guest ? "ps-guest" : ""}`}>
      <aside className={`ps-sidebar ${sidebarOpen ? "open" : ""}`} aria-label="主导航">
        <div className="ps-brand">
          <div className="ps-brand-mark">P</div>
          <div>
            <strong>PharmaScope</strong>
            <small>LITE · 研发情报工作台</small>
          </div>
        </div>
        <div className="ps-workspace">
          <span>当前工作区</span>
          <select
            aria-label="切换工作区"
            className="ps-input"
            value={membership?.workspace_id || ""}
            disabled={guest}
            onChange={(e) => selectWorkspace(e.target.value)}
          >
            {auth?.memberships
              .filter((item) => item.enabled !== false && item.workspace_id !== "demo-workspace")
              .map((item) => (
                <option key={item.workspace_id} value={item.workspace_id}>
                  {item.workspace_name || item.workspace?.name || item.workspace_id}
                </option>
              ))}
          </select>
        </div>
        <nav className="ps-nav">
          <div className="ps-nav-label">工作台</div>
          {navItems.slice(0, 5).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`ps-nav-link ${isActive(pathname, item.href) ? "active" : ""}`}
              onClick={() => setSidebarOpen(false)}
            >
              <span className="ps-nav-icon" aria-hidden>
                {item.icon}
              </span>
              <span>{item.label}</span>
            </Link>
          ))}
          <div className="ps-nav-label ps-nav-label-spaced">研究</div>
          {navItems.slice(5).filter((item) => !guest || item.href !== "/research/new").map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`ps-nav-link ${isActive(pathname, item.href) ? "active" : ""}`}
              onClick={() => setSidebarOpen(false)}
            >
              <span className="ps-nav-icon" aria-hidden>
                {item.icon}
              </span>
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="ps-sidebar-bottom">
          <div className={`ps-demo-note ${IS_REPLAY_MODE ? "" : "live"}`}>
            <strong>{modeLabel}</strong>
            <span>
              {IS_REPLAY_MODE
                ? "数据仅用于离线演示，不代表真实医药事实。"
                : "数据来自已配置的真实 API 来源。"}
            </span>
          </div>
          {!guest && (
            <>
              <Link
                href="/workspace"
                className={`ps-nav-link ${isActive(pathname, "/workspace") ? "active" : ""}`}
              >
                <span className="ps-nav-icon" aria-hidden>▦</span>
                <span>工作区与关联审核</span>
              </Link>
              <Link
                href="/settings"
                className={`ps-nav-link ${isActive(pathname, "/settings") ? "active" : ""}`}
              >
                <span className="ps-nav-icon" aria-hidden>⚙</span>
                <span>来源与设置</span>
              </Link>
            </>
          )}
          <div className="ps-user">
            <div className="ps-avatar">{userName.slice(0, 1)}</div>
            <div>
              <strong>{userName}</strong>
              <small>
                {guest ? "游客只读" : membership?.role || "未验证权限"} · {workspaceName}
              </small>
            </div>
            <button type="button" aria-label="退出登录" onClick={handleLogout}>
              ↪
            </button>
          </div>
        </div>
      </aside>

      <div className="ps-main-wrap">
        <header className="ps-topbar">
          <button
            className="ps-menu-button"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label="打开导航"
          >
            ☰
          </button>
          <div className="ps-breadcrumb">
            <span>{workspaceName}</span>
            <b>/</b>
            <strong>{title || "工作台"}</strong>
          </div>
          <div className="ps-top-actions">
            <Link className="ps-text-link" href="/drugs">
              搜索药物档案
            </Link>
            <span className={`ps-mode-badge ${IS_REPLAY_MODE ? "" : "live"}`}>
              <i /> {modeLabel}
            </span>
            <Link href="/inbox" className="ps-icon-button" aria-label="通知">
              ◌
            </Link>
            <div className="ps-top-avatar">{userName.slice(0, 1)}</div>
          </div>
        </header>

        <main className="ps-content">
          <div className={`ps-mode-banner ${IS_REPLAY_MODE ? "" : "live"}`}>
            <span>
              <i aria-hidden>ⓘ</i>{" "}
              {guest
                ? "游客只读模式 · 正在浏览管理员指定账号的演示数据"
                : IS_REPLAY_MODE
                  ? "当前为 REPLAY / DEMO 模式 · 所有对象均为虚构资料"
                  : "当前为 LIVE 模式 · 数据由 API 和已配置来源提供"}
            </span>
            {!guest && <Link href="/settings">查看数据范围与来源 →</Link>}
          </div>
          {guest && ["/research/new", "/workspace", "/settings"].includes(pathname) ? (
            <div className="ps-callout" role="status">
              游客只能浏览演示数据。请从左侧导航查看已有档案、变化、研究报告和订阅。
            </div>
          ) : (
            <>
              {(title || description || actions) && (
                <div className="ps-page-head">
                  <div>
                    <h1>{title}</h1>
                    {description && <p>{description}</p>}
                  </div>
                  {actions && <div className="ps-page-actions">{actions}</div>}
                </div>
              )}
              {children}
            </>
          )}
        </main>
      </div>
      {sidebarOpen && (
        <button
          className="ps-sidebar-overlay"
          aria-label="关闭导航"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}

export function StatusBadge({
  status,
  tone = "neutral",
}: {
  status: string;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  const icon =
    tone === "success"
      ? "✓"
      : tone === "warning"
        ? "!"
        : tone === "danger"
          ? "×"
          : tone === "info"
            ? "i"
            : "•";
  return (
    <span className={`ps-status ${tone}`}>
      <i aria-hidden>{icon}</i>
      {status}
    </span>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  icon,
  tone = "blue",
}: {
  label: string;
  value: ReactNode;
  detail: string;
  icon: string;
  tone?: string;
}) {
  return (
    <section className="ps-card ps-metric">
      <div className={`ps-metric-icon ${tone}`} aria-hidden>
        {icon}
      </div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </section>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="ps-empty">
      <div className="ps-empty-icon" aria-hidden>
        ⌁
      </div>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}

export function ApiErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = formatApiError(error);
  return (
    <div className="ps-empty ps-error-state" role="alert">
      <div className="ps-empty-icon" aria-hidden>
        !
      </div>
      <h3>数据加载失败</h3>
      <p>{message}</p>
      {error instanceof PharmaApiError && error.status === 401 && (
        <Link href="/login" className="ps-btn primary">
          前往登录
        </Link>
      )}
      <button
        type="button"
        className="ps-btn"
        onClick={onRetry || (() => window.location.reload())}
      >
        重试
      </button>
    </div>
  );
}
