import type { NewsCluster } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

interface NewsClusterApiItem {
  id: number
  stockCode: string
  kind: 'company' | 'market' | 'info'
  title: string
  easyExplanation: string
  factualBody: string
  articleCount: number
  publishedAt: string
  sources: NonNullable<NewsCluster['sources']>
}

interface NewsClusterResponse {
  items: NewsClusterApiItem[]
  total: number
  offset: number
  limit: number
  hasMore: boolean
}

function uniquePresses(item: NewsClusterApiItem) {
  return [...new Set(item.sources.map((source) => source.press))]
}

export async function fetchNewsClusters(
  signal: AbortSignal,
  options: { limit?: number; offset?: number; stockCode?: string } = {},
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
  })
  if (options.stockCode) params.set('stock_code', options.stockCode)
  const response = await fetch(`${API_BASE_URL}/api/clusters?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? '뉴스 브리핑을 불러오지 못했어요.')
  }
  const payload = await response.json() as NewsClusterResponse
  const clusters = payload.items.map<NewsCluster>((item) => ({
    id: item.id,
    stockCode: item.stockCode,
    kind: item.kind,
    title: item.title,
    easySummary: item.easyExplanation,
    factualBody: item.factualBody,
    articleCount: item.articleCount,
    pressList: uniquePresses(item),
    publishedAt: item.publishedAt,
    sentiment: null,
    sentimentScore: null,
    sentimentReason: null,
    sources: item.sources,
  }))
  return { clusters, hasMore: payload.hasMore, total: payload.total }
}

export async function explainNewsSelection(clusterId: number, text: string) {
  const response = await fetch(`${API_BASE_URL}/api/clusters/explain-selection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clusterId, text }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? '선택한 문구를 설명하지 못했어요.')
  }
  return response.json() as Promise<{ explanation: string; selectedText: string }>
}
