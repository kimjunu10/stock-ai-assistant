import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useRagConversation } from '../hooks/useRagConversation'
import type { RagContext, StockContextErrorCode } from '../types/qa'
import { Icon, type IconName } from './Icon'
import { RagAnswer } from './RagAnswer'
import { RagSources } from './RagSources'
import { RagVisualizations } from './RagVisualizations'

interface RagConversationProps {
  context: RagContext
  emptyTitle?: string
  variant: 'page' | 'panel'
  onStockContextError?: (code: StockContextErrorCode | null) => void
}

interface StarterQuestion {
  icon: IconName
  label: string
  question: string
}

function suggestions(context: RagContext): StarterQuestion[] {
  if (context.sourceType === 'news_event') return [
    { icon: 'info', label: '사건 해설', question: '이 사건이 왜 중요해?' },
    { icon: 'chart', label: '주가 반응', question: '발표 전후 주가는 어떻게 움직였어?' },
    { icon: 'document', label: '공식 자료', question: '관련된 공식 공시가 있어?' },
    { icon: 'news', label: '후속 보도', question: '후속 보도가 있었어?' },
  ]
  if (context.sourceType === 'dart_document' || context.sourceType === 'structured_disclosure') return [
    { icon: 'document', label: '핵심 숫자', question: '이 공시 핵심 숫자만 알려줘' },
    { icon: 'info', label: '주의 사항', question: '투자자가 주의할 점은 뭐야?' },
    { icon: 'news', label: '관련 뉴스', question: '관련 뉴스가 있어?' },
    { icon: 'refresh', label: '변경 사항', question: '정정 전과 후 무엇이 달라졌어?' },
  ]
  if (context.sourceType === 'research_report') return [
    { icon: 'chart', label: '목표주가', question: '이 리포트의 목표주가와 근거는?' },
    { icon: 'stocks', label: '실적 비교', question: '실제 실적과 전망치를 비교해줘' },
    { icon: 'document', label: '의견 비교', question: '다른 증권사 의견과 비교해줘' },
    { icon: 'check', label: '공식 발표', question: '회사 발표 내용만 알려줘' },
  ]
  return [
    { icon: 'message', label: '한눈에 요약', question: '이 종목 지금 핵심만 정리해줘' },
    { icon: 'chart', label: '주가 흐름', question: '최근 주가가 어떻게 움직였어?' },
    { icon: 'news', label: '뉴스 분석', question: '최근 호재만 알려줘. 실적 관련은 제외해.' },
    { icon: 'document', label: '실적·전망', question: '실제 실적과 증권사 전망을 비교해줘.' },
  ]
}

function contextLabel(context: RagContext) {
  const stock = context.stockName ?? context.stockCode
  if (context.sourceType === 'news_event') return `${stock ? `${stock} · ` : ''}현재 뉴스 기준`
  if (context.sourceType === 'dart_document' || context.sourceType === 'structured_disclosure') return `${stock ? `${stock} · ` : ''}현재 공시 기준`
  if (context.sourceType === 'research_report') return `${stock ? `${stock} · ` : ''}현재 리포트${context.page ? ` ${context.page}페이지` : ''} 기준`
  return stock ? `${stock} 기준` : '전체 자료 기준'
}

