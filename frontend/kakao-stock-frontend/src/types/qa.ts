export type RagPhase =
  | 'idle'
  | 'connecting'
  | 'running'
  | 'streaming'
  | 'completed'
  | 'error'
  | 'aborted'

export type RagSourceType =
  | 'financial'
  | 'term'
  | 'news_event'
  | 'dart_document'
  | 'structured_disclosure'
  | 'research_report'
  | 'price'

export interface RagContext {
  stockCode?: string
  stockName?: string
  sourceType?: RagSourceType
  sourceId?: string
  documentId?: string
  page?: number
  title?: string
  selectedText?: string
}

export interface RagSource {
  sourceId: string
  sourceType: RagSourceType
  title?: string
  publisher?: string
  publishedAt?: string
  page?: number
  url?: string
  valueKind?: string
  locator: Record<string, unknown>
}

export type RagVisualizationType =
  | 'price_snapshot'
  | 'price_line'
  | 'event_return'
  | 'broker_targets'
  | 'financial_series'
  | 'financial_comparison'
  | 'disclosure_metrics'
  | 'event_timeline'
  | 'term_definition'

export interface RagVisualization {
  type: RagVisualizationType
  title: string
  data: Record<string, unknown>
  sourceIds: string[]
}

export interface RagMessage {
  id: string
  role: 'assistant' | 'user'
  text: string
  sources: RagSource[]
  visualizations: RagVisualization[]
  warnings: string[]
  state?: 'pending' | 'complete' | 'error' | 'aborted'
}

export interface QaStreamEvent {
  event: 'agent_start' | 'tool_start' | 'tool_end' | 'sources' | 'delta' | 'done' | 'error'
  data: Record<string, unknown>
}
