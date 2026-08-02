import { useAuthStore } from '@/stores/authStore'
import { useForbiddenStore } from '@/stores/forbiddenStore'
import type { ApiErrorBody } from '@/types/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly forbidden: boolean
  readonly needed?: string
  readonly body?: unknown

  constructor(opts: {
    status: number
    code: string
    message: string
    forbidden?: boolean
    needed?: string
    body?: unknown
  }) {
    super(opts.message)
    this.name = 'ApiError'
    this.status = opts.status
    this.code = opts.code
    this.forbidden = Boolean(opts.forbidden)
    this.needed = opts.needed
    this.body = opts.body
  }
}

function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  const path = window.location.pathname
  if (path === '/login') return
  window.location.assign('/login')
}

function parseErrorPayload(data: unknown): {
  code: string
  message: string
  needed?: string
} {
  if (!data || typeof data !== 'object') {
    return { code: 'SYS_001', message: 'request_failed' }
  }
  const obj = data as Record<string, unknown>
  const err = obj.error as ApiErrorBody | undefined
  if (err && typeof err === 'object') {
    return {
      code: String(err.code || 'SYS_001'),
      message: String(err.message || 'request_failed'),
      needed:
        typeof err.detail === 'string'
          ? err.detail
          : undefined,
    }
  }
  const detail = obj.detail
  if (detail && typeof detail === 'object') {
    const d = detail as ApiErrorBody
    return {
      code: String(d.code || 'SYS_001'),
      message: String(d.message || 'request_failed'),
      needed: typeof d.detail === 'string' ? d.detail : undefined,
    }
  }
  if (typeof detail === 'string') {
    return { code: 'SYS_001', message: detail }
  }
  return { code: 'SYS_001', message: 'request_failed' }
}

export type ApiFetchInit = RequestInit & {
  /** 跳过自动附 key / 401 跳转（如登录探活） */
  skipAuth?: boolean
}

export async function apiFetch(
  path: string,
  init: ApiFetchInit = {},
): Promise<Response> {
  const { skipAuth, headers: initHeaders, ...rest } = init
  const headers = new Headers(initHeaders)

  if (!skipAuth) {
    const key = useAuthStore.getState().getActiveKey()
    if (!key) {
      redirectToLogin()
      throw new ApiError({
        status: 401,
        code: 'AUTH_001',
        message: 'missing_api_key',
      })
    }
    headers.set('X-API-Key', key)
  }

  if (rest.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(path, { ...rest, headers })

  if (res.status === 401 && !skipAuth) {
    useAuthStore.getState().clearActiveKey()
    redirectToLogin()
    let body: unknown
    try {
      body = await res.clone().json()
    } catch {
      body = undefined
    }
    const parsed = parseErrorPayload(body)
    throw new ApiError({
      status: 401,
      code: parsed.code || 'AUTH_001',
      message: parsed.message || 'unauthorized',
      body,
    })
  }

  if (res.status === 403) {
    let body: unknown
    try {
      body = await res.clone().json()
    } catch {
      body = undefined
    }
    const parsed = parseErrorPayload(body)
    const needed = parsed.needed || parsed.message
    useForbiddenStore.getState().setForbidden({
      code: parsed.code || 'AUTH_002',
      needed,
      message: parsed.message || 'forbidden',
      path,
      at: Date.now(),
    })
    throw new ApiError({
      status: 403,
      code: parsed.code || 'AUTH_002',
      message: parsed.message || 'forbidden',
      forbidden: true,
      needed,
      body,
    })
  }

  return res
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    const parsed = parseErrorPayload(body)
    throw new ApiError({
      status: res.status,
      code: parsed.code,
      message: parsed.message,
      body,
    })
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

export async function apiGet<T>(path: string, init?: ApiFetchInit): Promise<T> {
  const res = await apiFetch(path, { ...init, method: 'GET' })
  return readJson<T>(res)
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  init?: ApiFetchInit,
): Promise<T> {
  const res = await apiFetch(path, {
    ...init,
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return readJson<T>(res)
}
