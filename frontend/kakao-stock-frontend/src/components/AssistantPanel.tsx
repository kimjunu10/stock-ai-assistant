import { useState, type FormEvent } from 'react'
import { getStock } from '../data/mockData'
import type { AssistantContext } from '../types'
import { Icon } from './Icon'

interface AssistantPanelProps {
  context: AssistantContext | null
  onClose: () => void
  open: boolean
}

export function AssistantPanel({ context, onClose, open }: AssistantPanelProps) {
  const [input, setInput] = useState('')
  const [question, setQuestion] = useState<string | null>(null)
  const stock = context ? getStock(context.stockCode) : undefined

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim()) return
    setQuestion(input.trim())
    setInput('')
  }

  return (
    <>
      {open && <button aria-label="AI 패널 닫기" className="panel-scrim" onClick={onClose} type="button" />}
      <aside aria-hidden={!open} aria-label="문서에 관해 AI에게 질문" className={open ? 'assistant-panel is-open' : 'assistant-panel'}>
        <header className="assistant-panel__header">
          <div>
            <span className="assistant-symbol" aria-hidden="true">M</span>
            <div>
              <strong>Moa AI</strong>
              <span>문서 근거로 답변해요</span>
            </div>
          </div>
          <button aria-label="패널 닫기" className="icon-button" onClick={onClose} type="button">
            <Icon name="close" size={19} />
          </button>
        </header>

        <div className="assistant-panel__content">
          {context && (
            <div className="context-card">
              <span>{stock?.name ?? context.stockCode}에서 보고 있던 내용</span>
              <strong>{context.title}</strong>
              <small>이 문서를 우선 근거로 찾아볼게요.</small>
            </div>
          )}

          <div className="chat-message chat-message--assistant">
            <span className="chat-avatar" aria-hidden="true">M</span>
            <div>
              <p>이 내용에서 무엇이 궁금한가요?</p>
              <p>어려운 용어, 실적 영향, 관련 공시를 쉽게 설명해 드릴게요.</p>
            </div>
          </div>

          <div className="question-suggestions">
            {['왜 호재로 분류됐어?', '실적에는 어떤 영향이 있어?', '관련 공시도 찾아줘'].map((suggestion) => (
              <button key={suggestion} onClick={() => setInput(suggestion)} type="button">
                {suggestion}
              </button>
            ))}
          </div>

          {question && (
            <>
              <div className="chat-message chat-message--user"><p>{question}</p></div>
              <div className="chat-message chat-message--assistant">
                <span className="chat-avatar" aria-hidden="true">M</span>
                <div>
                  <p>현재는 UI 프로토타입이에요. 백엔드 연결 후 선택한 문서와 같은 종목의 자료만 근거로 답변이 표시됩니다.</p>
                  <div className="source-chip"><Icon name="document" size={14} /> [1] 선택한 문서</div>
                </div>
              </div>
            </>
          )}
        </div>

        <form className="assistant-composer" onSubmit={handleSubmit}>
          <div>
            <textarea
              aria-label="질문 입력"
              onChange={(event) => setInput(event.target.value)}
              placeholder="이 내용에 관해 질문해 보세요"
              rows={2}
              value={input}
            />
            <button aria-label="질문 보내기" disabled={!input.trim()} type="submit">
              <Icon name="send" size={17} />
            </button>
          </div>
          <p>투자 판단·매수/매도 추천은 제공하지 않아요.</p>
        </form>
      </aside>
    </>
  )
}
