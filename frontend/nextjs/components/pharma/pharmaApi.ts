/** Both modes use the same authenticated API; only the replay server loads fixtures. */
export const PHARMA_API_BASE = (process.env.NEXT_PUBLIC_PHARMA_API_URL || "").replace(/\/$/, "");
export let IS_REPLAY_MODE = process.env.NEXT_PUBLIC_PHARMA_RUNTIME_MODE === "replay";
export type ApiErrorPayload = {
  code?: string;
  message?: string;
  request_id?: string;
  details?: unknown;
};
export class PharmaApiError extends Error {
  constructor(
    public status: number,
    public payload: ApiErrorPayload = {}
  ) {
    super(payload.message || `API 请求失败 (${status})`);
    this.name = "PharmaApiError";
  }
  get code() {
    return this.payload.code;
  }
  get requestId() {
    return this.payload.request_id;
  }
}
export function formatApiError(error: unknown): string {
  if (!(error instanceof PharmaApiError))
    return error instanceof Error ? error.message : "无法连接 API 服务";
  const messages: Record<number, string> = {
    401: "登录已过期，请重新登录",
    403: "没有执行此操作的权限",
    404: "请求的资源不存在",
    409: "请求与当前资源状态冲突",
    422: "请求参数无效",
  };
  return `${messages[error.status] || error.message} · ${error.code || error.status}${error.payload.message ? `：${error.payload.message}` : ""}${error.requestId ? `（request_id: ${error.requestId}）` : ""}`;
}
export type AuthMe = {
  user: { id: string; email?: string; display_name?: string; name?: string; is_guest?: boolean };
  memberships: Array<{
    workspace_id: string;
    workspace_name?: string;
    role: string;
    enabled?: boolean;
    workspace?: { name?: string };
  }>;
  csrf_token?: string;
  runtime_mode?: string;
  is_guest?: boolean;
};
export const isGuest = (auth: AuthMe | null | undefined) =>
  auth?.is_guest === true || auth?.user?.is_guest === true;
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const csrf = typeof window !== "undefined" ? sessionStorage.getItem("pharmascope_csrf") : null;
  if (csrf && !["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", csrf);
  let response: Response;
  try {
    response = await fetch(`${PHARMA_API_BASE}${path}`, {
      ...init,
      method,
      credentials: "include",
      headers,
      cache: "no-store",
    });
  } catch {
    throw new PharmaApiError(0, {
      code: "API_UNAVAILABLE",
      message: "API 服务不可用，请检查连接后重试",
    });
  }
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new PharmaApiError(response.status, {
      ...(data?.error ||
        (typeof data?.detail === "object" ? data.detail : { message: data?.detail })),
      request_id: data?.error?.request_id || response.headers.get("x-request-id"),
    });
  if (data?.csrf_token && typeof window !== "undefined")
    sessionStorage.setItem("pharmascope_csrf", data.csrf_token);
  return data as T;
}
export async function getRuntimeMode() {
  const health = await apiFetch<{ runtime_mode: string }>("/healthz");
  IS_REPLAY_MODE = ["replay", "demo"].includes(health.runtime_mode);
  return IS_REPLAY_MODE;
}
let authPromise: Promise<AuthMe> | undefined;
export function clearAuthCache() {
  authPromise = undefined;
}
export async function loginAsGuest() {
  clearAuthCache();
  return apiFetch<AuthMe>("/api/v1/auth/guest-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}
export async function loginWithPassword(email: string, password: string) {
  clearAuthCache();
  return apiFetch<AuthMe>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}
export function getAuthMe(): Promise<AuthMe> {
  if (!authPromise)
    authPromise = apiFetch<AuthMe>("/api/v1/auth/me")
      .then((auth) => {
        if (auth.runtime_mode) IS_REPLAY_MODE = ["replay", "demo"].includes(auth.runtime_mode);
        return auth;
      })
      .catch((error) => {
        authPromise = undefined;
        throw error;
      });
  return authPromise;
}
export async function logout() {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
  sessionStorage.removeItem("pharmascope_csrf");
  sessionStorage.removeItem("pharmascope_workspace");
  clearAuthCache();
}
export function selectWorkspace(id: string) {
  sessionStorage.setItem("pharmascope_workspace", id);
  window.location.assign("/");
}
export async function workspacePath(path = ""): Promise<string> {
  const auth = await getAuthMe();
  const requested =
    sessionStorage.getItem("pharmascope_workspace") || process.env.NEXT_PUBLIC_PHARMA_WORKSPACE_ID;
  const membership =
    auth.memberships.find((item) => item.workspace_id === requested && item.enabled !== false) ||
    auth.memberships.find((item) => item.enabled !== false);
  if (!membership)
    throw new PharmaApiError(403, { code: "WORKSPACE_REQUIRED", message: "账号尚未加入工作区" });
  return `/api/v1/workspaces/${encodeURIComponent(membership.workspace_id)}${path}`;
}
export async function workspaceFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const workspace = await workspacePath(path);
  const method = (init?.method || "GET").toUpperCase();
  if (isGuest(await getAuthMe()) && !["GET", "HEAD", "OPTIONS"].includes(method))
    throw new PharmaApiError(403, { code: "GUEST_READ_ONLY", message: "游客只能浏览演示数据" });
  return apiFetch<T>(workspace, init);
}
export const jsonBody = (
  body: unknown,
  method = "POST",
  headers?: Record<string, string>
): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json", ...headers },
  body: JSON.stringify(body),
});
export const mutationKey = () => crypto.randomUUID();
async function list<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const result: { items: T[]; next_cursor?: string | null } = await workspaceFetch(
      `${path}${path.includes("?") ? "&" : "?"}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`
    );
    items.push(...result.items);
    cursor = result.next_cursor || null;
  } while (cursor);
  return items;
}
export type SourceHealth = {
  source: string;
  enabled: boolean;
  configured: boolean;
  state: string;
  last_success_at: string | null;
  last_error_code: string | null;
};
export type SourceConfig = SourceHealth;
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
  current_projection?: {
    brief_title?: string;
    overall_status?: string;
    phase?: string[];
    enrollment?: number | null;
  };
};
export type Event = {
  id: string;
  record_id: string;
  category: string;
  title: string;
  updated_at: string;
  latest_revision_id: string | null;
};
export type Report = {
  id: string;
  title: string;
  state: string;
  updated_at: string;
  current_version_id: string | null;
  published_version_id: string | null;
  run_id?: string | null;
  created_by?: string;
};
export type Publication = {
  id: string;
  external_id: string;
  title?: string;
  source: string;
  updated_at: string;
  abstract?: string | null;
  is_demo?: boolean;
  current_projection?: any;
};
export type Schedule = {
  frequency: string;
  timezone: string;
  local_time: string;
  weekday?: number | null;
};
export type Subscription = {
  id: string;
  name: string;
  enabled: boolean;
  schedule: Schedule;
  revision: number;
  next_run_at: string | null;
  drug_ids: string[];
  channels?: string[];
};
export type InboxItem = {
  id: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
  report_id?: string;
  state?: string;
  channel?: string;
};
export type ResearchRun = {
  id: string;
  status: string;
  question: string;
  runtime_mode?: string;
  report_id?: string | null;
  stop_reason?: string | null;
  error_code?: string;
  error_message?: string;
  event_seq?: number;
  usage?: Record<string, unknown>;
  coverage?: unknown[];
  updated_at?: string;
};
const normalizeTrial = (trial: Trial): Trial => {
  const p: any = trial.current_projection || {};
  return {
    ...trial,
    current_projection: {
      ...p,
      brief_title: p.brief_title || p.title,
      overall_status: p.overall_status || p.status,
      phase: p.phase || p.phases,
      enrollment: typeof p.enrollment === "object" ? (p.enrollment?.count ?? null) : p.enrollment,
    },
  };
};
const normalizePublication = (p: Publication): Publication => ({
  ...p,
  title: p.title || p.current_projection?.title,
  abstract: p.abstract || p.current_projection?.abstract,
});
export const getDashboard = () => workspaceFetch<Dashboard>("/dashboard");
export const getDrugs = () => list<Drug>("/drugs");
export const getDrug = (id: string) => workspaceFetch<Drug>(`/drugs/${encodeURIComponent(id)}`);
export const createDrug = (body: unknown) => workspaceFetch<Drug>("/drugs", jsonBody(body));
export const getTrials = async () =>
  (
    await list<Trial>(
      `/trials${typeof window !== "undefined" && new URLSearchParams(window.location.search).get("drug_id") ? `?drug_id=${encodeURIComponent(new URLSearchParams(window.location.search).get("drug_id")!)}` : ""}`
    )
  ).map(normalizeTrial);
