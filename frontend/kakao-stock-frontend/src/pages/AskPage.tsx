import { useState, type FormEvent } from 'react'
import { STOCKS } from '../data/mockData'
import { Icon } from '../components/Icon'

interface ChatMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  sources?: string[]
}

const STARTER_QUESTIONS = [
  '최근 뉴스에서 가장 중요한 변화가 뭐야?',
  '이번 분기 영업이익이 변한 이유를 설명해줘',
  '최근 공시 중 초보자가 꼭 볼 내용은?',
  '호재와 리스크를 각각 정리해줘',
]

export function AskPage() {
  const [stockCode, setStockCode] = useState(STOCKS[0]?.code ?? '005930')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const stock = STOCKS.find((item) => item.code === stockCode) ?? STOCKS[0]

  const sendQuestion = (question: string) => {
    if (!question.trim() || !stock) return
    const timestamp = Date.now()
    setMessages((current) => [
      ...current,
      { id: timestamp, role: 'user', text: question.trim() },
      {
        id: timestamp + 1,
        role: 'assistant',
        text: `현재는 ${stock.name} 질문 화면의 UI 프로토타입입니다. 백엔드가 연결되면 뉴스·공시·리포트·재무 자료에서 근거를 먼저 찾고, 확인된 내용만 쉬운 말로 답변합니다. 매수·매도 추천이나 주가 예측은 하지 않습니다.`,
        sources: ['[1] 최근 뉴스 브리핑', '[2] 분기보고서'],
      },
    ])
    setInput('')
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    sendQuestion(input)
  }

  return (
    <main className="ask-page">
      <aside className="ask-sidebar">
        <div className="ask-sidebar__title"><Icon name="message" size={18} /><strong>질문 기록</strong></div>
        <button className="new-chat-button" onClick={() => setMessages([])} type="button"><span>＋</span> 새 질문</button>
        <div className="ask-sidebar__recent">
          <span>최근</span>
          <button type="button">반도체 실적 흐름 정리</button>
          <button type="button">최근 공시 핵심 내용</button>
          <button type="button">조선업 수주 뉴스 설명</button>
        </div>
        <div className="ask-sidebar__notice"><Icon name="info" size={16} /><p>AI 답변은 투자 권유가 아니며, 모든 핵심 문장에 출처를 표시합니다.</p></div>
      </aside>

      <section className="global-chat">
        <header className="global-chat__header">
          <div><span className="assistant-symbol" aria-hidden="true">M</span><div><strong>Moa AI</strong><span>자료를 찾아 근거와 함께 답해요</span></div></div>
          <label className="stock-select">
            <span>분석 종목</span>
            <select aria-label="질문할 종목" onChange={(event) => setStockCode(event.target.value)} value={stockCode}>
              {STOCKS.map((item) => <option key={item.code} value={item.code}>{item.name} · {item.code}</option>)}
            </select>
          </label>
        </header>

        <div className={messages.length === 0 ? 'global-chat__body is-empty' : 'global-chat__body'}>
          {messages.length === 0 ? (
            <div className="chat-welcome">
              <span className="chat-welcome__icon"><Icon name="message" size={26} /></span>
              <h1>{stock?.name}에 대해<br />무엇이 궁금한가요?</h1>
              <p>어려운 금융 용어부터 최근 뉴스와 공시의 의미까지,<br />확인된 자료 안에서 쉽게 설명해 드릴게요.</p>
              <div className="starter-grid">
                {STARTER_QUESTIONS.map((question) => <button key={question} onClick={() => sendQuestion(question)} type="button"><span>{question}</span><Icon name="arrow-right" size={17} /></button>)}
              </div>
            </div>
          ) : (
            <div className="chat-thread">
              {messages.map((message) => (
                <div className={`global-message global-message--${message.role}`} key={message.id}>
                  {message.role === 'assistant' && <span className="chat-avatar" aria-hidden="true">M</span>}
                  <div><p>{message.text}</p>{message.sources && <div className="source-chip-row">{message.sources.map((source) => <button className="source-chip" key={source} type="button"><Icon name="document" size={14} /> {source}</button>)}</div>}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <form className="global-composer" onSubmit={handleSubmit}>
          <div className="global-composer__box">
            <textarea aria-label={`${stock?.name ?? ''} 질문 입력`} onChange={(event) => setInput(event.target.value)} placeholder={`${stock?.name ?? '선택한 종목'}에 관해 질문해 보세요`} rows={2} value={input} />
            <div><span><Icon name="document" size={15} /> 뉴스 · 공시 · 리포트 · 재무에서 검색</span><button aria-label="질문 보내기" disabled={!input.trim()} type="submit"><Icon name="send" size={17} /></button></div>
          </div>
          <p>제공된 문서에서 확인되지 않는 내용은 모른다고 답해요. 투자 판단은 직접 해주세요.</p>
        </form>
      </section>
    </main>
  )
}
