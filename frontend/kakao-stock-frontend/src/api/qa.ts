import type {
  QaStreamEvent,
  RagConversationRequest,
  RagContext,
  RagSource,
  RagSourceType,
  StockContextErrorCode,
  RagVisualization,
  RagVisualizationType,
} from '../types/qa'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

const SOURCE_TYPES = new Set<RagSourceType>([
  'financial',
  'term',
  'news_event',
  'dart_document',
  'structured_disclosure',
  'research_report',
  'price',
])

const VISUALIZATION_TYPES = new Set<RagVisualizationType>([
  'news_cards',
  'price_snapshot',
  'price_line',
  'event_return',
  'broker_targets',
  'financial_series',
  'financial_comparison',
  'disclosure_metrics',
  'event_timeline',
  'term_definition',
])

const STOCK_CONTEXT_ERROR_CODES = new Set<StockContextErrorCode>([
  'STOCK_CONTEXT_MISMATCH',
  'UNSUPPORTED_STOCK',
  'MULTI_STOCK_NOT_SUPPORTED',
])

export class QaStreamError extends Error {
  readonly code?: StockContextErrorCode

  constructor(message: string, code?: StockContextErrorCode) {
    super(message)
    this.name = 'QaStreamError'
    this.code = code
  }
}

export function stockContextErrorCode(value: unknown): StockContextErrorCode | undefined {
  return typeof value === 'string' && STOCK_CONTEXT_ERROR_CODES.has(value as StockContextErrorCode)
    ? value as StockContextErrorCode
    : undefined
}

export function parseSseBlock(block: string): QaStreamEvent | null {
  let event = ''
  const dataLines: string[] = []
  for (const line of block.replace(/\r/g, '').split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!event || dataLines.length === 0) return null
  try {
    const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
    if (!['agent_start', 'tool_start', 'tool_end', 'sources', 'delta', 'done', 'error'].includes(event)) {
      return null
    }
    return { event: event as QaStreamEvent['event'], data }
  } catch {
    return null
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

export function normalizeSources(value: unknown): RagSource[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => {
    const item = asRecord(entry)
    const sourceId = item.source_id
    const sourceType = item.source_type
    if (typeof sourceId !== 'string' || !SOURCE_TYPES.has(sourceType as RagSourceType)) return []
    return [{
      sourceId,
      sourceType: sourceType as RagSourceType,
      stockCode: typeof item.stock_code === 'string' ? item.stock_code : undefined,
      title: typeof item.title === 'string' ? item.title : undefined,
      publisher: typeof item.publisher === 'string' ? item.publisher : undefined,
      publishedAt: typeof item.published_at === 'string' ? item.published_at : undefined,
      page: typeof item.page === 'number' ? item.page : undefined,
      url: safeSourceUrl(item.url),
      valueKind: typeof item.value_kind === 'string' ? item.value_kind : undefined,
      locator: asRecord(item.locator),
    }]
  })
}

export function normalizeVisualizations(value: unknown): RagVisualization[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => {
    const item = asRecord(entry)
    const type = item.type
    const sourceIds = item.source_ids
    if (
      !VISUALIZATION_TYPES.has(type as RagVisualizationType)
      || typeof item.title !== 'string'
      || !Array.isArray(sourceIds)
      || sourceIds.some((id) => typeof id !== 'string')
    ) return []
    return [{
      type: type as RagVisualizationType,
      title: item.title,
      data: asRecord(item.data),
      sourceIds: sourceIds as string[],
    }]
  })
}

function safeSourceUrl(value: unknown) {
  if (typeof value !== 'string') return undefined
  try {
    const url = new URL(value, window.location.origin)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined
    return url.href
  } catch {
    return undefined
  }
}

async function readApiError(response: Response) {
  if (response.status === 503) return 'AI 질문 서비스를 잠시 사용할 수 없어요. 잠시 후 다시 시도해 주세요.'
  if (response.status === 408 || response.status === 504) return '답변 시간이 초과됐어요. 다시 시도해 주세요.'
  return '답변을 불러오는 중 문제가 발생했습니다.'
}

export async function streamQa(
  question: string,
  context: RagContext,
  conversation: RagConversationRequest,
  signal: AbortSignal,
  onEvent: (event: QaStreamEvent) => void,
) {
  const response = await fetch(`${API_BASE_URL}/api/qa/stream`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question,
      stock_code: context.stockCode,
      context_source_type: context.sourceType,
      context_source_id: context.sourceId,
      document_id: context.documentId,
      report_page: context.page,
      conversation_id: conversation.conversationId,
      history: conversation.history,
      stream: true,
    }),
    signal,
  })
  if (!response.ok) throw new Error(await readApiError(response))
  if (!response.body) throw new Error('스트리밍 응답을 읽을 수 없어요.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const parsed = parseSseBlock(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (parsed) onEvent(parsed)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  const parsed = parseSseBlock(buffer)
  if (parsed) onEvent(parsed)
}
