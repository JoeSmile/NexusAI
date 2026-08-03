import { apiPost } from '@/api/http'
import type { RoleName } from '@/types/api'

export type AuthResponse = {
  api_key: string
  role: RoleName
  tenant_id: string
  user_id: string
}

export type RegisterBody = {
  username: string
  password: string
  display_name?: string
  role?: RoleName
}

export type LoginBody = {
  username: string
  password: string
}

/** POST /api/auth/register — 公开端点,skipAuth:true */
export function registerAccount(body: RegisterBody) {
  return apiPost<AuthResponse>('/api/auth/register', body, { skipAuth: true })
}

/** POST /api/auth/login — 公开端点,skipAuth:true */
export function loginAccount(body: LoginBody) {
  return apiPost<AuthResponse>('/api/auth/login', body, { skipAuth: true })
}
