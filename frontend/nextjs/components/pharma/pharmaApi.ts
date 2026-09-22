export const PHARMA_API_BASE = process.env.NEXT_PUBLIC_PHARMA_API_URL || "http://localhost:8000";
export const PHARMA_WORKSPACE_ID = process.env.NEXT_PUBLIC_PHARMA_WORKSPACE_ID || "dee59b72-2cb2-5255-934c-b44a3fd8911c";

export type SourceHealth = {
  source: string;
  enabled: boolean;
  configured: boolean;
  state: "healthy" | "degraded" | "unavailable" | "unknown";
  last_success_at: string | null;
  last_error_code: string | null;
};

export type Dashboard = {
  watched_drugs: number;
  events_last_7_days: number;
  pending_reviews: number;
  source_health: SourceHealth[];
  as_of: string;
  is_demo: boolean;
};

export type Drug = {
  id: string;
  display_name: string;
  development_code: string;
  description: string;
  indications: string[];
  targets: string[];
  revision: number;
  archived: boolean;
  updated_at: string;
  is_demo?: boolean;
};

export type Trial = {
  id: string;
  external_id: string;
  source: string;
  updated_at: string;
  is_demo: boolean;
  current_projection?: { brief_title?: string; overall_status?: string; phase?: string[]; enrollment?: number | null };
};

export type Event = {
  id: string;
  record_id: string;
  category: string;
  title: string;
  updated_at: string;
  latest_revision_id: string | null;
};

export type Report = { id: string; title: string; state: string; updated_at: string; current_version_id: string | null; published_version_id: string | null };

const demoDashboard: Dashboard = {
  watched_drugs: 4,
  events_last_7_days: 3,
  pending_reviews: 1,
  as_of: "2026-09-18T08:00:00Z",
  is_demo: true,
  source_health: [
    { source: "clinicaltrials_gov", enabled: true, configured: true, state: "healthy", last_success_at: "2026-09-18T07:42:00Z", last_error_code: null },
    { source: "pubmed", enabled: true, configured: true, state: "healthy", last_success_at: "2026-09-18T07:38:00Z", last_error_code: null },
  ],
};

export const demoDrugs: Drug[] = [
  { id: "dd1dcb81-e4b6-5343-b4a6-544bf716d867", display_name: "PX-101", development_code: "PX-101", description: "虚构研发对象，仅用于界面演示", indications: ["未设置研究标签"], targets: ["未设置"], revision: 2, archived: false, updated_at: "2026-09-18T08:00:00Z", is_demo: true },
  { id: "8e1711c8-5516-5478-8df2-4c0f3352776f", display_name: "PX-202", development_code: "PX-202", description: "虚构研发对象，仅用于界面演示", indications: ["未设置研究标签"], targets: ["未设置"], revision: 1, archived: false, updated_at: "2026-09-16T08:00:00Z", is_demo: true },
  { id: "drug-demo-303", display_name: "PX-303", development_code: "PX-303", description: "虚构研发对象，仅用于界面演示", indications: ["未设置研究标签"], targets: ["未设置"], revision: 1, archived: false, updated_at: "2026-09-15T08:00:00Z", is_demo: true },
];

export const demoTrials: Trial[] = [
  { id: "trial-demo-001", external_id: "DEMO-CT-001", source: "clinicaltrials_gov", updated_at: "2026-09-18T08:00:00Z", is_demo: true, current_projection: { brief_title: "PX-101 虚构登记研究", overall_status: "ACTIVE_NOT_RECRUITING", phase: ["PHASE2"], enrollment: 120 } },
  { id: "trial-demo-002", external_id: "DEMO-CT-002", source: "clinicaltrials_gov", updated_at: "2026-09-16T08:00:00Z", is_demo: true, current_projection: { brief_title: "PX-202 虚构方案研究", overall_status: "RECRUITING", phase: ["PHASE1"], enrollment: 80 } },
];

export const demoEvents: Event[] = [
  { id: "event-demo-01", record_id: "trial-demo-001", category: "enrollment_change", title: "目标入组人数从 160 更正为 150", updated_at: "2026-09-17T08:00:00Z", latest_revision_id: "revision-demo-03" },
  { id: "event-demo-02", record_id: "trial-demo-001", category: "status_change", title: "登记状态：RECRUITING → ACTIVE_NOT_RECRUITING", updated_at: "2026-09-16T08:00:00Z", latest_revision_id: "revision-demo-02" },
  { id: "event-demo-03", record_id: "trial-demo-001", category: "enrollment_change", title: "目标入组人数从 120 调整为 160", updated_at: "2026-09-16T08:00:00Z", latest_revision_id: "revision-demo-01" },
];

export const demoReports: Report[] = [
  { id: "report-demo-001", title: "PX-101 临床登记变化摘要", state: "in_review", updated_at: "2026-09-18T08:00:00Z", current_version_id: "version-demo-001", published_version_id: null },
  { id: "report-demo-002", title: "PX-202 资料范围说明", state: "published", updated_at: "2026-09-16T08:00:00Z", current_version_id: "version-demo-002", published_version_id: "version-demo-002" },
];

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const method = (init?.method || "GET").toUpperCase();
    const csrf = typeof window !== "undefined" ? window.sessionStorage.getItem("pharmascope_csrf") : null;
    const headers: Record<string, string> = { Accept: "application/json", ...((init?.headers || {}) as Record<string, string>) };
    if (csrf && !["GET", "HEAD", "OPTIONS"].includes(method)) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(`${PHARMA_API_BASE}${path}`, { ...init, method, credentials: "include", headers, cache: "no-store" });
    if (!response.ok) return null;
    const data = (await response.json()) as T & { csrf_token?: string };
    if (data && typeof data === "object" && data.csrf_token && typeof window !== "undefined") window.sessionStorage.setItem("pharmascope_csrf", data.csrf_token);
    return data as T;
  } catch {
    return null;
  }
}

