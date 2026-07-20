import type { ReactNode } from 'react'

interface SectionHeaderProps {
  action?: ReactNode
  description?: string
  eyebrow?: string
  title: string
}

export function SectionHeader({ action, description, eyebrow, title }: SectionHeaderProps) {
  return (
    <div className="section-header">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  )
}
