import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
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

function reportViewUrl(source: RagSource, stockCode?: string) {
  const reportId = source.locator.report_id
  if (source.sourceType !== 'research_report' || !stockCode || typeof reportId !== 'string') {
    return undefined
  }
  return `/api/stocks/${stockCode}/reports/${reportId}/view`
}

function evidenceText(source: RagSource) {
  return typeof source.locator.evidence === 'string' ? source.locator.evidence : undefined
}

function SourceRow({ onPreview, source, stockCode }: { onPreview: (url: string, title: string) => void; source: RagSource; stockCode?: string }) {
  const downloadUrl = reportDownloadUrl(source, stockCode)
  const viewUrl = reportViewUrl(source, stockCode)
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
      <span className="answer-source__actions">
        {source.url && <a aria-label={`${source.title || '자료'} 원문 보기`} href={source.url} rel="noreferrer" target="_blank"><Icon name="external" size={14} /> 보기</a>}
        {viewUrl && <button aria-label={`${source.title || '리포트'} 원문 미리보기`} onClick={() => onPreview(viewUrl, source.title || '증권사 리포트')} type="button"><Icon name="document" size={14} /> 미리보기</button>}
        {downloadUrl && <a aria-label={`${source.title || '리포트'} PDF 다운로드`} href={downloadUrl} rel="noreferrer" target="_blank"><Icon name="download" size={14} /> PDF</a>}
        {!source.url && !downloadUrl && !evidence && <span><Icon name="check" size={14} /> 확인됨</span>}
      </span>
    </>
  )

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
  const [preview, setPreview] = useState<{ title: string; url: string } | null>(null)
  useEffect(() => {
    if (!preview) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [preview])
  if (sources.length === 0) return null
  return (
    <>
      <section aria-label="답변 출처" className="answer-sources">
        <header>
          <strong>확인한 출처</strong>
          <span>{sources.length}</span>
        </header>
        <div>
          {sources.map((source) => (
            <SourceRow key={source.sourceId} onPreview={(url, title) => setPreview({ title, url })} source={source} stockCode={stockCode} />
          ))}
        </div>
      </section>
      {preview && createPortal(
        <div className="report-preview-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)} role="presentation">
          <section aria-label={`${preview.title} 원문 미리보기`} aria-modal="true" className="report-preview" role="dialog">
            <header><div><span>증권사 리포트 원문</span><strong>{preview.title}</strong></div><button aria-label="리포트 미리보기 닫기" onClick={() => setPreview(null)} type="button"><Icon name="close" size={20} /></button></header>
            <iframe src={preview.url} title={`${preview.title} PDF 원문`} />
          </section>
        </div>,
        document.body,
      )}
    </>
  )
}
