import { useState, type FormEvent } from 'react'
import { STOCKS } from '../data/mockData'
import type { Theme } from '../types'
import { AppLink, type Navigate } from './AppLink'
import { Icon } from './Icon'
import { StockAvatar } from './StockAvatar'

interface AppHeaderProps {
  currentPath: string
  onNavigate: Navigate
  onThemeChange: (theme: Theme) => void
  theme: Theme
}

const NAV_ITEMS = [
  { href: '/', label: '홈' },
  { href: '/stocks', label: '종목' },
  { href: '/news', label: '뉴스 브리핑' },
  { href: '/ask', label: 'AI에게 질문' },
]

export function AppHeader({ currentPath, onNavigate, onThemeChange, theme }: AppHeaderProps) {
  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)

  const matchedStocks = search.trim()
    ? STOCKS.filter(
        (stock) => stock.name.includes(search.trim()) || stock.code.includes(search.trim()),
      )
    : STOCKS

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const stock = matchedStocks[0]
    if (stock) {
      onNavigate(`/stocks/${stock.code}`)
      setSearch('')
      setSearchOpen(false)
    }
  }

  return (
    <header className="app-header">
      <div className="app-header__inner shell">
        <AppLink className="brand" href="/" onNavigate={onNavigate} aria-label="Moa 홈">
          <span className="brand__mark" aria-hidden="true">
            <span />
            <span />
          </span>
          <span>Moa</span>
          <span className="brand__suffix">AI</span>
        </AppLink>

        <nav aria-label="주요 메뉴" className="desktop-nav">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === '/'
                ? currentPath === '/'
                : currentPath === item.href || currentPath.startsWith(`${item.href}/`)
            return (
              <AppLink
                className={active ? 'desktop-nav__link is-active' : 'desktop-nav__link'}
                href={item.href}
                key={item.href}
                onNavigate={onNavigate}
              >
                {item.label}
              </AppLink>
            )
          })}
        </nav>

        <div className="header-actions">
          <div className="stock-search">
            <form className="stock-search__form" onSubmit={handleSubmit}>
              <Icon name="search" size={18} />
              <input
                aria-label="종목 검색"
                onChange={(event) => setSearch(event.target.value)}
                onFocus={() => setSearchOpen(true)}
                placeholder="종목명 또는 코드"
                value={search}
              />
            </form>
            {searchOpen && (
              <div className="stock-search__results">
                <div className="stock-search__label">5개 분석 종목</div>
                {matchedStocks.length > 0 ? (
                  matchedStocks.map((stock) => (
                    <button
                      key={stock.code}
                      onClick={() => {
                        onNavigate(`/stocks/${stock.code}`)
                        setSearch('')
                        setSearchOpen(false)
                      }}
                      type="button"
                    >
                      <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />
                      <span>
                        <strong>{stock.name}</strong>
                        <small>{stock.code}</small>
                      </span>
                      <Icon name="chevron-right" size={16} />
                    </button>
                  ))
                ) : (
                  <p className="stock-search__empty">일치하는 분석 종목이 없어요.</p>
                )}
              </div>
            )}
          </div>
          {searchOpen && (
            <button
              aria-label="검색 닫기"
              className="search-scrim"
              onClick={() => setSearchOpen(false)}
              type="button"
            />
          )}
          <button
            aria-label={theme === 'light' ? '다크 테마 사용' : '라이트 테마 사용'}
            className="icon-button theme-toggle"
            onClick={() => onThemeChange(theme === 'light' ? 'dark' : 'light')}
            type="button"
          >
            <Icon name={theme === 'light' ? 'moon' : 'sun'} size={19} />
          </button>
        </div>
      </div>
    </header>
  )
}

export function MobileNavigation({ currentPath, onNavigate }: Pick<AppHeaderProps, 'currentPath' | 'onNavigate'>) {
  const items = [
    { href: '/', label: '홈', icon: 'home' as const },
    { href: '/stocks', label: '종목', icon: 'stocks' as const },
    { href: '/news', label: '뉴스', icon: 'news' as const },
    { href: '/ask', label: 'AI 질문', icon: 'message' as const },
  ]

  return (
    <nav aria-label="모바일 주요 메뉴" className="mobile-nav">
      {items.map((item) => {
        const active =
          item.href === '/'
            ? currentPath === '/'
            : currentPath === item.href || currentPath.startsWith(`${item.href}/`)
        return (
          <AppLink
            className={active ? 'mobile-nav__link is-active' : 'mobile-nav__link'}
            href={item.href}
            key={item.href}
            onNavigate={onNavigate}
          >
            <Icon name={item.icon} size={21} />
            <span>{item.label}</span>
          </AppLink>
        )
      })}
    </nav>
  )
}
