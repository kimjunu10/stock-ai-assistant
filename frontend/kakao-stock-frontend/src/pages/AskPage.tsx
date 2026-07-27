import { useCallback, useRef, useState } from 'react'
import { Icon } from '../components/Icon'
import { RagConversation } from '../components/RagConversation'
import { STOCKS } from '../data/mockData'
import type { StockContextErrorCode } from '../types/qa'

export function AskPage() {
  const [stockCode, setStockCode] = useState(STOCKS[0]?.code ?? '005930')
  const [highlightStockSelect, setHighlightStockSelect] = useState(false)
  const stockSelectRef = useRef<HTMLSelectElement>(null)
  const stock = STOCKS.find((item) => item.code === stockCode) ?? STOCKS[0]
  const handleStockContextError = useCallback((code: StockContextErrorCode | null) => {
    const shouldHighlight = code === 'STOCK_CONTEXT_MISMATCH'
    setHighlightStockSelect(shouldHighlight)
    if (shouldHighlight) stockSelectRef.current?.focus()
  }, [])

  return (
    <main className="ask-page">
      <aside className="ask-sidebar">
        <div className="ask-sidebar__title"><Icon name="message" size={18} /><strong>Moa AI</strong></div>
        <div className="ask-sidebar__status"><i /><span>근거 자료 연결됨</span></div>
        <div className="ask-sidebar__recent">
          <span>확인하는 자료</span>
          <p>실시간 주가와 DART 공식 수치</p>
          <p>사건 단위 뉴스와 공시</p>
          <p>증권사 리포트와 전망</p>
        </div>
        <div className="ask-sidebar__notice"><Icon name="info" size={16} /><p>AI 답변은 투자 권유가 아니며, 실제 자료와 전망을 구분해 표시합니다.</p></div>
      </aside>

      <section className="global-chat">
        <header className="global-chat__header">
          <div className="global-chat__identity">
            <span aria-hidden="true" className="moa-chat-avatar">M</span>
            <div><strong>Moa AI</strong><span>금융 자료를 근거로 답합니다</span></div>
          </div>
          <label className={`stock-select${highlightStockSelect ? ' stock-select--attention' : ''}`}>
            <span>대화 종목</span>
            <select
              aria-label="질문할 종목"
              onChange={(event) => {
                setHighlightStockSelect(false)
                setStockCode(event.target.value)
              }}
              ref={stockSelectRef}
              value={stockCode}
            >
              {STOCKS.map((item) => <option key={item.code} value={item.code}>{item.name} · {item.code}</option>)}
            </select>
          </label>
        </header>

        {stock && (
          <RagConversation
            context={{ stockCode: stock.code, stockName: stock.name }}
            emptyTitle={`${stock.name}에 대해 무엇이 궁금한가요?`}
            key={stock.code}
            onStockContextError={handleStockContextError}
            variant="page"
          />
        )}
      </section>
    </main>
  )
}
