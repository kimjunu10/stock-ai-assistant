import type { Stock } from '../types'
import { AppLink, type Navigate } from './AppLink'
import { Icon } from './Icon'
import { StockAvatar } from './StockAvatar'

interface StockCardProps {
  onNavigate: Navigate
  stock: Stock
}

export function StockCard({ onNavigate, stock }: StockCardProps) {
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
        <strong>{stock.price}</strong>
        <span className={`quote-change quote-change--${stock.direction}`}>
          {stock.changeRate}
        </span>
      </div>
      <p>{stock.sector}</p>
    </AppLink>
  )
}
