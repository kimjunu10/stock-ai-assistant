import { describe, expect, it } from 'vitest'
import type { RagMessage } from '../types/qa'
import {
  completedConversationEventContext,
  completedConversationHistory,
} from './useRagConversation'

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

describe('completedConversationEventContext', () => {
  it('uses canonical source locators from only the latest completed answer', () => {
    expect(completedConversationEventContext([
      message('user', '뉴스 알려줘'),
      {
        ...message('assistant', '첫 답변', 'complete'),
        sources: [{
          sourceId: 'old',
          sourceType: 'news_event',
          stockCode: '005930',
          locator: { cluster_id: 1 },
        }],
      },
      message('user', '최근 공시는?'),
      {
        ...message('assistant', '최근 공시입니다.', 'complete'),
        sources: [{
          sourceId: 'chunk-r7',
          sourceType: 'dart_document',
          stockCode: '005930',
          title: '공급계약',
          publishedAt: '2026-07-22',
          locator: { rcept_no: 'R7' },
        }],
      },
    ])).toEqual([{
      eventId: 'R7',
      stockCode: '005930',
      publishedAt: '2026-07-22',
      title: '공급계약',
      sourceType: 'dart_document',
    }])
  })
})
