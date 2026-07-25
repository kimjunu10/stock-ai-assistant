import { useState } from 'react'
import { Icon } from '../components/Icon'
import { RagConversation } from '../components/RagConversation'
import { STOCKS } from '../data/mockData'

export function AskPage() {
  const [stockCode, setStockCode] = useState(STOCKS[0]?.code ?? '005930')
  const stock = STOCKS.find((item) => item.code === stockCode) ?? STOCKS[0]

  return (
    <main className="ask-page">
      <aside className="ask-sidebar">
        <div className="ask-sidebar__title"><Icon name="message" size={18} /><strong>Moa AI</strong></div>
        <div className="ask-sidebar__status"><i /><span>Agentic Hybrid RAG 연결</span></div>
        <div className="ask-sidebar__recent">
          <span>찾아보는 자료</span>
          <p>실제 주가와 DART 공식 수치</p>
          <p>사건 단위 뉴스와 공시</p>
          <p>증권사 리포트와 전망</p>
        </div>
        <div className="ask-sidebar__notice"><Icon name="info" size={16} /><p>AI 답변은 투자 권유가 아니며, 실제값과 전망값을 구분해 표시합니다.</p></div>
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

        {stock && (
          <RagConversation
            context={{ stockCode: stock.code, stockName: stock.name }}
            emptyTitle={`${stock.name}에 대해 무엇이 궁금한가요?`}
            key={stock.code}
            variant="page"
          />
        )}
      </section>
    </main>
  )
}
