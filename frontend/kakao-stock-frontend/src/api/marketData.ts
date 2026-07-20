import type { StockMarketData, StockMarketOverview } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

interface ApiErrorBody {
  detail?: string
}

export async function fetchStockMarketData(stockCode: string, signal: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/stocks/${stockCode}/market-data`, { signal })

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody
    throw new Error(body.detail ?? '실제 시세를 불러오지 못했어요.')
  }

  return response.json() as Promise<StockMarketData>
}

export async function fetchStockMarketOverview(signal: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/api/stocks/market-overview`, { signal })

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody
    throw new Error(body.detail ?? '실제 시세를 불러오지 못했어요.')
  }

  return response.json() as Promise<StockMarketOverview>
}
