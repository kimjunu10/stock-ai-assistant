import type { AssistantContext, MarketDataStatus, Stock, StockMarketData } from '../types'
import { AnimatedPrice } from './AnimatedPrice'
import { Icon } from './Icon'
import { StockAvatar } from './StockAvatar'

interface StockHeaderProps {
  isRefreshing: boolean
  marketData: StockMarketData | null
  marketDataStatus: MarketDataStatus
  onAsk: (context: AssistantContext) => void
  stock: Stock
}

const numberFormatter = new Intl.NumberFormat('ko-KR')

function formatSignedWon(value: number) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${numberFormatter.format(value)}원`
}

function formatAsOf(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    day: 'numeric',
    hour: '2-digit',
    hour12: false,
    minute: '2-digit',
    month: 'long',
    timeZone: 'Asia/Seoul',
  }).format(new Date(value))
}

export function StockHeader({ isRefreshing, marketData, marketDataStatus, onAsk, stock }: StockHeaderProps) {
  const quote = marketData?.quote
  const direction = !quote || quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down'
  const changeText = quote
    ? `어제보다 ${formatSignedWon(quote.change)} (${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%)`
    : marketDataStatus === 'loading' ? '실제 시세를 확인하고 있어요' : '시세를 불러오지 못했어요'

  return (
    <section className="stock-hero">
      <div className="stock-hero__overview">
        <div className="stock-hero__identity">
          <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="lg" />
          <div>
            <div className="stock-hero__labels">
              <span>{stock.market}</span>
              <span>{stock.sector}</span>
            </div>
            <div className="stock-hero__title">
              <h1>{stock.name}</h1>
              <span>{stock.code}</span>
            </div>
            <p>{stock.summary}</p>
          </div>
        </div>
        <div className="stock-hero__quote">
          <span className="sample-label">
            <i className={`live-dot${isRefreshing ? ' live-dot--refreshing' : ''}`} />
            {quote ? `LIVE · ${formatAsOf(quote.asOf)} 기준 · 15초 자동 갱신` : '토스증권 실제 시세'}
          </span>
          <div className="stock-hero__price-line">
            <AnimatedPrice value={quote?.price ?? null} />
            <span className={`quote-change quote-change--${direction}`}>
              {changeText}
            </span>
          </div>
        </div>
      </div>
      <div className="stock-hero__actions">
        <p>
          숫자만 보지 않아도 괜찮아요.
          <strong> 오늘 움직임과 뉴스가 왜 연결되는지 AI에게 바로 물어보세요.</strong>
        </p>
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
