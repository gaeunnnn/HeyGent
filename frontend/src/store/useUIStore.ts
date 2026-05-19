import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const DEFAULT_SIDEBAR_WIDTH = 236
export const DEFAULT_SIDEBAR_COLLAPSED_WIDTH = 64
export const MIN_SIDEBAR_WIDTH = 200
export const MAX_SIDEBAR_WIDTH = 480

// Keep the favicon aligned with the app theme.
// Use the dedicated theme favicon assets.
function applyFavicon(theme: 'dark' | 'light') {
  const path = theme === 'dark' ? '/favicon_dark.png' : '/favicon_light.png'
  // cache-busting — 브라우저 favicon 캐시 강제 무효화
  const href = `${path}?v=${Date.now()}`

  // 1. 정적 HTML 의 prefers-color-scheme 기반 favicon link 모두 제거
  //    (OS 테마와 앱 테마가 다를 때 브라우저가 정적 link 를 우선해서 동적 갱신이 무시되는 문제 방지)
  document
    .querySelectorAll<HTMLLinkElement>('link[rel~="icon"]:not([data-app])')
    .forEach((el) => el.remove())

  // 2. 동적 (data-app="1") favicon link 갱신
  let appLink = document.querySelector<HTMLLinkElement>('link[rel="icon"][data-app="1"]')
  if (!appLink) {
    appLink = document.createElement('link')
    appLink.rel = 'icon'
    appLink.type = 'image/png'
    appLink.dataset.app = '1'
    document.head.appendChild(appLink)
  }
  appLink.setAttribute('sizes', 'any')
  appLink.href = href

  // 3. shortcut icon (구형 브라우저 호환)
  let shortcut = document.querySelector<HTMLLinkElement>('link[rel="shortcut icon"][data-app="1"]')
  if (!shortcut) {
    shortcut = document.createElement('link')
    shortcut.rel = 'shortcut icon'
    shortcut.dataset.app = '1'
    document.head.appendChild(shortcut)
  }
  shortcut.href = href

  // 4. apple-touch-icon 도 동기 갱신 (홈 화면 바로가기용)
  let touch = document.querySelector<HTMLLinkElement>('link[rel="apple-touch-icon"][data-app="1"]')
  if (!touch) {
    touch = document.createElement('link')
    touch.rel = 'apple-touch-icon'
    touch.dataset.app = '1'
    document.head.appendChild(touch)
  }
  touch.href = href
}

interface UIState {
  // 좌측 사이드바
  sidebarCollapsed: boolean
  sidebarWidth: number
  sessionWorkspaceCollapsed: boolean
  settingsOpen: boolean
  settingsInitialTab: string
  settingsSingleTab: boolean
  setSidebarCollapsed: (collapsed: boolean) => void
  setSidebarWidth: (width: number) => void
  setSessionWorkspaceCollapsed: (collapsed: boolean) => void
  setSettingsOpen: (open: boolean, initialTab?: string, options?: { singleTab?: boolean }) => void

  // 채팅 활동 패널
  taskActivityPanelOpen: boolean
  setTaskActivityPanelOpen: (open: boolean) => void

  // 프로토타입 프리뷰 패널
  prototypePanelSessionId: string | null
  prototypePanelOpenRequest: number
  requestPrototypePanel: (sessionId: string) => void

  // 테마
  theme: 'dark' | 'light'
  setTheme: (theme: 'dark' | 'light') => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
      sessionWorkspaceCollapsed: false,
      settingsOpen: false,
      settingsInitialTab: 'general',
      settingsSingleTab: false,
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setSidebarWidth: (width) =>
        set({ sidebarWidth: Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width)) }),
      setSessionWorkspaceCollapsed: (collapsed) => set({ sessionWorkspaceCollapsed: collapsed }),
      setSettingsOpen: (open, initialTab, options) =>
        set({
          settingsOpen: open,
          ...(initialTab ? { settingsInitialTab: initialTab } : {}),
          settingsSingleTab: open ? (options?.singleTab ?? false) : false,
        }),
      taskActivityPanelOpen: false,
      setTaskActivityPanelOpen: (open) => set({ taskActivityPanelOpen: open }),
      prototypePanelSessionId: null,
      prototypePanelOpenRequest: 0,
      requestPrototypePanel: (sessionId) =>
        set((state) => ({
          prototypePanelSessionId: sessionId,
          prototypePanelOpenRequest: state.prototypePanelOpenRequest + 1,
        })),
      theme: 'dark',
      setTheme: (theme) => {
        document.documentElement.classList.toggle('dark', theme === 'dark')
        applyFavicon(theme)
        set({ theme })
      },
    }),
    {
      name: 'heygent-ui-state',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        sidebarWidth: state.sidebarWidth,
        sessionWorkspaceCollapsed: state.sessionWorkspaceCollapsed,
        theme: state.theme,
      }),
    },
  ),
)
