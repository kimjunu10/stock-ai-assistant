import type { RagSource, RagSourceType } from '../types/qa'
import { Icon } from './Icon'

const SOURCE_LABELS: Record<RagSourceType, string> = {
  financial: 'DART 재무',
  term: '금융용어',
  news_event: '뉴스',
  dart_document: 'DART 공시',
  structured_disclosure: 'DART 공시',
  research_report: '증권사 리포트',
  price: '시장 가격',
}

function sourceMeta(source: RagSource) {
  return [source.publisher, source.publishedAt, source.page ? `${source.page}페이지` : undefined]
    .filter(Boolean)
    .join(' · ')
}

function reportDownloadUrl(source: RagSource, stockCode?: string) {
  const reportId = source.locator.report_id
  if (source.sourceType !== 'research_report' || !stockCode || typeof reportId !== 'string') {
    return undefined
  }
  return `/api/stocks/${stockCode}/reports/${reportId}/download`
}

function evidenceText(source: RagSource) {
  return typeof source.locator.evidence === 'string' ? source.locator.evidence : undefined
}

function SourceRow({ source, stockCode }: { source: RagSource; stockCode?: string }) {
  const downloadUrl = reportDownloadUrl(source, stockCode)
  const href = source.url || downloadUrl
  const evidence = evidenceText(source)
  const row = (
    <>
      <span className={`answer-source__kind is-${source.sourceType}`}>
        {SOURCE_LABELS[source.sourceType]}
      </span>
      <span className="answer-source__body">
        <strong>{source.title || '제목 없는 자료'}</strong>
        {sourceMeta(source) && <small>{sourceMeta(source)}</small>}
      </span>
      <span className="answer-source__action">
        {downloadUrl
          ? <><Icon name="download" size={15} /> PDF</>
          : href ? <Icon name="external" size={15} /> : <Icon name="check" size={15} />}
      </span>
    </>
  )

  if (href) {
    return <a className="answer-source" href={href} rel="noreferrer" target="_blank">{row}</a>
  }
  if (evidence) {
    return (
      <details className="answer-source answer-source--evidence">
        <summary>{row}</summary>
        <blockquote>{evidence}</blockquote>
      </details>
    )
  }
  return <div className="answer-source">{row}</div>
}

export function RagSources({ sources, stockCode }: { sources: RagSource[]; stockCode?: string }) {
  if (sources.length === 0) return null
  return (
    <section aria-label="답변 출처" className="answer-sources">
      <header>
        <strong>확인한 출처</strong>
        <span>{sources.length}</span>
      </header>
      <div>
        {sources.map((source) => (
          <SourceRow key={source.sourceId} source={source} stockCode={stockCode} />
        ))}
      </div>
    </section>
  )
}
