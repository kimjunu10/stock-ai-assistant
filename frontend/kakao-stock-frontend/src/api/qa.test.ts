import { afterEach, describe, expect, it, vi } from 'vitest'
import { normalizeSources, normalizeVisualizations, parseSseBlock, streamQa } from './qa'

afterEach(() => vi.restoreAllMocks())

describe('QA SSE contract', () => {
  it('parses CRLF and multi-line data safely', () => {
    expect(parseSseBlock('event: delta\r\ndata: {"text":"안녕"}\r\n')).toEqual({
      event: 'delta',
      data: { text: '안녕' },
    })
    expect(parseSseBlock('event: internal\ndata: {}')).toBeNull()
    expect(parseSseBlock('event: delta\ndata: not-json')).toBeNull()
  })

  it('ignores unknown visualizations and charts without source ids', () => {
    expect(normalizeVisualizations([
      { type: 'invented_chart', title: '위험', data: {}, source_ids: ['s1'] },
      { type: 'price_line', title: '출처 없음', data: {}, source_ids: [] },
      { type: 'event_return', title: '검증됨', data: { return_pct: 2 }, source_ids: ['p1'] },
    ])).toEqual([{
      type: 'event_return',
      title: '검증됨',
      data: { return_pct: 2 },
      sourceIds: ['p1'],
    }])
  })

  it('normalizes only known source types and safe URLs', () => {
    const result = normalizeSources([
      { source_id: 'n1', source_type: 'news_event', stock_code: '005930', title: '뉴스', url: 'https://example.com/a', locator: {} },
      { source_id: 'x1', source_type: 'private_file', title: '내부 파일', url: 'file:///tmp/a' },
    ])
    expect(result).toHaveLength(1)
    expect(result[0]?.url).toBe('https://example.com/a')
    expect(result[0]?.stockCode).toBe('005930')
  })

  it('includes the current screen context in the request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      'event: done\ndata: {"stop_reason":"completed"}\n\n',
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    ))
    await streamQa('왜 중요해?', {
      stockCode: '005930',
      sourceType: 'research_report',
      sourceId: 'report-7',
      documentId: 'document-7',
      page: 3,
    }, new AbortController().signal, () => {})
    const init = fetchMock.mock.calls[0]?.[1]
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>
    expect(body).toMatchObject({
      stock_code: '005930',
      context_source_type: 'research_report',
      context_source_id: 'report-7',
      document_id: 'document-7',
      report_page: 3,
    })
  })
})
