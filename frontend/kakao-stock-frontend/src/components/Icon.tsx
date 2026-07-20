export type IconName =
  | 'home'
  | 'stocks'
  | 'news'
  | 'search'
  | 'sun'
  | 'moon'
  | 'arrow-right'
  | 'chevron-right'
  | 'message'
  | 'send'
  | 'close'
  | 'refresh'
  | 'external'
  | 'chart'
  | 'document'
  | 'check'
  | 'info'
  | 'calendar'
  | 'menu'

interface IconProps {
  name: IconName
  size?: number
  strokeWidth?: number
  className?: string
}

export function Icon({ name, size = 20, strokeWidth = 1.8, className }: IconProps) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    strokeWidth,
  }

  const paths: Record<IconName, React.ReactNode> = {
    home: (
      <>
        <path {...common} d="m3 10.5 9-7 9 7" />
        <path {...common} d="M5.5 9.5V21h13V9.5M9.5 21v-7h5v7" />
      </>
    ),
    stocks: (
      <>
        <path {...common} d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
        <path {...common} d="m4 7 6-4 6 6 6-5" />
      </>
    ),
    news: (
      <>
        <path {...common} d="M5 3h14v18H5z" />
        <path {...common} d="M8.5 7h7M8.5 11h7M8.5 15h4" />
      </>
    ),
    search: (
      <>
        <circle {...common} cx="10.5" cy="10.5" r="6.5" />
        <path {...common} d="m15.5 15.5 5 5" />
      </>
    ),
    sun: (
      <>
        <circle {...common} cx="12" cy="12" r="4" />
        <path {...common} d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41" />
      </>
    ),
    moon: <path {...common} d="M20.3 15.2A8.3 8.3 0 0 1 8.8 3.7 8.3 8.3 0 1 0 20.3 15.2Z" />,
    'arrow-right': <path {...common} d="M5 12h14M14 7l5 5-5 5" />,
    'chevron-right': <path {...common} d="m9 5 7 7-7 7" />,
    message: (
      <>
        <path {...common} d="M21 11.5a8.5 8.5 0 0 1-9 8.5 9.5 9.5 0 0 1-3.8-.9L3 21l1.9-5A8.5 8.5 0 1 1 21 11.5Z" />
        <path {...common} d="M8 10.5h8M8 14h5" />
      </>
    ),
    send: (
      <>
        <path {...common} d="m3 3 18 9-18 9 3-9-3-9Z" />
        <path {...common} d="M6 12h15" />
      </>
    ),
    close: <path {...common} d="M5 5l14 14M19 5 5 19" />,
    refresh: (
      <>
        <path {...common} d="M20 7v5h-5" />
        <path {...common} d="M18.2 17a8 8 0 1 1 1.4-8l.4 3" />
      </>
    ),
    external: (
      <>
        <path {...common} d="M14 4h6v6M20 4l-9 9" />
        <path {...common} d="M18 13v6H5V6h6" />
      </>
    ),
    chart: (
      <>
        <path {...common} d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </>
    ),
    document: (
      <>
        <path {...common} d="M6 2h8l4 4v16H6z" />
        <path {...common} d="M14 2v5h5M9 12h6M9 16h6" />
      </>
    ),
    check: <path {...common} d="m5 12 4 4L19 6" />,
    info: (
      <>
        <circle {...common} cx="12" cy="12" r="9" />
        <path {...common} d="M12 11v6M12 7.5v.1" />
      </>
    ),
    calendar: (
      <>
        <rect {...common} x="3" y="5" width="18" height="16" rx="2" />
        <path {...common} d="M8 3v4M16 3v4M3 10h18" />
      </>
    ),
    menu: <path {...common} d="M4 7h16M4 12h16M4 17h16" />,
  }

  return (
    <svg
      aria-hidden="true"
      className={className}
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      {paths[name]}
    </svg>
  )
}
