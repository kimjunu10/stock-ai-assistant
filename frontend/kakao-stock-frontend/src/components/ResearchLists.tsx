import type { AssistantContext, DisclosureItem, ReportItem } from '../types'
import { Icon } from './Icon'

const BROKER_LOGOS: Record<string, string> = {
  'DS투자증권': '/brokers/ds.svg',
  'IBK투자증권': '/brokers/ibk.jpg',
  'SK증권': '/brokers/sk.jpg',
  'iM증권': '/brokers/im.jpg',
  '교보증권': '/brokers/kyobo.jpg',
  '대신증권': '/brokers/daishin.jpg',
  '메리츠증권': '/brokers/meritz.jpg',
  '미래에셋증권': '/brokers/mirae.jpg',
  '삼성증권': '/brokers/samsung.jpg',
  '유안타증권': '/brokers/yuanta.jpg',
  '유진투자증권': '/brokers/eugene.jpg',
  '키움증권': '/brokers/kiwoom.jpg',
  '하나증권': '/brokers/hana.jpg',
  '한화투자증권': '/brokers/hanwha.jpg',
  '현대차증권': '/brokers/hyundai.jpg',
}

interface DisclosureListProps {
  items: DisclosureItem[]
  onAsk: (context: AssistantContext) => void
}

interface ReportListProps {
  items: ReportItem[]
  onAsk: (context: AssistantContext) => void
}

function BrokerLogo({ broker }: { broker: string }) {
  const logoSrc = BROKER_LOGOS[broker.normalize('NFC').trim()]

  return (
    <span className="research-list__broker-logo" title={broker}>
      {logoSrc ? (
        <img
          alt=""
          decoding="async"
          loading="lazy"
          onError={(event) => {
            event.currentTarget.hidden = true
            event.currentTarget.nextElementSibling?.removeAttribute('hidden')
          }}
          src={logoSrc}
        />
      ) : null}
      <span className="research-list__broker-fallback" hidden={Boolean(logoSrc)}>
        <Icon name="chart" size={18} />
      </span>
    </span>
  )
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
                sourceId: item.sourceId ?? String(item.id),
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
          <BrokerLogo broker={item.broker} />
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
