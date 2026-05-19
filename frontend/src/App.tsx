import { Key, Monitor } from 'lucide-react'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router'
import { LeftSidebar } from '@/components/layout/LeftSidebar'
import { SessionWorkspaceDetailPanel } from '@/components/sessionWorkspace/SessionWorkspaceDetailPanel'
import { SessionWorkspaceSidebar } from '@/components/sessionWorkspace/SessionWorkspaceSidebar'
import { getWorkspacePanelFromPath } from '@/components/sessionWorkspace/sessionWorkspaceUtils'
import { DashboardPage } from '@/pages/DashboardPage'
import { AgentStatusPage } from '@/pages/AgentStatusPage'
import { BuildingOverviewPage } from '@/pages/BuildingOverviewPage'
import { BridgeSettingsPage } from '@/pages/BridgeSettingsPage'
import { NewChatPage } from '@/pages/NewChatPage'
import { ChatSessionPage } from '@/pages/ChatSessionPage'
import { LoginPage } from '@/pages/LoginPage'
import { KakaoCallbackPage } from '@/pages/KakaoCallbackPage'
import { NotionCallbackPage } from '@/pages/NotionCallbackPage'
import { GmailCallbackPage } from '@/pages/GmailCallbackPage'
import { AiRealtimeProvider } from '@/providers/AiRealtimeProvider'
import { FcmProvider } from '@/providers/FcmProvider'
import { Toaster } from '@/components/ui/sonner'
import { useAuthStore } from '@/store/useAuthStore'
import { useChatStore } from '@/store/useChatStore'
import { useUIStore } from '@/store/useUIStore'
import { getOpenAiProviders } from '@/apis/openaiProviders'
import { listBridgeDevices } from '@/apis/bridge'

// "오늘 하루 보지 않기" 공통 유틸 — 다음날 00:00까지 dismiss
function getNextMidnightIso(): string {
  const now = new Date()
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0, 0)
  return next.toISOString()
}

function isDismissedUntilTomorrow(key: string): boolean {
  if (typeof window === 'undefined') return false
  try {
    const value = window.localStorage.getItem(key)
    if (!value) return false
    const until = new Date(value).getTime()
    if (!Number.isFinite(until)) return false
    if (until <= Date.now()) {
      window.localStorage.removeItem(key)
      return false
    }
    return true
  } catch {
    return false
  }
}

function dismissUntilTomorrow(key: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, getNextMidnightIso())
  } catch {
    // localStorage 사용 불가 환경에서는 무시
  }
}

const API_KEY_DISMISS_KEY = 'heygent.apikey-overlay.dismissed-until'
const BRIDGE_DISMISS_KEY = 'heygent.bridge-overlay.dismissed-until'

