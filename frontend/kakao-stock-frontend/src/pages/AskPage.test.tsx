import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskPage } from './AskPage'

afterEach(() => vi.restoreAllMocks())

describe('AskPage stock context safety', () => {
  it('shows the mismatch guidance, clears stock cards, and focuses the stock selector', async () => {
    const stream = [
      'event: agent_start\ndata: {}\n\n',
      'event: sources\ndata: {"sources":[],"visualizations":[]}\n\n',
      'event: error\ndata: {"message":"현재 삼성전자가 선택되어 있습니다.\\n현대차 정보를 확인하려면 종목을 현대차로 변경해 주세요.","stop_reason":"blocked","error_code":"STOCK_CONTEXT_MISMATCH"}\n\n',
    ].join('')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, { status: 200 }))
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0)
      return 1
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })

    render(<AskPage />)
    const input = screen.getByLabelText('삼성전자 AI 질문 입력')
    fireEvent.change(input, { target: { value: '현대차 올해 실적 알려줘' } })
    fireEvent.click(screen.getByLabelText('질문 보내기'))

    await screen.findByText(/종목을 현대차로 변경해 주세요/)
    const stockPicker = screen.getByLabelText('질문할 종목')
    await waitFor(() => expect(document.activeElement).toBe(stockPicker))
    expect(stockPicker.className).toContain('stock-select--attention')
    expect(screen.queryByText('삼성전자 재무')).toBeNull()
  })
})
