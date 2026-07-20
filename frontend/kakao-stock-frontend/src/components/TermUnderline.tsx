import { useState } from 'react'
import { Icon } from './Icon'

interface TermUnderlineProps {
  definition: string
  term: string
}

export function TermUnderline({ definition, term }: TermUnderlineProps) {
  const [open, setOpen] = useState(false)

  return (
    <span className="term-wrap">
      <button className="term-underline" onClick={() => setOpen((value) => !value)} type="button">
        {term}
      </button>
      {open && (
        <span className="term-popover" role="tooltip">
          <span className="term-popover__title">
            <Icon name="info" size={15} />
            {term}
          </span>
          {definition}
        </span>
      )}
    </span>
  )
}
