/**
 * Typed client for the RebateLedger API, generated from the backend OpenAPI schema
 * (`make openapi`). The browser only calls same-origin `/api/v1/...` paths; Next.js
 * rewrites them to FastAPI. The CSRF token lives in memory only (never storage/URLs).
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "@/generated/api";

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token ?? null;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const csrf: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method) && csrfToken) {
      request.headers.set("X-CSRF-Token", csrfToken);
    }
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(csrf);

/**
 * RFC 9457 Problem Details as returned by every API error. This is the transport
 * error envelope (not a resource type), so it is declared here rather than generated.
 */
export interface Problem {
  type?: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  request_id?: string;
  errors?: { field: string; code: string; message: string }[];
  [extra: string]: unknown;
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }

  get code(): string {
    return this.problem.code;
  }

  /** Field-level messages keyed by field name, for react-hook-form setError. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.problem.errors ?? []) {
      if (e.field && !out[e.field]) out[e.field] = e.message;
    }
    return out;
  }
}

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && "code" in value && "status" in value;
}

/** Unwrap an openapi-fetch result: return data or throw ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok) return result.data as T;
  const err = result.error;
  if (isProblem(err)) throw new ApiError(err);
  throw new ApiError({
    title: "Something went wrong",
    status: result.response.status,
    code: result.response.status === 0 ? "NETWORK_ERROR" : "HTTP_ERROR",
    detail: "The request failed. Check your connection and try again.",
  });
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail || error.problem.title;
  return "Something went wrong. Try again.";
}

/** Fresh idempotency key for create-style POSTs (imports, runs, claims). */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}
