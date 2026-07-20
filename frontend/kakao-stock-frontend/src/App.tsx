import { useCallback, useEffect, useState } from 'react'
import { AppHeader, MobileNavigation } from './components/AppHeader'
import { AppLink } from './components/AppLink'
import { AssistantPanel } from './components/AssistantPanel'
import { Icon } from './components/Icon'
import { AskPage } from './pages/AskPage'
import { HomePage } from './pages/HomePage'
import { NewsPage } from './pages/NewsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { StockDetailPage } from './pages/StockDetailPage'
import { StocksPage } from './pages/StocksPage'
import type { AssistantContext, Theme } from './types'

function getInitialTheme(): Theme {
  const saved = window.localStorage.getItem('moa-theme')
  return saved === 'dark' ? 'dark' : 'light'
}

function getCurrentPath() {
  return window.location.pathname.replace(/\/$/, '') || '/'
}

function App() {
  const [currentPath, setCurrentPath] = useState(getCurrentPath)
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const [assistantContext, setAssistantContext] = useState<AssistantContext | null>(null)

  useEffect(() => {
    const handlePopState = () => setCurrentPath(getCurrentPath())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    window.localStorage.setItem('moa-theme', theme)
  }, [theme])

  const navigate = useCallback((path: string) => {
    if (getCurrentPath() !== path) window.history.pushState({}, '', path)
    setCurrentPath(path)
    setAssistantContext(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  const openAssistant = useCallback((context: AssistantContext) => {
    setAssistantContext(context)
  }, [])

  let page
  const stockMatch = currentPath.match(/^\/stocks\/(\d{6})$/)

  if (currentPath === '/') {
    page = <HomePage onAsk={openAssistant} onNavigate={navigate} />
  } else if (currentPath === '/stocks') {
    page = <StocksPage onNavigate={navigate} />
  } else if (stockMatch?.[1]) {
    page = <StockDetailPage onAsk={openAssistant} stockCode={stockMatch[1]} theme={theme} />
  } else if (currentPath === '/news') {
    page = <NewsPage onAsk={openAssistant} />
  } else if (currentPath === '/ask') {
    page = <AskPage />
  } else {
    page = <NotFoundPage onNavigate={navigate} />
  }

  return (
    <div className="app">
      <AppHeader currentPath={currentPath} onNavigate={navigate} onThemeChange={setTheme} theme={theme} />
      {page}
      {currentPath !== '/ask' && (
        <footer className="app-footer">
          <div className="shell app-footer__inner">
            <div>
              <AppLink className="brand brand--footer" href="/" onNavigate={navigate}>
                <span className="brand__mark" aria-hidden="true"><span /><span /></span>
                <span>Moa</span><span className="brand__suffix">AI</span>
              </AppLink>
              <p>뉴스·공시·리포트를 근거로 쉽게 설명하는 투자 정보 서비스</p>
            </div>
            <div className="app-footer__notice"><Icon name="info" size={16} /><span>투자 판단을 위한 참고 정보이며, 매수·매도 추천을 제공하지 않습니다.</span></div>
          </div>
        </footer>
      )}
      <MobileNavigation currentPath={currentPath} onNavigate={navigate} />
      <AssistantPanel context={assistantContext} onClose={() => setAssistantContext(null)} open={assistantContext !== null} />
    </div>
  )
}

export default App
