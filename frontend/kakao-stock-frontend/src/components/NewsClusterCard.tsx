import { getStock } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import { Icon } from './Icon'
import { SentimentBadge } from './SentimentBadge'
import { StockAvatar } from './StockAvatar'
import { TermUnderline } from './TermUnderline'

interface NewsClusterCardProps {
  cluster: NewsCluster
  compact?: boolean
  onAsk?: (context: AssistantContext) => void
  showStock?: boolean
}

function EasySummary({ cluster }: { cluster: NewsCluster }) {
  const term = cluster.terms?.[0]
  if (!term || !cluster.easySummary.includes(term.term)) {
    return <>{cluster.easySummary}</>
  }

  const [before, after] = cluster.easySummary.split(term.term)
  return (
    <>
      {before}
      <TermUnderline definition={term.easyDefinition} term={term.term} />
      {after}
    </>
  )
}

export function NewsClusterCard({ cluster, compact = false, onAsk, showStock = false }: NewsClusterCardProps) {
  const stock = getStock(cluster.stockCode)

  return (
    <article className={compact ? 'news-card news-card--compact' : 'news-card'} id={`news_cluster:${cluster.id}`}>
      <div className="news-card__meta-row">
        <div className="news-card__badges">
          <SentimentBadge score={cluster.sentimentScore} sentiment={cluster.sentiment} />
          {showStock && stock && (
            <span className="news-card__stock">
              <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />
              {stock.name}
            </span>
          )}
        </div>
        <time>{cluster.publishedAt}</time>
      </div>
      <h3>{cluster.title}</h3>
      <p className="news-card__summary">
        <EasySummary cluster={cluster} />
      </p>
      {!compact && (
        <div className="news-card__reason">
          <span>왜 이렇게 봤나요?</span>
          <p>{cluster.sentimentReason}</p>
        </div>
      )}
      <div className="news-card__footer">
        <span>
          {cluster.pressList[0]} 외 {Math.max(cluster.articleCount - 1, 0)}건
          <span className="news-card__press-list"> · {cluster.pressList.slice(1).join(', ')}</span>
        </span>
        {onAsk && (
          <button
            className="text-button"
            onClick={() =>
              onAsk({
                stockCode: cluster.stockCode,
                sourceType: 'news_cluster',
                sourceId: String(cluster.id),
                title: cluster.title,
              })
            }
            type="button"
          >
            <Icon name="message" size={16} />
            이 뉴스 물어보기
          </button>
        )}
      </div>
    </article>
  )
}
