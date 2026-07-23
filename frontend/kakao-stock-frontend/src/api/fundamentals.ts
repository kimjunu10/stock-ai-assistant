import type { DisclosureItem, FinancialItem, StockCompanyProfile } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

interface FinancialSummaryResponse {
  stockCode: string
  source: 'DART'
  items: FinancialItem[]
}

interface DisclosureSummaryResponse {
  stockCode: string
  source: 'DART'
  items: DisclosureItem[]
}

async function readError(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({})) as { detail?: string }
  return body.detail ?? fallback
}

export async function fetchFinancialSummary(stockCode: string, signal: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/stocks/${stockCode}/financial-summary`, { signal })
  if (!response.ok) throw new Error(await readError(response, 'DART 재무 데이터를 불러오지 못했어요.'))
  return response.json() as Promise<FinancialSummaryResponse>
}

export async function fetchDisclosures(stockCode: string, signal: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/stocks/${stockCode}/disclosures?limit=3`, { signal })
  if (!response.ok) throw new Error(await readError(response, 'DART 공시를 불러오지 못했어요.'))
  return response.json() as Promise<DisclosureSummaryResponse>
}

export async function fetchCompanyProfile(stockCode: string, signal: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/stocks/${stockCode}/company-profile`, { signal })
  if (!response.ok) throw new Error(await readError(response, '회사 기본 정보를 불러오지 못했어요.'))
  return response.json() as Promise<StockCompanyProfile>
}
