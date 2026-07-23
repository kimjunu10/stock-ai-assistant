export type Theme = 'light' | 'dark'

export type Sentiment = 'positive' | 'negative' | 'neutral'

export interface Stock {
  code: string
  name: string
  initials: string
  imageSrc: string
  market: 'KOSPI'
  sector: string
  price: string
  change: string
  changeRate: string
  direction: 'up' | 'down' | 'flat'
  marketCap: string
  volume: string
  summary: string
}

export interface PriceCandle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface StockQuote {
  price: number
  previousClose: number
  change: number
  changeRate: number
  currency: 'KRW'
  asOf: string
  volume: number
}

export interface OrderbookLevel {
  price: number
  volume: number
}

export interface StockMarketData {
  stockCode: string
  interval: '1d'
  period: '6m'
  adjusted: boolean
  source: string
  quote: StockQuote
  candles: PriceCandle[]
  intradayCandles: PriceCandle[]
  upperLimitPrice: number | null
  lowerLimitPrice: number | null
  asks: OrderbookLevel[]
  bids: OrderbookLevel[]
}

export interface StockListQuote {
  stockCode: string
  price: number
  previousClose: number
  change: number
  changeRate: number
  asOf: string
}

export interface StockMarketOverview {
  source: string
  quotes: StockListQuote[]
}

export type MarketDataStatus = 'loading' | 'ready' | 'error'

export interface Term {
  term: string
  easyDefinition: string
}

export interface NewsCluster {
  id: number
  stockCode: string
  kind?: 'company' | 'market' | 'info'
  title: string
  easySummary: string
  factualBody?: string
  sentiment?: Sentiment | null
  sentimentScore?: number | null
  sentimentPositiveScore?: number | null
  sentimentNeutralScore?: number | null
  sentimentNegativeScore?: number | null
  sentimentReason?: string | null
  articleCount: number
  pressList: string[]
  publishedAt: string
  sources?: NewsSource[]
  terms?: Term[]
}

export interface NewsSource {
  articleId: number
  title: string
  press: string
  url: string
  publishedAt: string
  description: string
  imageUrl?: string | null
}

export interface FinancialItem {
  account: string
  display: string
  yoyPct: number | null
  note: string
}

export interface DisclosureItem {
  id: number
  stockCode: string
  type: string
  title: string
  date: string
  source: string
  viewerUrl?: string
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
  selectedText?: string
  stockCode: string
  sourceType: 'news_cluster' | 'disclosure' | 'report' | 'stock'
  sourceId: string
  title: string
  presentation?: 'news_detail'
}
