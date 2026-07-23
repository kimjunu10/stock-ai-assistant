export interface SelectionAnchor {
  actionVertical: 'above' | 'below'
  height: number
  horizontal: 'left' | 'right'
  left: number
  text: string
  top: number
  vertical: 'above' | 'below'
}

interface SelectionEndpoint {
  clientX: number
  clientY: number
}

const ACTION_WIDTH = 310
const VIEWPORT_GUTTER = 12

export function createSelectionAnchor(range: Range, text: string, endpoint?: SelectionEndpoint): SelectionAnchor {
  const rects = Array.from(range.getClientRects())
  const rangeRect = range.getBoundingClientRect()
  const fallbackRect = rects.at(-1) ?? rangeRect
  const endpointRect = endpoint && rects.length > 0
    ? rects.reduce((nearest, candidate) => {
        const x = Math.min(Math.max(endpoint.clientX, candidate.left), candidate.right)
        const y = Math.min(Math.max(endpoint.clientY, candidate.top), candidate.bottom)
        const nearestX = Math.min(Math.max(endpoint.clientX, nearest.left), nearest.right)
        const nearestY = Math.min(Math.max(endpoint.clientY, nearest.top), nearest.bottom)
        const candidateDistance = (endpoint.clientX - x) ** 2 + (endpoint.clientY - y) ** 2
        const nearestDistance = (endpoint.clientX - nearestX) ** 2 + (endpoint.clientY - nearestY) ** 2
        return candidateDistance < nearestDistance ? candidate : nearest
      }, fallbackRect)
    : fallbackRect
  const endpointX = endpoint?.clientX ?? endpointRect.right
  const left = Math.min(Math.max(VIEWPORT_GUTTER, endpointX), window.innerWidth - VIEWPORT_GUTTER)
  return {
    text: text.slice(0, 500),
    top: Math.min(Math.max(VIEWPORT_GUTTER, rangeRect.top), window.innerHeight - VIEWPORT_GUTTER),
    left,
    height: Math.max(20, rangeRect.height),
    horizontal: left >= ACTION_WIDTH + VIEWPORT_GUTTER ? 'right' : 'left',
    actionVertical: rangeRect.top >= 76 ? 'above' : 'below',
    vertical: rangeRect.bottom > window.innerHeight * 0.58 ? 'above' : 'below',
  }
}
