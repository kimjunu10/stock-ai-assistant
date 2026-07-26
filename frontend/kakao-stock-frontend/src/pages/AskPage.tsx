import { useState } from 'react'
import { RagConversation } from '../components/RagConversation'
import { STOCKS } from '../data/mockData'

export function AskPage() {
  const [stockCode, setStockCode] = useState(STOCKS[0]?.code ?? '005930')
  const stock = STOCKS.find((item) => item.code === stockCode) ?? STOCKS[0]

  return (
    <main className="ask-page">
      <section className="global-chat">
        <header className="global-chat__header">
          <div><div><strong>Moa AI</strong><span>금융 자료를 근거로 답합니다</span></div></div>
          <label className="stock-select">
            <span>종목</span>
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
