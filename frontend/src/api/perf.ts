import { apiGet } from '@/api/http'

export async function perfMetrics() {
  return apiGet<Record<string, unknown>>('/performance/metrics')
}

export async function perfCacheStats() {
  return apiGet<Record<string, unknown>>('/performance/cache/stats')
}

export async function perfStreamsActive() {
  return apiGet<Record<string, unknown>>('/performance/streams/active')
}

export async function perfBenchmark() {
  return apiGet<Record<string, unknown>>('/performance/benchmark')
}
