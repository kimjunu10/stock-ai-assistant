export type Theme = 'light' | 'dark'

export type Sentiment = 'positive' | 'negative' | 'neutral'

export interface Stock {
  code: string
  name: string
  initials: string
  imageSrc: string
  market: 'KOSPI'
  tradingViewSymbol: string
  sector: string
  price: string
  change: string
  changeRate: string
  direction: 'up' | 'down' | 'flat'
  marketCap: string
  volume: string
  summary: string
}

export interface Term {
  term: string
  easyDefinition: string
}

export interface NewsCluster {
  id: number
  stockCode: string
  title: string
  easySummary: string
  sentiment: Sentiment
  sentimentScore: number
  sentimentReason: string
  articleCount: number
  pressList: string[]
  publishedAt: string
  terms?: Term[]
}

export interface FinancialItem {
  account: string
  display: string
  yoyPct: number
  note: string
}

export interface DisclosureItem {
  id: number
  stockCode: string
  type: string
  title: string
  date: string
  source: string
}

export interface ReportItem {
  id: number
  stockCode: string
  broker: string
  title: string
  date: string
  opinion: string
}

export interface AssistantContext {
  stockCode: string
  sourceType: 'news_cluster' | 'disclosure' | 'report' | 'stock'
  sourceId: string
  title: string
}
