import type { AssistantContext, DisclosureItem, ReportItem } from '../types'
import { Icon } from './Icon'

interface DisclosureListProps {
  items: DisclosureItem[]
  onAsk: (context: AssistantContext) => void
}

interface ReportListProps {
  items: ReportItem[]
  onAsk: (context: AssistantContext) => void
}

export function DisclosureList({ items, onAsk }: DisclosureListProps) {
  return (
    <div className="research-list">
      {items.map((item) => (
        <article id={`disclosure:${item.id}`} key={item.id}>
          <span className="research-list__icon">
            <Icon name="document" size={18} />
          </span>
          <div className="research-list__body">
            <div>
              <span>{item.type}</span>
              <time>{item.date}</time>
            </div>
            <h3>{item.viewerUrl ? <a href={item.viewerUrl} rel="noreferrer" target="_blank">{item.title}</a> : item.title}</h3>
            <p>{item.source} 공식 공시</p>
          </div>
          <button
            aria-label={`${item.title}에 관해 질문하기`}
            className="research-list__ask"
            onClick={() =>
              onAsk({
                stockCode: item.stockCode,
                sourceType: 'disclosure',
                sourceId: String(item.id),
                title: item.title,
              })
            }
            type="button"
          >
            <Icon name="message" size={17} />
          </button>
        </article>
      ))}
    </div>
  )
}

export function ReportList({ items, onAsk }: ReportListProps) {
  return (
    <div className="research-list">
      {items.map((item) => (
        <article id={`report:${item.id}`} key={item.id}>
          <span className="research-list__icon research-list__icon--report">
            <Icon name="chart" size={18} />
          </span>
          <div className="research-list__body">
            <div>
              <span>{item.broker}</span>
              <time>{item.date}</time>
            </div>
            <h3>{item.title}</h3>
            <p>
              {[item.opinion, item.pageCount ? `${item.pageCount}페이지` : null]
                .filter(Boolean)
                .join(' · ') || '증권사 원문 PDF'}
            </p>
          </div>
          <div className="research-list__actions">
            <button
              aria-label={`${item.title}에 관해 질문하기`}
              className="research-list__ask"
              onClick={() =>
                onAsk({
                  stockCode: item.stockCode,
                  sourceType: 'report',
                  sourceId: String(item.id),
                  title: item.title,
                })
              }
              type="button"
            >
              <Icon name="message" size={17} />
            </button>
            {item.downloadUrl && (
              <a
                className="research-list__download"
                href={item.downloadUrl}
                rel="noreferrer"
              >
                <Icon name="download" size={16} />
                PDF 다운로드
              </a>
            )}
          </div>
        </article>
      ))}
    </div>
  )
}
