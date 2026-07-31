import type {
  Decision,
  ExportResult,
  HealthStatus,
  InspectionCase,
  VerificationResult,
} from "./types";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const value = payload as Record<string, unknown>;
  if (typeof value.message === "string") return value.message;
  if (typeof value.detail === "string") return value.detail;
  if (value.detail && typeof value.detail === "object") {
    const detail = value.detail as Record<string, unknown>;
    if (typeof detail.message === "string") return detail.message;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(!(init?.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const fallback = `${response.status} ${response.statusText}`;
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(errorMessage(payload, fallback), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function unwrapCases(payload: InspectionCase[] | { items: InspectionCase[] }): InspectionCase[] {
  return Array.isArray(payload) ? payload : payload.items;
}

export const api = {
  health: () => request<HealthStatus>("/health"),

  async listCases(): Promise<InspectionCase[]> {
    return unwrapCases(await request<InspectionCase[] | { items: InspectionCase[] }>("/cases"));
  },

  getCase: (caseId: string) => request<InspectionCase>(`/cases/${encodeURIComponent(caseId)}`),

  createCase: (partId: string, revision: string) =>
    request<InspectionCase>("/cases", {
      method: "POST",
      body: JSON.stringify({ part_id: partId, revision }),
    }),

  createDemo: () => request<InspectionCase>("/demo", { method: "POST", body: "{}" }),

  uploadReference(caseId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<InspectionCase>(`/cases/${encodeURIComponent(caseId)}/reference`, {
      method: "POST",
      body,
    });
  },

  uploadInspection(caseId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<InspectionCase>(`/cases/${encodeURIComponent(caseId)}/images`, {
      method: "POST",
      body,
    });
  },

  analyze: (caseId: string) =>
    request<InspectionCase>(`/cases/${encodeURIComponent(caseId)}/analyze`, {
      method: "POST",
      body: "{}",
    }),

  disposition: (caseId: string, decision: Decision, reviewer: string, note: string) =>
    request<InspectionCase>(`/cases/${encodeURIComponent(caseId)}/disposition`, {
      method: "POST",
      body: JSON.stringify({ decision, reviewer, note }),
    }),

  exportEvidence: (caseId: string) =>
    request<ExportResult>(`/cases/${encodeURIComponent(caseId)}/export`, {
      method: "POST",
      body: "{}",
    }),

  verifyEvidence: (bundlePath: string) =>
    request<VerificationResult>("/evidence/verify", {
      method: "POST",
      body: JSON.stringify({ bundle_path: bundlePath }),
    }),
};

