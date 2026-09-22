"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useState } from "react";

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

  return (
    <div className="ps-app">
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
          <strong>示例研发中心 <span aria-hidden>⌄</span></strong>
        </div>
        <nav className="ps-nav">
          <div className="ps-nav-label">工作台</div>
          {navItems.slice(0, 5).map((item) => (
            <Link key={item.href} href={item.href} className={`ps-nav-link ${isActive(pathname, item.href) ? "active" : ""}`} onClick={() => setSidebarOpen(false)}>
              <span className="ps-nav-icon" aria-hidden>{item.icon}</span><span>{item.label}</span>
              {item.href === "/events" && <em>3</em>}
            </Link>
          ))}
          <div className="ps-nav-label ps-nav-label-spaced">研究</div>
          {navItems.slice(5).map((item) => (
            <Link key={item.href} href={item.href} className={`ps-nav-link ${isActive(pathname, item.href) ? "active" : ""}`} onClick={() => setSidebarOpen(false)}>
              <span className="ps-nav-icon" aria-hidden>{item.icon}</span><span>{item.label}</span>
              {item.href === "/inbox" && <em>2</em>}
            </Link>
          ))}
        </nav>
        <div className="ps-sidebar-bottom">
          <div className="ps-demo-note"><strong>DEMO 模式</strong><span>数据仅用于界面演示，不代表真实医药事实。</span></div>
          <Link href="/settings" className={`ps-nav-link ${isActive(pathname, "/settings") ? "active" : ""}`}><span className="ps-nav-icon" aria-hidden>⚙</span><span>来源与设置</span></Link>
          <div className="ps-user"><div className="ps-avatar">研</div><div><strong>研究员</strong><small>reader · 示例工作区</small></div><span aria-hidden>⋮</span></div>
        </div>
      </aside>

      <div className="ps-main-wrap">
        <header className="ps-topbar">
          <button className="ps-menu-button" onClick={() => setSidebarOpen((v) => !v)} aria-label="打开导航">☰</button>
          <div className="ps-breadcrumb"><span>示例研发中心</span><b>/</b><strong>{title || "工作台"}</strong></div>
          <div className="ps-top-actions">
            <label className="ps-global-search"><span aria-hidden>⌕</span><input aria-label="全局搜索" placeholder="搜索药物、试验或文献" /><kbd>⌘ K</kbd></label>
            <span className="ps-mode-badge"><i /> DEMO</span>
            <button className="ps-icon-button" aria-label="通知">◌<b>2</b></button>
            <div className="ps-top-avatar">研</div>
          </div>
        </header>

        <main className="ps-content">
          <div className="ps-mode-banner"><span><i aria-hidden>ⓘ</i> 当前为 DEMO 模式 · 所有示例对象均为虚构资料</span><Link href="/settings">查看数据范围与来源 →</Link></div>
          {(title || description || actions) && <div className="ps-page-head"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="ps-page-actions">{actions}</div>}</div>}
          {children}
        </main>
      </div>
      {sidebarOpen && <button className="ps-sidebar-overlay" aria-label="关闭导航" onClick={() => setSidebarOpen(false)} />}
    </div>
  );
}

export function StatusBadge({ status, tone = "neutral" }: { status: string; tone?: "neutral" | "success" | "warning" | "danger" | "info" }) {
  const icon = tone === "success" ? "✓" : tone === "warning" ? "!" : tone === "danger" ? "×" : tone === "info" ? "i" : "•";
  return <span className={`ps-status ${tone}`}><i aria-hidden>{icon}</i>{status}</span>;
}

export function MetricCard({ label, value, detail, icon, tone = "blue" }: { label: string; value: ReactNode; detail: string; icon: string; tone?: string }) {
  return <section className="ps-card ps-metric"><div className={`ps-metric-icon ${tone}`} aria-hidden>{icon}</div><span>{label}</span><strong>{value}</strong><small>{detail}</small></section>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className="ps-empty"><div className="ps-empty-icon" aria-hidden>⌁</div><h3>{title}</h3><p>{detail}</p>{action}</div>;
}
