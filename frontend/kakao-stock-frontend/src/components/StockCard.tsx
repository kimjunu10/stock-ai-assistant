import type { Stock, StockListQuote } from '../types'
import { AnimatedPrice } from './AnimatedPrice'
import { AppLink, type Navigate } from './AppLink'
import { Icon } from './Icon'
import { StockAvatar } from './StockAvatar'

interface StockCardProps {
  onNavigate: Navigate
  quote?: StockListQuote
  stock: Stock
}

export function StockCard({ onNavigate, quote, stock }: StockCardProps) {
  const direction = quote ? (quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down') : stock.direction
  const changeRate = quote
    ? `${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%`
    : stock.changeRate

  return (
    <AppLink className="stock-card" href={`/stocks/${stock.code}`} onNavigate={onNavigate}>
      <div className="stock-card__top">
        <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} />
        <span className="stock-card__market">{stock.market}</span>
        <Icon className="stock-card__arrow" name="chevron-right" size={18} />
      </div>
      <div className="stock-card__identity">
        <strong>{stock.name}</strong>
        <span>{stock.code}</span>
      </div>
      <div className="stock-card__quote">
        <AnimatedPrice fallback={stock.price} value={quote?.price ?? null} />
        <span className={`quote-change quote-change--${direction}`}>
          {changeRate}
        </span>
      </div>
      <p>{stock.sector}</p>
    </AppLink>
  )
}
