import type { ReportItem } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

interface ResearchReportResponse {
  stockCode: string
  items: ReportItem[]
  total: number
  offset: number
  limit: number
  hasMore: boolean
}

export async function fetchResearchReports(
  stockCode: string,
  signal: AbortSignal,
  limit = 8,
  offset = 0,
) {
  const response = await fetch(
    `${API_BASE_URL}/api/stocks/${stockCode}/reports?limit=${limit}&offset=${offset}`,
    { signal },
  )
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? '증권사 리포트를 불러오지 못했어요.')
  }
  return response.json() as Promise<ResearchReportResponse>
}