export function RagConversation({
  context,
  emptyTitle,
  variant,
  onStockContextError,
}: RagConversationProps) {
  const [input, setInput] = useState('')
  const {
    abort,
    messages,
    phase,
    progress,
    reset,
    retry,
    send,
    stockContextError,
  } = useRagConversation(context)
  const scrollRef = useRef<HTMLDivElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const starterQuestions = useMemo(() => suggestions(context), [context])
  const active = phase === 'connecting' || phase === 'running' || phase === 'streaming'

  useEffect(() => {
    onStockContextError?.(stockContextError)
  }, [onStockContextError, stockContextError])

  useEffect(() => {
    if (messages.length > 0 || progress) {
      const frame = window.requestAnimationFrame(() => {
        endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
      })
      return () => window.cancelAnimationFrame(frame)
    }
  }, [messages, progress])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim() || active) return
    void send(input)
    setInput('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <div className={`rag-conversation rag-conversation--${variant}`}>
      <div aria-live="polite" className="rag-thread" ref={scrollRef}>
        <div className="rag-context-badge"><span>{contextLabel(context)}</span></div>
        {context.title && <div className="rag-context-title"><strong>{context.title}</strong>{context.selectedText && <q>{context.selectedText}</q>}</div>}

        {messages.length === 0 ? (
          <div className="rag-empty">
            <div className="rag-empty__identity">
              <span aria-hidden="true" className="moa-chat-avatar moa-chat-avatar--large">M</span>
              <div><strong>Moa AI</strong><span>무엇이든 물어보세요</span></div>
              <i aria-hidden="true" />
            </div>
            <h1>{emptyTitle ?? '무엇이 궁금한가요?'}</h1>
            <p>주가, 뉴스, 공시와 리포트를 한 번에 확인하세요.</p>
            <div className="rag-starters">
              {starterQuestions.map((item) => (
                <button aria-label={item.question} key={item.question} onClick={() => void send(item.question)} type="button">
                  <span className="rag-starter__leading">
                    <span className="rag-starter__icon"><Icon name={item.icon} size={17} /></span>
                    <span><small>{item.label}</small><strong>{item.question}</strong></span>
                  </span>
                  <Icon name="arrow-right" size={15} />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="rag-messages">
            {messages.map((message) => (
              <article className={`rag-message rag-message--${message.role}${message.state ? ` is-${message.state}` : ''}`} key={message.id}>
                <div>
                  {message.role === 'assistant' && (
                    <div className="rag-message__identity">
                      <span aria-hidden="true" className="moa-chat-avatar">M</span>
                      <strong>Moa AI</strong>
                    </div>
                  )}
                  {message.text
                    ? message.role === 'assistant' ? <RagAnswer text={message.text} /> : <p>{message.text}</p>
                    : message.state === 'pending' && <span className="rag-answer-placeholder">근거를 확인하고 있어요…</span>}
                  {message.role === 'assistant' && <RagVisualizations visualizations={message.visualizations} />}
                  {message.role === 'assistant' && <RagSources sources={message.sources.filter((source) => !message.visualizations.some(
                    (visualization) => visualization.type === 'news_cards' && visualization.sourceIds.includes(source.sourceId),
                  ))} stockCode={context.stockCode} />}
                  {message.warnings.length > 0 && <div className="rag-warnings">{message.warnings.map((warning) => <p key={warning}><Icon name="info" size={13} />{warning}</p>)}</div>}
                  {(message.state === 'aborted' || (message.state === 'error' && !message.errorCode)) && <button className="rag-retry" onClick={retry} type="button"><Icon name="refresh" size={14} /> 다시 시도</button>}
                </div>
              </article>
            ))}
          </div>
        )}
        {active && <div className="rag-progress" role="status"><i /><span>{progress}</span></div>}
        <div aria-hidden="true" className="rag-thread-end" ref={endRef} />
      </div>

      <form className="rag-composer" onSubmit={submit}>
        <div>
          <textarea
            aria-label={`${context.stockName ?? context.stockCode ?? ''} AI 질문 입력`}
            disabled={active}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="AI에게 질문해 보세요"
            rows={2}
            value={input}
          />
          {active
            ? <button aria-label="답변 생성 중단" className="rag-stop" onClick={abort} type="button"><span /></button>
            : <button aria-label="질문 보내기" disabled={!input.trim()} type="submit"><Icon name="send" size={17} /></button>}
        </div>
        <footer>
          <span>답변은 확인된 자료를 기준으로 생성됩니다.</span>
          {messages.length > 0 && !active && <button onClick={reset} type="button">새 질문</button>}
        </footer>
      </form>
    </div>
  )
}