export const getTrial = async (id: string) =>
  normalizeTrial(await workspaceFetch<Trial>(`/trials/${encodeURIComponent(id)}`));
export const getPublications = async () =>
  (await list<Publication>("/publications")).map(normalizePublication);
export const getPublication = async (id: string) =>
  normalizePublication(
    await workspaceFetch<Publication>(`/publications/${encodeURIComponent(id)}`)
  );
export const getEvents = () =>
  list<Event>(
    `/events${typeof window !== "undefined" && new URLSearchParams(window.location.search).get("drug_id") ? `?drug_id=${encodeURIComponent(new URLSearchParams(window.location.search).get("drug_id")!)}` : ""}`
  );
export const getEvent = (id: string) => workspaceFetch<Event>(`/events/${encodeURIComponent(id)}`);
export const getReports = () => list<Report>("/reports");
export const getReport = (id: string) =>
  workspaceFetch<Report>(`/reports/${encodeURIComponent(id)}`);
export async function getReportVersion(reportId: string, versionId?: string) {
  const r = await getReport(reportId);
  const id = versionId || r.current_version_id || r.published_version_id;
  return id
    ? workspaceFetch<any>(
        `/reports/${encodeURIComponent(reportId)}/versions/${encodeURIComponent(id)}`
      )
    : null;
}
export async function submitReportReview(
  reportId: string,
  decision: "approve" | "request_changes",
  note: string
) {
  const v = await getReportVersion(reportId);
  return workspaceFetch(
    `/reports/${encodeURIComponent(reportId)}/reviews`,
    jsonBody({
      version_id: v.id,
      content_hash: v.content_hash,
      decision: decision === "request_changes" ? "reject" : "approve",
      note,
    })
  );
}
export const getSubscriptions = () => list<Subscription>("/subscriptions");
export const getInbox = () => list<InboxItem>("/inbox");
export const markInboxRead = (id: string) =>
  workspaceFetch<InboxItem>(`/inbox/${encodeURIComponent(id)}/read`, { method: "POST" });
