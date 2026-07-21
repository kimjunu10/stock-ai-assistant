export interface SelectionAnchor {
  horizontal: 'left' | 'right'
  left: number
  text: string
  top: number
  vertical: 'above' | 'below'
}

export function createSelectionAnchor(range: Range, text: string): SelectionAnchor {
  const rects = Array.from(range.getClientRects())
  const rect = rects.at(-1) ?? range.getBoundingClientRect()
  return {
    text: text.slice(0, 500),
    top: Math.min(Math.max(12, rect.top - 42), window.innerHeight - 52),
    left: Math.min(Math.max(12, rect.right + 8), window.innerWidth - 48),
    horizontal: rect.right < window.innerWidth / 2 ? 'left' : 'right',
    vertical: rect.bottom > window.innerHeight * 0.58 ? 'above' : 'below',
  }
}
