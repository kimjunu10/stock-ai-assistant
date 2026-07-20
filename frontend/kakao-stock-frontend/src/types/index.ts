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