function OnboardingOverlays() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const settingsOpen = useUIStore((s) => s.settingsOpen)
  const setSettingsOpen = useUIStore((s) => s.setSettingsOpen)
  const location = useLocation()

  // API 키
  const [apiDismissedSession, setApiDismissedSession] = useState(false)
  const [apiKeyMissing, setApiKeyMissing] = useState(false)
  const [apiDismissedDaily, setApiDismissedDaily] = useState(() =>
    isDismissedUntilTomorrow(API_KEY_DISMISS_KEY),
  )

  // 브릿지
  const [bridgeDismissedSession, setBridgeDismissedSession] = useState(false)
  const [bridgeNotConnected, setBridgeNotConnected] = useState(false)
  // 'idle': 조회 시작 전, 'loading': 조회 중, 'loaded': 조회 완료(성공 또는 실패)
  // — loaded일 때만 카드 표시 결정. 조회 끝나기 전엔 카드를 절대 안 띄움.
  const [bridgeStatusPhase, setBridgeStatusPhase] = useState<'idle' | 'loading' | 'loaded'>('idle')
  const [bridgeDismissedDaily, setBridgeDismissedDaily] = useState(() =>
    isDismissedUntilTomorrow(BRIDGE_DISMISS_KEY),
  )

  const fetchApiKeyStatus = useCallback(() => {
    if (!isAuthenticated) return
    getOpenAiProviders()
      .then((res) => setApiKeyMissing(!res.providers.some((p) => p.connected)))
      .catch(() => setApiKeyMissing(false))
  }, [isAuthenticated])

  useEffect(() => {
    if (!isAuthenticated) return
    fetchApiKeyStatus()
  }, [isAuthenticated, fetchApiKeyStatus])

  useEffect(() => {
    if (!settingsOpen) fetchApiKeyStatus()
  }, [settingsOpen, fetchApiKeyStatus])

  useEffect(() => {
    if (!isAuthenticated) return
    let cancelled = false
    listBridgeDevices()
      .then((devices) => {
        if (cancelled) return
        // revokedAt이 truthy(실제 해제 ISO 문자열)일 때만 제외 — null/undefined/"" 등은 정상으로 본다
        const active = devices.filter((device) => !device.revokedAt)
        setBridgeNotConnected(active.length === 0)
        setBridgeStatusPhase('loaded')
      })
      .catch(() => {
        if (cancelled) return
        // 실패 시에는 카드를 띄우지 않는다(잘못된 가정 방지).
        setBridgeNotConnected(false)
        setBridgeStatusPhase('loaded')
      })
    return () => {
      cancelled = true
    }
  }, [isAuthenticated])

  const onBridgeSettingsPage = location.pathname.startsWith('/settings/bridge')

  const showApiCard =
    isAuthenticated && !apiDismissedSession && !apiDismissedDaily && apiKeyMissing && !settingsOpen
  // API 카드가 떠 있는 동안은 브릿지 카드를 띄우지 않는다 — 한 번에 하나씩만 보여줌
  const showBridgeCard =
    !showApiCard &&
    isAuthenticated &&
    bridgeStatusPhase === 'loaded' &&
    !bridgeDismissedSession &&
    !bridgeDismissedDaily &&
    bridgeNotConnected &&
    !settingsOpen &&
    !onBridgeSettingsPage

  if (!showApiCard && !showBridgeCard) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 배경 딤 — 카드 개수와 무관하게 한 번만 */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      <div className="relative flex max-h-[90vh] w-full max-w-sm flex-col gap-4 overflow-y-auto px-4">
        {showApiCard && (
          <div className="bg-card border-border w-full space-y-5 rounded-2xl border p-6 shadow-2xl">
            <div className="flex justify-center">
              <div className="bg-muted flex h-12 w-12 items-center justify-center rounded-2xl">
                <Key className="text-muted-foreground h-6 w-6" />
              </div>
            </div>

            <div className="space-y-1.5 text-center">
              <h2 className="text-foreground text-lg font-semibold">API 키를 등록해 주세요</h2>
              <p className="text-muted-foreground text-sm leading-6">
                서비스를 이용하려면 OpenAI, Gemini 등의 API 키가 필요합니다. 지금 등록하면 바로
                사용할 수 있어요.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => setSettingsOpen(true, 'apiKeys')}
                className="bg-foreground hover:bg-foreground/85 text-background w-full rounded-xl py-2.5 text-sm font-medium transition-colors"
              >
                API 키 등록하기
              </button>
              <button
                type="button"
                onClick={() => setApiDismissedSession(true)}
                className="text-muted-foreground hover:text-foreground w-full rounded-xl py-2 text-sm transition-colors"
              >
                나중에 하기
              </button>
              <button
                type="button"
                onClick={() => {
                  dismissUntilTomorrow(API_KEY_DISMISS_KEY)
                  setApiDismissedDaily(true)
                }}
                className="text-muted-foreground hover:text-foreground w-full rounded-xl py-1 text-xs transition-colors"
              >
                오늘 하루 보지 않기
              </button>
            </div>
          </div>
        )}

        {showBridgeCard && (
          <div className="bg-card border-border w-full space-y-5 rounded-2xl border p-6 shadow-2xl">
            <div className="flex justify-center">
              <div className="bg-muted flex h-12 w-12 items-center justify-center rounded-2xl">
                <Monitor className="text-muted-foreground h-6 w-6" />
              </div>
            </div>

            <div className="space-y-1.5 text-center">
              <h2 className="text-foreground text-lg font-semibold">
                브릿지 프로그램을 연결해 주세요
              </h2>
              <p className="text-muted-foreground text-sm leading-6">
                내 PC와 HeyGent를 잇는 브릿지가 아직 연결되지 않았어요. 페어링하면 로컬 기기 제어와
                연동 기능을 바로 사용할 수 있습니다.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <a
                href="/settings/bridge"
                className="bg-foreground hover:bg-foreground/85 text-background w-full rounded-xl py-2.5 text-center text-sm font-medium transition-colors"
              >
                브릿지 연결하기
              </a>
              <button
                type="button"
                onClick={() => setBridgeDismissedSession(true)}
                className="text-muted-foreground hover:text-foreground w-full rounded-xl py-2 text-sm transition-colors"
              >
                나중에 하기
              </button>
              <button
                type="button"
                onClick={() => {
                  dismissUntilTomorrow(BRIDGE_DISMISS_KEY)
                  setBridgeDismissedDaily(true)
                }}
                className="text-muted-foreground hover:text-foreground w-full rounded-xl py-1 text-xs transition-colors"
              >
                오늘 하루 보지 않기
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function WorkspaceRoutes() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/new-chat" element={<NewChatPage />} />
      <Route path="/agent-status" element={<BuildingOverviewPage />} />
      <Route path="/agent-status/:sessionId" element={<AgentStatusPage />} />
      {/*
       * 세션 페이지(/session/:sessionId 와 /session/:sessionId/workspace/...)는
       * 모두 같은 SessionShell 로 마운트한다. SessionShell 이 시각화 패널을
       * 항상 백그라운드로 한 번만 마운트하고 그 위에 채팅/다른 패널을 덮어
       * 와리가리 시 캐릭터 walkTimer/transition 이 끊기는 것을 막는다.
       */}
      <Route path="/session/:sessionId/*" element={<SessionShell />} />
      <Route path="/chat" element={<Navigate to="/new-chat" replace />} />
      <Route path="/agents" element={<Navigate to="/agent-status" replace />} />
      <Route path="/reminders" element={<Navigate to="/" replace />} />
      <Route path="/wellness" element={<Navigate to="/" replace />} />
      <Route path="/devices" element={<Navigate to="/" replace />} />
      <Route path="/settings/bridge" element={<BridgeSettingsPage />} />
      <Route path="/settings" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function SessionShell() {
  const location = useLocation()
  const { sessionId = '' } = useParams()
  const sessionsById = useChatStore((state) => state.sessionsById)
  const activePanel = getWorkspacePanelFromPath(location.pathname)
  // 시각화 패널을 한 번이라도 진입했는지 — 진입 후엔 영구 true 로 유지해야 컴포넌트가 안 죽는다.
  // React 공식 권장: "render 중에 prev state 와 새 state 를 비교해서 set" 하는 패턴 (한 번만 발생, 무한 루프 없음).
  // https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [visualizationVisited, setVisualizationVisited] = useState(false)
  if (activePanel === 'visualization' && !visualizationVisited) {
    setVisualizationVisited(true)
  }
  const visualizationVisible = activePanel === 'visualization'
  const isChat = activePanel === null

  if (sessionId === '') {
    return <Navigate to="/new-chat" replace />
  }

  // 시각화 패널은 한 번이라도 진입했으면 절대 언마운트되지 않는다.
  // 안 보일 때는 화면 밖으로 옮겨두지만 DOM/walkTimer/CSS transition 은 계속 살아있다.
  const visualizationNode = visualizationVisited ? (
    <div
      key="session-visualization-persistent"
      style={
        visualizationVisible
          ? {
              position: 'absolute',
              inset: 0,
              zIndex: 0,
              display: 'flex',
            }
          : {
              position: 'absolute',
              left: '-99999px',
              top: '-99999px',
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              visibility: 'hidden',
              display: 'flex',
            }
      }
      aria-hidden={!visualizationVisible}
    >
      <AgentStatusPage />
    </div>
  ) : null

  let overlayNode: ReactNode = null
  if (isChat) {
    overlayNode = <ChatSessionPage />
  } else if (activePanel !== null && activePanel !== 'visualization') {
    overlayNode = (
      <SessionWorkspaceDetailPanel
        activePanel={activePanel}
        sessionId={sessionId}
        session={sessionsById[sessionId] ?? null}
      />
    )
  }

  return (
    <div className="relative flex min-w-0 flex-1">
      {visualizationNode}
      {overlayNode !== null && (
        <div className="bg-background relative flex min-w-0 flex-1" style={{ zIndex: 1 }}>
          {overlayNode}
        </div>
      )}
    </div>
  )
}

function ThemeSync() {
  const theme = useUIStore((s) => s.theme)
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])
  return null
}

function AuthenticatedShell() {
  return (
    <>
      <ThemeSync />
      <div className="bg-background flex h-screen w-full overflow-hidden">
        <div className="hidden md:contents">
          <LeftSidebar />
        </div>
        <div className="hidden md:contents">
          <SessionWorkspaceSidebar />
        </div>
        <WorkspaceRoutes />
      </div>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/kakao/callback" element={<KakaoCallbackPage />} />
        <Route path="/auth/notion/callback" element={<NotionCallbackPage />} />
        <Route path="/auth/gmail/callback" element={<GmailCallbackPage />} />
        <Route
          path="*"
          element={
            <>
              <OnboardingOverlays />
              <AiRealtimeProvider>
                <FcmProvider>
                  <AuthenticatedShell />
                </FcmProvider>
              </AiRealtimeProvider>
            </>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
