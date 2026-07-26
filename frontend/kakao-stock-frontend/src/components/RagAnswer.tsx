import { cleanPublicText } from '../utils/publicText'

interface RagAnswerProps {
  text: string
}

type AnswerBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'ordered' | 'unordered'; items: string[] }

const ORDERED_ITEM = /^\d+[.)]\s+(.+)$/
const UNORDERED_ITEM = /^[-*•]\s+(.+)$/

function parseAnswer(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = []
  let paragraph: string[] = []
  let list: Extract<AnswerBlock, { kind: 'ordered' | 'unordered' }> | undefined

  const flushParagraph = () => {
    const value = paragraph.join(' ').trim()
    if (value) blocks.push({ kind: 'paragraph', text: value })
    paragraph = []
  }
  const flushList = () => {
    if (list?.items.length) blocks.push(list)
    list = undefined
  }

  for (const rawLine of cleanPublicText(text).replace(/\r/g, '').split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }
    const ordered = line.match(ORDERED_ITEM)
    const unordered = line.match(UNORDERED_ITEM)
    const kind = ordered ? 'ordered' : unordered ? 'unordered' : undefined
    if (kind) {
      flushParagraph()
      if (list?.kind !== kind) flushList()
      list ??= { kind, items: [] }
      list.items.push((ordered?.[1] ?? unordered?.[1] ?? '').trim())
      continue
    }
    flushList()
    paragraph.push(line)
  }
  flushParagraph()
  flushList()
  return blocks
}

export function RagAnswer({ text }: RagAnswerProps) {
  return (
    <div className="rag-answer">
      {parseAnswer(text).map((block, index) => {
        if (block.kind === 'paragraph') return <p key={`${block.kind}-${index}`}>{block.text}</p>
        const items = block.items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{item}</li>)
        return block.kind === 'ordered'
          ? <ol key={`${block.kind}-${index}`}>{items}</ol>
          : <ul key={`${block.kind}-${index}`}>{items}</ul>
      })}
    </div>
  )
}