export const getSources = () => list<SourceConfig>("/sources");
export const getResearchRuns = () => list<ResearchRun>("/research/runs");
export const getResearchRun = (id: string) =>
  workspaceFetch<ResearchRun>(`/research/runs/${encodeURIComponent(id)}`);
export const cancelResearchRun = (id: string) =>
  workspaceFetch<ResearchRun>(`/research/runs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
export const retryResearchRun = (id: string) =>
  workspaceFetch<ResearchRun>(
    `/research/runs/${encodeURIComponent(id)}/retry`,
    jsonBody({}, "POST", { "Idempotency-Key": mutationKey() })
  );
const researchRequests = new Map<string, unknown>();
export async function createResearchRun(
  question: string,
  drugIds: string[],
  options?: {
    timeRangeDays?: number;
    idempotencyKey?: string;
    sources?: string[];
    budget?: { max_tool_calls: number; max_model_calls: number; max_records: number };
  }
) {
  const end = new Date();
  const start = new Date(end.getTime() - (options?.timeRangeDays || 30) * 86400000);
  const key = options?.idempotencyKey || mutationKey();
  if (!researchRequests.has(key)) {
    if (researchRequests.size > 20) researchRequests.clear();
    researchRequests.set(key, {
      question,
      drug_ids: drugIds,
      time_range: {
        start: start.toISOString(),
        end_exclusive: end.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
      source_allowlist: options?.sources || ["ctgov", "pubmed"],
      budget: options?.budget || { max_tool_calls: 20, max_model_calls: 4, max_records: 100 },
    });
  }
  return workspaceFetch<ResearchRun>(
    "/research/runs",
    jsonBody(researchRequests.get(key), "POST", { "Idempotency-Key": key })
  );
}
