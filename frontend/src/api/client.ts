// Typed access to our API. The types come from the backend's OpenAPI spec:  npm run gen:api
import type { components } from "./schema";

type S = components["schemas"];
export type Run = S["RunOut"];
export type Measurement = S["MeasurementOut"];
export type ImageItem = S["ImageOut"];
export type Nucleus = S["NucleusOut"];
export type SummaryRow = S["SummaryRow"];
export type Job = S["JobOut"];
export type Health = S["Health"];
export type UploadResult = S["UploadResult"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Every request carries this header; the API refuses changes without it (cross-site request protection).
const CSRF = { "X-Requested-With": "stemchub" };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, { ...init, headers: { ...CSRF, ...init.headers } });
  if (!res.ok) {
    const type = res.headers.get("content-type") ?? "";
    const detail = type.includes("json") ? (await res.json()).detail : "";
    const hint = res.status === 502 || res.status === 504 ? " — the API is not reachable (restarting?)" : "";
    const text = typeof detail === "string" && detail ? detail : `${res.status} ${res.statusText}${hint}`;
    throw new ApiError(res.status, text);
  }
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export type User = S["UserOut"];
export const ROLE_LEVEL: Record<string, number> = { viewer: 0, scientist: 1, admin: 2 };
export const can = (user: User | undefined, role: "scientist" | "admin") => !!user && ROLE_LEVEL[user.role] >= ROLE_LEVEL[role];

export const api = {
  health: () => request<Health>("/health"),
  runs: () => request<Run[]>("/runs"),
  run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
  measurements: (id: string) => request<Measurement[]>(`/runs/${encodeURIComponent(id)}/measurements`),
  images: (id: string) => request<ImageItem[]>(`/runs/${encodeURIComponent(id)}/images`),
  nuclei: (imageId: number) => request<Nucleus[]>(`/images/${imageId}/nuclei`),
  summary: () => request<SummaryRow[]>("/summary"),
  jobs: () => request<Job[]>("/jobs?limit=50"),
  sync: () => request<{ queued: string[] }>("/sync", { method: "POST" }),
  reprocess: (imageId: number) => request<{ queued: string[] }>(`/images/${imageId}/reprocess`, { method: "POST" }),
  // login
  me: () => request<User>("/auth/me"),
  login: (username: string, password: string) => request<User>("/auth/login", json("POST", { username, password })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/password", json("POST", { current_password, new_password })),
  users: () => request<User[]>("/users"),
  createUser: (username: string, password: string, role: string) => request<User>("/users", json("POST", { username, password, role })),
  updateUser: (id: number, patch: { role?: string; active?: boolean; password?: string }) =>
    request<User>(`/users/${id}`, json("PATCH", patch)),
};

export const imageUrls = (id: number) => ({
  thumbnail: `/api/images/${id}/thumbnail?size=320`,
  preview: `/api/images/${id}/preview`,
  mask: `/api/images/${id}/mask`,
});

/** Upload with progress (fetch cannot report upload progress, XMLHttpRequest can). */
export function uploadForm(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.setRequestHeader("X-Requested-With", "stemchub");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let body: { detail?: unknown } & Partial<UploadResult> = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON, e.g. a proxy error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else reject(new Error(typeof body.detail === "string" ? body.detail : `${xhr.status} ${xhr.statusText}`));
    };
    xhr.onerror = () => reject(new Error("Network error: is the app running?"));
    xhr.send(form);
  });
}

export const dayFolder = (day: number) => (day < 0 ? `day-${String(-day).padStart(2, "0")}` : `day${String(day).padStart(2, "0")}`);
