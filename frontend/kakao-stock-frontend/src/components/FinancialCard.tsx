import type { FinancialItem } from '../types'

interface FinancialCardProps {
  item: FinancialItem
}

export function FinancialCard({ item }: FinancialCardProps) {
  const direction = item.yoyPct > 0 ? 'up' : item.yoyPct < 0 ? 'down' : 'flat'

  return (
    <article className="financial-card">
      <span>{item.account}</span>
      <strong>{item.display}</strong>
      <div>
        <span className={`financial-card__change financial-card__change--${direction}`}>
          전년 대비 {item.yoyPct > 0 ? '+' : ''}{item.yoyPct}%
        </span>
        <small>{item.note}</small>
      </div>
    </article>
  )
}
