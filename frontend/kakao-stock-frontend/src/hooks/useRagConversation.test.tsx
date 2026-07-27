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

  it('renders a stock context block as a source-free assistant notice', async () => {
    const stream = [
      'event: agent_start\ndata: {}\n\n',
      'event: sources\ndata: {"sources":[{"source_id":"005930/2025","source_type":"financial","stock_code":"005930","locator":{}}],"visualizations":[{"type":"financial_series","title":"삼성전자 재무","data":{},"source_ids":["005930/2025"]}]}\n\n',
      'event: error\ndata: {"message":"현재 애플은 지원하지 않는 종목입니다.\\n지원 종목을 선택한 뒤 다시 질문해 주세요.","stop_reason":"blocked","error_code":"UNSUPPORTED_STOCK"}\n\n',
    ].join('')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    const { result } = renderHook(() => useRagConversation({ stockCode: '005930' }))

    await act(async () => result.current.send('애플 올해 실적'))

    await waitFor(() => expect(result.current.phase).toBe('completed'))
    expect(result.current.stockContextError).toBe('UNSUPPORTED_STOCK')
    expect(result.current.messages[1]?.errorCode).toBe('UNSUPPORTED_STOCK')
    expect(result.current.messages[1]?.state).toBe('complete')
    expect(result.current.messages[1]?.sources).toEqual([])
    expect(result.current.messages[1]?.visualizations).toEqual([])
    expect(result.current.messages[1]?.text).toContain('지원하지 않는 종목')
  })
})
