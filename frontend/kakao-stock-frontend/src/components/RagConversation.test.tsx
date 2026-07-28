import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RagMessage } from '../types/qa'
import { RagConversation } from './RagConversation'

const send = vi.fn()
let messages: RagMessage[] = []

vi.mock('../hooks/useRagConversation', () => ({
  useRagConversation: () => ({
    abort: vi.fn(),
    messages,
    phase: 'idle',
    progress: '',
    retry: vi.fn(),
    send,
    stockContextError: null,
  }),
}))

describe('RagConversation selected text handoff', () => {
  beforeEach(() => {
    send.mockReset()
    messages = []
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('prefills the composer with the exact selected news text', () => {
    render(
      <RagConversation
        context={{
          stockCode: '005380',
          sourceType: 'news_event',
          sourceId: '77',
          selectedText: '구체적인 투자 규모와',
        }}
        variant="panel"
      />,
    )

    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value)
      .toBe('구체적인 투자 규모와')
  })

  it('lets the user extend the selected text before asking', () => {
    render(
      <RagConversation
        context={{
          stockCode: '005380',
          sourceType: 'news_event',
          sourceId: '77',
          selectedText: '구체적인 투자 규모와',
        }}
        variant="panel"
      />,
    )

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '구체적인 투자 규모와 실제 일정은?' },
    })
    fireEvent.click(screen.getByRole('button', { name: '질문 보내기' }))

    expect(send).toHaveBeenCalledWith('구체적인 투자 규모와 실제 일정은?')
  })

  it('moves the latest question to the top as soon as it is submitted', () => {
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0)
      return 1
    })
    messages = [
      {
        id: 'user-1',
        role: 'user',
        text: '가장 최근 호재는?',
        sources: [],
        visualizations: [],
        warnings: [],
      },
      {
        id: 'assistant-1',
        role: 'assistant',
        text: '',
        sources: [],
        visualizations: [],
        warnings: [],
        state: 'pending',
      },
    ]

    render(<RagConversation context={{ stockCode: '005930' }} variant="page" />)

    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'smooth' })
  })
})
