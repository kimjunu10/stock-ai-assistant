import { describe, expect, it } from 'vitest'
import type { RagMessage } from '../types/qa'
import { completedConversationHistory } from './useRagConversation'

function message(
  role: RagMessage['role'],
  text: string,
  state?: RagMessage['state'],
): RagMessage {
  return { id: `${role}-${text}`, role, text, sources: [], visualizations: [], warnings: [], state }
}

describe('completedConversationHistory', () => {
  it('sends only completed turns so follow-up questions retain the same conversation', () => {
    expect(completedConversationHistory([
      message('user', '호재야?'),
      message('assistant', '이 뉴스는 수주 확대 측면에서 호재입니다.', 'complete'),
      message('user', '왜?'),
      message('assistant', '', 'pending'),
    ])).toEqual([
      { role: 'user', content: '호재야?' },
      { role: 'assistant', content: '이 뉴스는 수주 확대 측면에서 호재입니다.' },
    ])
  })

  it('keeps at most the latest ten completed turns', () => {
    const messages = Array.from({ length: 12 }, (_, index) => [
      message('user', `질문 ${index}`),
      message('assistant', `답변 ${index}`, 'complete'),
    ]).flat()

    const history = completedConversationHistory(messages)

    expect(history).toHaveLength(20)
    expect(history[0]).toEqual({ role: 'user', content: '질문 2' })
    expect(history.at(-1)).toEqual({ role: 'assistant', content: '답변 11' })
  })
})
