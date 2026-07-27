import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RagConversation } from './RagConversation'

const send = vi.fn()

vi.mock('../hooks/useRagConversation', () => ({
  useRagConversation: () => ({
    abort: vi.fn(),
    messages: [],
    phase: 'idle',
    progress: '',
    retry: vi.fn(),
    send,
    stockContextError: null,
  }),
}))

describe('RagConversation selected text handoff', () => {
  beforeEach(() => send.mockReset())
  afterEach(cleanup)

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
})
