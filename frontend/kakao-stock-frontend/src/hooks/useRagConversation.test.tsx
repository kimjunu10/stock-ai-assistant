import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRagConversation } from './useRagConversation'

afterEach(() => vi.restoreAllMocks())

describe('useRagConversation', () => {
  it('accumulates delta and tracks tool/source completion', async () => {
    const stream = [
      'event: agent_start\ndata: {}\n\n',
      'event: tool_start\ndata: {"name":"search_news"}\n\n',
      'event: tool_end\ndata: {"name":"search_news","status":"ok"}\n\n',
      'event: sources\ndata: {"sources":[{"source_id":"n1","source_type":"news_event","title":"뉴스","locator":{}}],"visualizations":[]}\n\n',
      'event: delta\ndata: {"text":"안녕"}\n\n',
      'event: delta\ndata: {"text":"하세요"}\n\n',
      'event: done\ndata: {"stop_reason":"completed"}\n\n',
    ].join('')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    const { result } = renderHook(() => useRagConversation({ stockCode: '005930' }))

    await act(async () => result.current.send('최근 뉴스는?'))

    await waitFor(() => expect(result.current.phase).toBe('completed'))
    expect(result.current.messages[1]?.text).toBe('안녕하세요')
    expect(result.current.messages[1]?.sources[0]?.sourceType).toBe('news_event')
    expect(result.current.messages[1]?.state).toBe('complete')
  })

  it('moves to aborted and remains reusable after cancellation', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const { result } = renderHook(() => useRagConversation({ stockCode: '005930' }))

    act(() => { void result.current.send('중단할 질문') })
    await waitFor(() => expect(result.current.phase).toBe('connecting'))
    act(() => result.current.abort())
    await waitFor(() => expect(result.current.phase).toBe('aborted'))
    expect(result.current.messages[1]?.state).toBe('aborted')
  })

  it.each([
    'STOCK_CONTEXT_MISMATCH',
    'UNSUPPORTED_STOCK',
    'MULTI_STOCK_NOT_SUPPORTED',
  ])('renders %s as a source-free assistant notice', async (errorCode) => {
    const notice = '현재 선택한 종목에서는 해당 요청에 답변할 수 없습니다.'
    const stream = [
      'event: sources\ndata: {"sources":[],"visualizations":[]}\n\n',
      `event: error\ndata: ${JSON.stringify({
        message: notice,
        stop_reason: 'blocked',
        error_code: errorCode,
      })}\n\n`,
    ].join('')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    const { result } = renderHook(() => useRagConversation({ stockCode: '005930' }))

    await act(async () => result.current.send('지원 범위를 벗어난 요청'))

    await waitFor(() => expect(result.current.phase).toBe('completed'))
    expect(result.current.stockContextError).toBe(errorCode)
    expect(result.current.messages[1]?.errorCode).toBe(errorCode)
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      text: notice,
      sources: [],
      visualizations: [],
      state: 'complete',
    })
  })

  it('keeps non-policy stream errors in the retryable error state', async () => {
    const stream = 'event: error\ndata: {"message":"internal","stop_reason":"error"}\n\n'
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    const { result } = renderHook(() => useRagConversation({ stockCode: '005930' }))

    await act(async () => result.current.send('일반 오류 요청'))

    await waitFor(() => expect(result.current.phase).toBe('error'))
    expect(result.current.messages[1]?.state).toBe('error')
    expect(result.current.messages[1]?.text).toBe('데이터를 불러오는 중 문제가 발생했습니다.')
  })
})