export async function getDashboard(): Promise<Dashboard> {
  return (await apiFetch<Dashboard>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/dashboard`)) || demoDashboard;
}

export async function getDrugs(): Promise<Drug[]> {
  const response = await apiFetch<{ items: Drug[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/drugs?limit=50`);
  return response?.items || demoDrugs;
}

export async function getTrials(): Promise<Trial[]> {
  const response = await apiFetch<{ items: Trial[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/trials?limit=50`);
  return response?.items?.map((trial) => {
    const projection: any = trial.current_projection || {};
    return { ...trial, current_projection: {
      ...projection,
      brief_title: projection.brief_title || projection.title,
      overall_status: projection.overall_status || projection.status,
      phase: projection.phase || projection.phases,
      enrollment: typeof projection.enrollment === "object" ? projection.enrollment?.count ?? null : projection.enrollment,
    }};
  }) || demoTrials;
}

export async function getEvents(): Promise<Event[]> {
  const response = await apiFetch<{ items: Event[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/events?limit=50`);
  return response?.items || demoEvents;
}
export async function getEvent(id: string): Promise<Event> {
  return (await apiFetch<Event>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/events/${encodeURIComponent(id)}`)) || demoEvents.find((item) => item.id === id) || demoEvents[0];
}
export async function getDrug(id: string): Promise<Drug> {
  return (await apiFetch<Drug>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/drugs/${encodeURIComponent(id)}`)) || demoDrugs.find((item) => item.id === id) || demoDrugs[0];
}
export async function getTrial(id: string): Promise<Trial> {
  const trial = await apiFetch<Trial>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/trials/${encodeURIComponent(id)}`);
  if (!trial) return demoTrials.find((item) => item.id === id) || demoTrials[0];
  const projection: any = trial.current_projection || {};
  return { ...trial, current_projection: { ...projection, brief_title: projection.brief_title || projection.title, overall_status: projection.overall_status || projection.status, phase: projection.phase || projection.phases, enrollment: typeof projection.enrollment === "object" ? projection.enrollment?.count ?? null : projection.enrollment } };
}
export async function getReport(id: string): Promise<Report> {
  return (await apiFetch<Report>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/reports/${encodeURIComponent(id)}`)) || demoReports.find((item) => item.id === id) || demoReports[0];
}

export async function getReports(): Promise<Report[]> {
  const response = await apiFetch<{ items: Report[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/reports?limit=50`);
  return response?.items || demoReports;
}

export type Publication = { id: string; external_id: string; title?: string; source: string; updated_at: string; abstract?: string | null; is_demo?: boolean };
export type Subscription = { id: string; name: string; enabled: boolean; frequency: string; timezone: string; next_run_at: string | null; drug_ids: string[] };
export type InboxItem = { id: string; title: string; body: string; read_at: string | null; created_at: string };
export type SourceConfig = SourceHealth;

export const demoPublications: Publication[] = [
  { id: "pub-demo-001", external_id: "DEMO-PM-001", title: "PX-101 虚构方案研究：登记资料说明", source: "pubmed", updated_at: "2026-09-16T08:00:00Z", abstract: "该合成摘要仅用于界面测试，不包含疗效或安全性证据。", is_demo: true },
  { id: "pub-demo-002", external_id: "DEMO-PM-002", title: "试验登记变化的版本化观察方法", source: "pubmed", updated_at: "2026-09-14T08:00:00Z", abstract: "示例文献元数据，摘要范围由来源快照决定。", is_demo: true },
];
export const demoSubscriptions: Subscription[] = [{ id: "subscription-demo-001", name: "PX-101 每周登记变化", enabled: true, frequency: "weekly", timezone: "Asia/Shanghai", next_run_at: "2026-09-21T01:00:00Z", drug_ids: [demoDrugs[0].id] }];
export const demoInbox: InboxItem[] = [{ id: "delivery-demo-001", title: "报告待审核：PX-101 临床登记变化摘要", body: "报告 v1 已生成，等待独立审核员核对证据。", read_at: null, created_at: "2026-09-18T08:40:00Z" }, { id: "delivery-demo-002", title: "来源同步完成", body: "ClinicalTrials.gov 样例适配器已完成本次同步。", read_at: "2026-09-18T07:20:00Z", created_at: "2026-09-18T07:20:00Z" }];

export async function getPublications(): Promise<Publication[]> {
  const response = await apiFetch<{ items: Publication[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/publications?limit=50`);
  return response?.items || demoPublications;
}
export async function getSubscriptions(): Promise<Subscription[]> {
  const response = await apiFetch<{ items: Subscription[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/subscriptions?limit=50`);
  return response?.items || demoSubscriptions;
}
export async function getInbox(): Promise<InboxItem[]> {
  const response = await apiFetch<{ items: InboxItem[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/inbox?limit=50`);
  return response?.items || demoInbox;
}
export async function getSources(): Promise<SourceConfig[]> {
  const response = await apiFetch<{ items: SourceConfig[] }>(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/sources`);
  return response?.items?.map((source) => ({ ...source, state: source.state || (source as any).status || "unknown" })) || demoDashboard.source_health;
}

export async function createResearchRun(question: string, drugIds: string[]) {
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
  return apiFetch(`/api/v1/workspaces/${PHARMA_WORKSPACE_ID}/research/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      drug_ids: drugIds,
      time_range: { start: start.toISOString(), end_exclusive: end.toISOString(), timezone: "UTC" },
      source_allowlist: ["ctgov", "pubmed"],
      budget: { max_tool_calls: 20, max_model_calls: 4, max_records: 100 },
    }),
  });
}
