import type { AssistantContext, Stock } from '../types'
import { Icon } from './Icon'
import { StockAvatar } from './StockAvatar'

interface StockHeaderProps {
  onAsk: (context: AssistantContext) => void
  stock: Stock
}

export function StockHeader({ onAsk, stock }: StockHeaderProps) {
  return (
    <section className="stock-hero">
      <div className="stock-hero__identity">
        <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="lg" />
        <div>
          <div className="stock-hero__labels">
            <span>{stock.market}</span>
            <span>{stock.code}</span>
            <span>{stock.sector}</span>
          </div>
          <h1>{stock.name}</h1>
          <p>{stock.summary}</p>
        </div>
      </div>
      <div className="stock-hero__quote">
        <span className="sample-label">화면 구성용 샘플 · 전일 종가 기준</span>
        <strong>{stock.price}</strong>
        <span className={`quote-change quote-change--${stock.direction}`}>
          {stock.change} ({stock.changeRate})
        </span>
      </div>
      <div className="stock-hero__facts">
        <div><span>시가총액</span><strong>{stock.marketCap}</strong></div>
        <div><span>거래량</span><strong>{stock.volume}</strong></div>
        <button
          className="primary-button"
          onClick={() =>
            onAsk({
              stockCode: stock.code,
              sourceType: 'stock',
              sourceId: stock.code,
              title: `${stock.name} 전체 자료`,
            })
          }
          type="button"
        >
          <Icon name="message" size={17} />
          이 종목에 질문하기
        </button>
      </div>
    </section>
  )
}
