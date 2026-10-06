// Small fetch wrapper: JSON, CSRF header, error normalisation.

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

let csrfToken: string | null = null;
type Listener = (status: number, detail: string) => void;
const authListeners = new Set<Listener>();

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

/** Called for 401 (session expired) and 403 password_change_required. */
export function onAuthProblem(listener: Listener): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; ");
  }
  return fallback;
}

async function request<T>(method: string, url: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let resp: Response;
  try {
    resp = await fetch(url, { method, headers, body: payload, credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "Server nicht erreichbar. Bitte Verbindung prüfen.");
  }
  if (resp.status === 204) return undefined as T;
  const ctype = resp.headers.get("content-type") || "";
  const data = ctype.includes("application/json") ? await resp.json().catch(() => null) : await resp.text();
  if (!resp.ok) {
    const detail = detailOf(data, resp.statusText || `Fehler ${resp.status}`);
    if (resp.status === 401 || (resp.status === 403 && detail === "password_change_required")) {
      authListeners.forEach((l) => l(resp.status, detail));
    }
    throw new ApiError(resp.status, detail);
  }
  return data as T;
}

function withParams(url: string, params?: Record<string, unknown>): string {
  if (!params) return url;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `${url}?${s}` : url;
}

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) => request<T>("GET", withParams(url, params)),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  del: <T>(url: string) => request<T>("DELETE", url),
  upload: <T>(url: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", url, fd);
  },
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Unbekannter Fehler";
}
