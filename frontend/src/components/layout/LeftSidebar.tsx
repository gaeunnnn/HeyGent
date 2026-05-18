import { useMemo, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router'
import {
  Building2,
  ChevronRight,
  Loader2,
  LayoutDashboard,
  MessageSquare,
  Monitor,
  Moon,
  Plus,
  Sun,
  User,
  Settings,
  Key,
  Globe,
  LogOut,
  UserCircle,
  X,
  Edit3,
  Pin,
} from 'lucide-react'
import { useState } from 'react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { NewSessionModal, type CustomAgentConfig } from '@/components/session/NewSessionModal'
import { defaultAgentSessionConfig } from '@/components/session/defaultAgentSession'
import {
  getCurrentWorkspaceSessionId,
  getString,
  toJsonObject,
} from '@/components/sessionWorkspace/sessionWorkspaceUtils'
import { getSessionTime, isRemovedSidebarSession } from './sessionListUtils'
import { DEFAULT_SIDEBAR_COLLAPSED_WIDTH, useUIStore } from '@/store/useUIStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useAuthStore } from '@/store/useAuthStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useChatStore } from '@/store/useChatStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import { logout } from '@/apis/auth'
import { agentProfilesToPanelItems, createDefaultSessionAgents } from '@/apis/agents'
import { createSession as createAiSession } from '@/apis/sessions'
import { updateMyInfo } from '@/apis/users'
import type { ChatMessageView, RawAiSession } from '@/types/aiChat'
import type { RawTaskRun } from '@/types/taskRuns'
import { shouldClearSessionRunFromPersistedMessages } from '@/utils/chatLiveState'
import { isTerminalTaskRunStatus } from '@/utils/taskRunDisplayStatus'

type SidebarSession = {
  id: string
  title: string
  preview: string
  time: string
  isRunning: boolean
  raw: RawAiSession
}

export function LeftSidebar() {
  const {
    sidebarCollapsed: collapsed,
    settingsOpen,
    settingsInitialTab,
    settingsSingleTab,
    sidebarWidth,
    setSidebarCollapsed,
    setSidebarWidth,
    setSessionWorkspaceCollapsed,
    setSettingsOpen,
    theme,
    setTheme,
  } = useUIStore()
  const { setAgentPanelsForSession, setSelectedSessionId, pinnedSessionIds } = useSessionStore()
  const [profileOpen, setProfileOpen] = useState(false)
  const [newSessionModalOpen, setNewSessionModalOpen] = useState(false)
  const [newSessionCreating, setNewSessionCreating] = useState(false)
  const [newSessionError, setNewSessionError] = useState<string | null>(null)
  const realtimeStatus = useAiRealtimeStore((state) => state.connectionStatus)
  const sessionsById = useChatStore((state) => state.sessionsById)
  const messagesBySessionId = useChatStore((state) => state.messagesBySessionId)
  const taskRunsById = useTaskRunStore((state) => state.taskRunsById)
  const sessionListLoading = useChatStore((state) => state.sessionListLoading)
  const chatError = useChatStore((state) => state.sessionListError ?? state.lastError)
  const fetchSessions = useChatStore((state) => state.fetchSessions)
  const navigate = useNavigate()
  const location = useLocation()
  const currentWorkspaceSessionId = getCurrentWorkspaceSessionId(location.pathname)
  const sidebarSessions = useMemo(() => {
    const all = Object.values(sessionsById)
      .map((session) =>
        toSidebarSession(session, messagesBySessionId[session.session_id] ?? [], taskRunsById),
      )
      .filter((s) => !isRemovedSidebarSession(s.raw))
      .sort((first, second) => getSessionTime(second.raw) - getSessionTime(first.raw))
    const pinned = all.filter((s) => pinnedSessionIds.has(s.id))
    const unpinned = all.filter((s) => !pinnedSessionIds.has(s.id))
    return [...pinned, ...unpinned]
  }, [messagesBySessionId, pinnedSessionIds, sessionsById, taskRunsById])

  // fetchSessions 호출은 AiRealtimeProvider 의 auth.ok 핸들러가 단독으로 담당.
  // LeftSidebar 에서 또 호출하면 같은 명령이 2회 발사돼 사이드바 로드가 두 배 느려진다.

  const createDefaultAgentSession = (config: CustomAgentConfig) => {
    setNewSessionCreating(true)
    setNewSessionError(null)
    void createAiSession({
      title: '새 AI 세션',
      model: config.model.trim() || undefined,
      settings: {
        ...(config.persona.trim() ? { systemPrompt: config.persona.trim() } : {}),
        ...(config.model.trim() ? { model: config.model.trim() } : {}),
        delegationPolicy: config.delegationPolicy,
      },
      metadataPatch: {
        ui: {
          agentName: config.agentName,
          callName: config.callName,
          agentProfileImage: config.profileImage,
          instructionsEntryFile: config.instructionsEntryFile,
          instructionsMode: config.instructionsMode,
          instructionsRootPath: config.instructionsRootPath,
          instructionsFiles: config.instructionsFiles,
        },
      },
    })
      .then(async (session) => {
        const profiles = await createDefaultSessionAgents(session.session_id)
        setAgentPanelsForSession(session.session_id, agentProfilesToPanelItems(profiles))
        void fetchSessions().catch(() => undefined)
        setSelectedSessionId(session.session_id)
        setNewSessionModalOpen(false)
        setSidebarCollapsed(true)
        setSessionWorkspaceCollapsed(false)
        navigate(`/session/${session.session_id}`)
      })
      .catch((error) => {
        setNewSessionError(getNewSessionErrorMessage(error))
        setSidebarCollapsed(false)
      })
      .finally(() => {
        setNewSessionCreating(false)
      })
  }

  // + 버튼 클릭 시 즉시 기본 에이전트 세션 생성, 1초 이상 호버하면 새 세션 모달 열림
  const HOVER_THRESHOLD_MS = 1000
  const newChatHoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const newChatHoverFiredRef = useRef(false)

  const handleNewChatHoverStart = () => {
    if (newSessionCreating) return
    newChatHoverFiredRef.current = false
    if (newChatHoverTimer.current !== null) {
      clearTimeout(newChatHoverTimer.current)
    }
    newChatHoverTimer.current = setTimeout(() => {
      newChatHoverFiredRef.current = true
      setNewSessionModalOpen(true)
    }, HOVER_THRESHOLD_MS)
  }

  const handleNewChatHoverEnd = () => {
    if (newChatHoverTimer.current !== null) {
      clearTimeout(newChatHoverTimer.current)
      newChatHoverTimer.current = null
    }
  }

  const handleNewChatClick = () => {
    // 호버 타이머가 이미 모달을 띄웠으면 클릭은 무시
    if (newChatHoverFiredRef.current) {
      newChatHoverFiredRef.current = false
      return
    }
    if (newChatHoverTimer.current !== null) {
      clearTimeout(newChatHoverTimer.current)
      newChatHoverTimer.current = null
    }
    if (newSessionCreating) return
    createDefaultAgentSession(defaultAgentSessionConfig())
  }

  const handleOpenPrimaryRoute = (path: string) => {
    if (collapsed) {
      setSidebarCollapsed(false)
    }
    navigate(path)
  }

  const handleOpenChatSession = (sessionId: string, event?: React.MouseEvent) => {
    event?.stopPropagation()
    setSelectedSessionId(sessionId)
    if (!collapsed) {
      setSidebarCollapsed(true)
    }
    setSessionWorkspaceCollapsed(false)
    navigate(`/session/${sessionId}`)
  }

  const handleSidebarResizeStart = (event: React.PointerEvent<HTMLDivElement>) => {
    if (collapsed) return
    event.preventDefault()
    const startX = event.clientX
    const startWidth = sidebarWidth
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handlePointerMove = (moveEvent: PointerEvent) => {
      setSidebarWidth(startWidth + moveEvent.clientX - startX)
    }

    const handlePointerUp = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
  }

  return (
    <>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        sessionId={getCurrentWorkspaceSessionId(location.pathname) ?? undefined}
        initialTab={settingsInitialTab as 'apiKeys'}
        singleTab={settingsSingleTab}
      />
      <NewSessionModal
        error={newSessionError}
        open={newSessionModalOpen}
        onOpenChange={(open) => {
          if (newSessionCreating) return
          setNewSessionError(null)
          setNewSessionModalOpen(open)
        }}
        submitting={newSessionCreating}
        onConfirm={(config) => {
          if (config?.seedDefaultAgents) {
            createDefaultAgentSession(config)
            return
          }
          storePendingSessionConfig(config)
          setNewSessionModalOpen(false)
          if (config && !config.seedDefaultAgents) {
            setSidebarCollapsed(false)
            navigate('/agent-status')
          } else {
            setSidebarCollapsed(true)
            navigate('/new-chat')
          }
        }}
      />

      <div
        className="bg-background border-border relative flex shrink-0 flex-col overflow-hidden border-r transition-[width] duration-200 ease-in-out"
        style={{ width: collapsed ? DEFAULT_SIDEBAR_COLLAPSED_WIDTH : sidebarWidth }}
      >
        {!collapsed && (
          <div
            role="separator"
            aria-label="사이드바 너비 조절"
            className="hover:bg-primary/40 absolute top-0 right-0 z-20 h-full w-1 cursor-col-resize touch-none transition-colors"
            onPointerDown={handleSidebarResizeStart}
          />
        )}
        {/* ── Collapsed Rail ── */}
        {collapsed && (
          <div className="flex h-full flex-col items-center gap-1.5 px-2 py-4">
            <div className="flex h-12 shrink-0 items-center justify-center">
              <button
                type="button"
                onClick={() => handleOpenPrimaryRoute('/agent-status')}
                className="flex h-12 w-12 items-center justify-center rounded-xl"
                aria-label="내 사무실로 이동"
              >
                <img
                  src="/img_logo_light.png"
                  alt="HeyGent"
                  className="h-9 w-9 object-contain dark:hidden"
                />
                <img
                  src="/img_logo_dark.png"
                  alt="HeyGent"
                  className="hidden h-9 w-9 object-contain dark:block"
                />
              </button>
            </div>

            <div className="bg-border my-1 h-px w-10" />

            <CollapsedTooltip label="내 사무실">
              <button
                type="button"
                onClick={() => handleOpenPrimaryRoute('/agent-status')}
                className={`hover:bg-accent/50 flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                  location.pathname.startsWith('/agent-status')
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                aria-label="내 사무실로 이동"
              >
                <Building2 className="h-5 w-5" />
              </button>
            </CollapsedTooltip>

            <CollapsedTooltip label="대시보드">
              <button
                type="button"
                onClick={() => handleOpenPrimaryRoute('/')}
                className={`hover:bg-accent/50 flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                  location.pathname === '/'
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                aria-label="대시보드로 이동"
              >
                <LayoutDashboard className="h-5 w-5" />
              </button>
            </CollapsedTooltip>

            <div className="bg-border my-1 h-px w-10" />

            {/* New Chat button — 클릭=기본 에이전트 즉시 생성 / 1초 이상 호버=새 세션 모달 */}
            <CollapsedTooltip label="새 세션 (길게 누르면 옵션 선택)">
              <button
                type="button"
                onClick={handleNewChatClick}
                onMouseEnter={handleNewChatHoverStart}
                onMouseLeave={handleNewChatHoverEnd}
                onFocus={handleNewChatHoverStart}
                onBlur={handleNewChatHoverEnd}
                disabled={newSessionCreating}
                className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-12 w-12 items-center justify-center rounded-xl transition-colors disabled:opacity-50"
              >
                <Plus className="h-5 w-5" />
              </button>
            </CollapsedTooltip>

            <div className="min-h-0 w-full flex-1 overflow-x-hidden overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <div className="flex flex-col items-center gap-1.5">
                {newSessionCreating && (
                  <CollapsedTooltip label="새 세션을 만드는 중...">
                    <div
                      aria-label="새 세션을 만드는 중"
                      className="bg-accent/30 text-muted-foreground flex h-12 w-12 items-center justify-center rounded-xl"
                    >
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                  </CollapsedTooltip>
                )}
                {sidebarSessions.map((session) => (
                  <CollapsedTooltip key={session.id} label={session.title}>
                    <button
                      type="button"
                      onClick={(event) => handleOpenChatSession(session.id, event)}
                      aria-label={`${session.title} 채팅 열기`}
                      className={`hover:bg-accent/50 relative flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                        currentWorkspaceSessionId === session.id
                          ? 'bg-accent text-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {session.isRunning && (
                        <Loader2 className="text-primary absolute top-1 right-1 h-3 w-3 animate-spin" />
                      )}
                      <MessageSquare className="h-5 w-5" />
                    </button>
                  </CollapsedTooltip>
                ))}
              </div>
            </div>

            {/* Theme toggle (collapsed) */}
            <CollapsedTooltip label={theme === 'dark' ? '라이트 모드' : '다크 모드'}>
              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-12 w-12 items-center justify-center rounded-xl transition-colors"
                aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
              >
                {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              </button>
            </CollapsedTooltip>

            {/* Profile (collapsed) — 우측 SessionWorkspaceMenu의 border-t 위치와 정렬 */}
            <div className="border-border -mx-2 mt-1.5 -mb-4 flex shrink-0 justify-center self-stretch border-t py-3">
              <Popover open={profileOpen} onOpenChange={setProfileOpen}>
                <PopoverTrigger asChild>
                  <button
                    aria-label="프로필"
                    className="hover:bg-accent/50 flex h-10 w-10 items-center justify-center rounded-xl transition-colors"
                  >
                    <ProfileAvatar size={28} />
                  </button>
                </PopoverTrigger>
                <PopoverContent side="right" align="end" className="w-52 rounded-2xl p-1.5">
                  <ProfileMenu
                    onOpenApiKeys={() => {
                      setProfileOpen(false)
                      setSettingsOpen(true, 'apiKeys', { singleTab: true })
                    }}
                    onOpenExternal={() => {
                      setProfileOpen(false)
                      setSettingsOpen(true, 'external', { singleTab: true })
                    }}
                    onOpenBridge={() => {
                      setProfileOpen(false)
                      navigate('/settings/bridge')
                    }}
                  />
                </PopoverContent>
              </Popover>
            </div>
          </div>
        )}

        {/* ── Expanded Panel ── */}
        {!collapsed && (
          <div className="flex h-full flex-col overflow-hidden">
            <div className="flex h-12 shrink-0 items-center overflow-hidden px-3">
              <button
                type="button"
                onClick={() => handleOpenPrimaryRoute('/agent-status')}
                className="flex h-full w-full min-w-0 items-center justify-center rounded-lg p-0"
                aria-label="내 사무실로 이동"
              >
                <img
                  src="/text_logo_light.png"
                  alt="HeyGent"
                  className="h-7 w-auto max-w-[220px] shrink-0 scale-[2] object-contain dark:hidden"
                />
                <img
                  src="/text_logo_dark.png"
                  alt="HeyGent"
                  className="hidden h-7 w-auto max-w-[220px] shrink-0 scale-[2] object-contain dark:block"
                />
              </button>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-3 py-3">
              <nav className="flex shrink-0 flex-col gap-1">
                <button
                  type="button"
                  onClick={() => handleOpenPrimaryRoute('/agent-status')}
                  className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm font-medium transition-colors ${
                    location.pathname.startsWith('/agent-status')
                      ? 'bg-accent text-foreground'
                      : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Building2 className="h-5 w-5 shrink-0" />
                  <span>내 사무실</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleOpenPrimaryRoute('/')}
                  className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm font-medium transition-colors ${
                    location.pathname === '/'
                      ? 'bg-accent text-foreground'
                      : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <LayoutDashboard className="h-5 w-5 shrink-0" />
                  <span>대시보드</span>
                </button>
              </nav>

              {/* ── Sessions ── */}
              <section className="mt-4 flex min-h-0 flex-1 flex-col">
                <div className="text-muted-foreground/60 px-2.5 py-1.5 font-mono text-[10px] font-medium tracking-widest">
                  <span>대화 세션</span>
                </div>
                <div className="mt-0.5 flex shrink-0 flex-col gap-0.5">
                  <button
                    onClick={handleNewChatClick}
                    onMouseEnter={handleNewChatHoverStart}
                    onMouseLeave={handleNewChatHoverEnd}
                    onFocus={handleNewChatHoverStart}
                    onBlur={handleNewChatHoverEnd}
                    disabled={newSessionCreating}
                    title="클릭하면 기본 에이전트로 새 세션이 시작됩니다. 길게 누르면 옵션을 선택할 수 있어요."
                    className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    <Plus className="text-muted-foreground h-5 w-5 shrink-0" />
                    <span className="text-muted-foreground truncate text-sm">새 세션</span>
                  </button>
                </div>
                <div className="mt-0.5 min-h-0 flex-1 overflow-x-hidden overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                  <div className="flex flex-col gap-0.5">
                    {newSessionCreating && (
                      <div
                        aria-label="새 세션을 만드는 중"
                        className="text-muted-foreground bg-accent/30 flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-sm"
                      >
                        <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="bg-muted-foreground/20 h-3 w-2/3 animate-pulse rounded" />
                          <div className="bg-muted-foreground/15 h-2 w-1/2 animate-pulse rounded" />
                        </div>
                      </div>
                    )}
                    {sidebarSessions.map((session) => {
                      const isActive = currentWorkspaceSessionId === session.id
                      const isPinned = pinnedSessionIds.has(session.id)
                      return (
                        <button
                          type="button"
                          key={session.id}
                          onClick={() => {
                            setSelectedSessionId(session.id)
                            setSidebarCollapsed(true)
                            setSessionWorkspaceCollapsed(false)
                            navigate(`/session/${session.id}`)
                          }}
                          className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm font-medium transition-colors ${
                            isActive
                              ? 'bg-accent text-foreground'
                              : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                          }`}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1">
                              {isPinned && <Pin className="text-primary h-3 w-3 shrink-0" />}
                              <p className="truncate">{session.title}</p>
                            </div>
                          </div>
                          {session.isRunning && (
                            <Loader2 className="text-primary h-3.5 w-3.5 shrink-0 animate-spin" />
                          )}
                        </button>
                      )
                    })}
                    {sidebarSessions.length === 0 && (
                      <EmptySessionNotice
                        realtimeStatus={realtimeStatus}
                        loading={sessionListLoading}
                        error={chatError}
                      />
                    )}
                  </div>
                </div>
              </section>
            </div>

            {/* ── Profile Footer (Fixed) ── */}
            <div className="border-border flex shrink-0 items-center gap-2 border-t px-3 py-3">
              <Popover open={profileOpen} onOpenChange={setProfileOpen}>
                <PopoverTrigger asChild>
                  <button className="hover:bg-accent/50 flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition-colors">
                    <ProfileAvatar size={20} />
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground truncate text-sm font-medium">
                        <ProfileName />
                      </p>
                    </div>
                  </button>
                </PopoverTrigger>
                <PopoverContent side="top" align="start" className="w-52 rounded-2xl p-1.5">
                  <ProfileMenu
                    onOpenApiKeys={() => {
                      setProfileOpen(false)
                      setSettingsOpen(true, 'apiKeys', { singleTab: true })
                    }}
                    onOpenExternal={() => {
                      setProfileOpen(false)
                      setSettingsOpen(true, 'external', { singleTab: true })
                    }}
                    onOpenBridge={() => {
                      setProfileOpen(false)
                      navigate('/settings/bridge')
                    }}
                  />
                </PopoverContent>
              </Popover>
              <button
                type="button"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors"
                aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
                title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
              >
                {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}

function storePendingSessionConfig(config: CustomAgentConfig | undefined) {
  if (config === undefined) {
    sessionStorage.removeItem('ai-new-session-config')
    return
  }
  sessionStorage.setItem('ai-new-session-config', JSON.stringify(config))
}

function getNewSessionErrorMessage(error: unknown) {
  if (isAxiosLikeError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail
    }
  }
  return error instanceof Error ? error.message : '세션을 만들지 못했습니다.'
}

function isAxiosLikeError(error: unknown): error is { response?: { data?: { detail?: unknown } } } {
  return typeof error === 'object' && error !== null && 'response' in error
}

function EmptySessionNotice({
  realtimeStatus,
  loading,
  error,
}: {
  realtimeStatus: string
  loading: boolean
  error: string | null
}) {
  const message =
    error ??
    (loading ? '세션 목록을 불러오는 중입니다.' : null) ??
    (realtimeStatus === 'authenticated' ? '아직 표시할 대화 세션이 없습니다.' : '서버 연결 준비 중')

  return (
    <div className="border-border text-muted-foreground border border-dashed p-3 text-xs leading-5">
      {message}
    </div>
  )
}

function toSidebarSession(
  session: RawAiSession,
  messages: ChatMessageView[],
  taskRunsById: Record<string, RawTaskRun>,
): SidebarSession {
  // 세션 워크스페이스 메뉴에서 이름을 수정하면 metadata.ui.sessionName에 저장되므로,
  // 사이드바도 동일한 우선순위(metadata.ui.sessionName → session.title → session_key)로 표시한다.
  const metadata = toJsonObject(session.metadata)
  const uiMetadata = toJsonObject(metadata.ui)
  const title =
    getString(uiMetadata, 'sessionName') ??
    getStringValue(session.title) ??
    getStringValue(session.session_key) ??
    `세션 ${session.session_id}`
  const preview =
    getStringValue(session.last_message) ??
    getStringValue(session.preview) ??
    getMessageCountPreview(session) ??
    '대화 내용 없음'
  const activeTaskRunId =
    getStringValue(session.active_task_run_id) ?? getStringValue(session.activeTaskRunId)
  const taskRunStatus =
    getStringValue(session.last_task_run_status) ?? getStringValue(session.lastTaskRunStatus)

  return {
    id: session.session_id,
    title,
    preview,
    time: formatSessionTime(session),
    isRunning: isSidebarSessionRunning(
      session,
      messages,
      taskRunsById,
      activeTaskRunId,
      taskRunStatus,
    ),
    raw: session,
  }
}

function isSidebarSessionRunning(
  session: RawAiSession,
  messages: ChatMessageView[],
  taskRunsById: Record<string, RawTaskRun>,
  activeTaskRunId: string | undefined,
  taskRunStatus: string | undefined,
) {
  if (
    activeTaskRunId !== undefined &&
    isTerminalTaskRunStatus(taskRunsById[activeTaskRunId]?.status)
  ) {
    return false
  }
  if (shouldClearSessionRunFromPersistedMessages(session, messages)) {
    return false
  }
  if (activeTaskRunId !== undefined && taskRunStatus === undefined) {
    return taskRunsById[activeTaskRunId] !== undefined
  }
  return isRunningTaskRunStatus(taskRunStatus)
}

function getStringValue(value: unknown) {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined
}

function getMessageCountPreview(session: RawAiSession) {
  const count = typeof session.message_count === 'number' ? session.message_count : undefined
  if (count === undefined) {
    return undefined
  }
  return `${count}개 메시지`
}

function formatSessionTime(session: RawAiSession) {
  const time = getSessionTime(session)
  if (time === 0) {
    return '시간 정보 없음'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(time))
}

function isRunningTaskRunStatus(status: string | undefined) {
  return status === 'PENDING' || status === 'RUNNING' || status === 'WAITING'
}

// ────────────────────────────────────────────────────────────────────────────
// Collapsed tooltip
// ────────────────────────────────────────────────────────────────────────────
function CollapsedTooltip({ label, children }: { label: string; children: React.ReactNode }) {
  const [visible, setVisible] = useState(false)
  return (
    <div
      className="relative"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div className="bg-foreground text-background pointer-events-none absolute top-1/2 left-full z-100 ml-2 -translate-y-1/2 rounded-md px-2 py-1 text-xs font-medium whitespace-nowrap shadow-lg">
          {label}
          <div
            className="pointer-events-none absolute top-1/2 -left-1.5 -translate-y-1/2"
            style={{
              borderWidth: '4px',
              borderStyle: 'solid',
              borderColor: 'transparent',
              borderRightColor: 'var(--foreground)',
            }}
          />
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Profile helpers
// ────────────────────────────────────────────────────────────────────────────
function ProfileAvatar({ size = 36 }: { size?: number }) {
  const userInfo = useAuthStore((s) => s.userInfo)
  if (userInfo?.profileImage) {
    return (
      <img
        src={userInfo.profileImage}
        alt="프로필"
        className="shrink-0 rounded-full object-cover"
        style={{ width: size, height: size }}
      />
    )
  }
  return (
    <div
      className="bg-primary/10 border-primary/20 flex shrink-0 items-center justify-center rounded-full border"
      style={{ width: size, height: size }}
    >
      <User className="text-primary h-4 w-4" />
    </div>
  )
}

function ProfileName() {
  const userInfo = useAuthStore((s) => s.userInfo)
  return <>{userInfo?.nickname ?? '사용자'}</>
}

// ────────────────────────────────────────────────────────────────────────────
// Profile Menu Component
// ────────────────────────────────────────────────────────────────────────────
function ProfileMenu({
  onOpenApiKeys,
  onOpenExternal,
  onOpenBridge,
}: {
  onOpenApiKeys: () => void
  onOpenExternal: () => void
  onOpenBridge: () => void
}) {
  const [view, setView] = useState<'menu' | 'profile'>('menu')
  const [settingsSubOpen, setSettingsSubOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const { refreshToken, clearTokens, userInfo, setUserInfo } = useAuthStore()
  const navigate = useNavigate()
  const [nickname, setNickname] = useState(userInfo?.nickname ?? '')

  const handleConfirmLogout = async () => {
    if (isLoggingOut) return
    setIsLoggingOut(true)
    try {
      if (refreshToken) await logout(refreshToken)
    } finally {
      clearTokens()
      navigate('/login', { replace: true })
    }
  }

  if (view === 'profile') {
    return (
      <div className="p-2">
        <div className="mb-3 flex items-center justify-between pl-1">
          <h3 className="text-foreground text-sm font-semibold">프로필</h3>
          <button
            onClick={() => setView('menu')}
            className="hover:bg-muted flex h-6 w-6 items-center justify-center rounded-md transition-colors"
          >
            <X className="text-muted-foreground h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          {/* Nickname Input */}
          <div>
            <label className="text-muted-foreground mb-1.5 block pl-1 text-xs font-medium">
              이름
            </label>
            <div className="relative">
              <input
                type="text"
                value={nickname}
                onChange={(e) => {
                  setNickname(e.target.value)
                  setSaveError(null)
                }}
                maxLength={100}
                disabled={isSaving}
                className="border-border bg-background text-foreground focus:ring-primary/20 w-full rounded-lg border py-2 pr-10 pl-3 text-sm focus:ring-2 focus:outline-none disabled:opacity-60"
              />
              <button
                onClick={async () => {
                  const trimmed = nickname.trim()
                  if (!trimmed || isSaving) return
                  setIsSaving(true)
                  setSaveError(null)
                  try {
                    const res = await updateMyInfo({ nickname: trimmed })
                    setUserInfo(res.data)
                  } catch {
                    setSaveError('저장에 실패했습니다.')
                  } finally {
                    setIsSaving(false)
                  }
                }}
                disabled={isSaving || !nickname.trim()}
                aria-label="이름 저장"
                className="text-muted-foreground hover:bg-muted hover:text-foreground absolute top-1/2 right-1.5 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md transition-colors disabled:opacity-50"
              >
                {isSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Edit3 className="h-4 w-4" />
                )}
              </button>
            </div>
            {saveError && <p className="mt-1 text-xs text-red-500">{saveError}</p>}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-0.5">
      <button
        onClick={() => setView('profile')}
        className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors"
      >
        <UserCircle className="text-muted-foreground h-4 w-4 shrink-0" />
        <span className="text-foreground text-sm">프로필</span>
      </button>

      {/* 설정 — 우측에 nested 오버레이 */}
      <Popover open={settingsSubOpen} onOpenChange={setSettingsSubOpen}>
        <PopoverTrigger asChild>
          <button className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors">
            <Settings className="text-muted-foreground h-4 w-4 shrink-0" />
            <span className="text-foreground flex-1 text-sm">설정</span>
            <ChevronRight className="text-muted-foreground h-4 w-4 shrink-0" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="right"
          align="start"
          sideOffset={8}
          className="w-52 rounded-2xl p-1.5"
        >
          <div className="space-y-0.5">
            <button
              onClick={() => {
                setSettingsSubOpen(false)
                onOpenApiKeys()
              }}
              className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors"
            >
              <Key className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-foreground text-sm">API 키</span>
            </button>
            <button
              onClick={() => {
                setSettingsSubOpen(false)
                onOpenExternal()
              }}
              className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors"
            >
              <Globe className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-foreground text-sm">외부 서비스</span>
            </button>
            <button
              onClick={() => {
                setSettingsSubOpen(false)
                onOpenBridge()
              }}
              className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors"
            >
              <Monitor className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-foreground text-sm">내 PC 브릿지</span>
            </button>
          </div>
        </PopoverContent>
      </Popover>

      <div className="border-border/70 mt-1 border-t pt-1">
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button
              disabled={isLoggingOut}
              className="flex w-full items-center gap-3 rounded-xl bg-red-50 px-3 py-2.5 text-red-600 transition-colors hover:bg-red-100 disabled:opacity-60"
            >
              <LogOut className="h-4 w-4 shrink-0" />
              <span className="text-sm font-medium">
                {isLoggingOut ? '로그아웃 중...' : '로그아웃'}
              </span>
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>로그아웃할까요?</AlertDialogTitle>
              <AlertDialogDescription>
                현재 계정에서 로그아웃하고 로그인 화면으로 이동합니다.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogAction
                disabled={isLoggingOut}
                onClick={() => void handleConfirmLogout()}
                className="bg-red-600 text-white hover:bg-red-700"
              >
                {isLoggingOut ? '로그아웃 중...' : '로그아웃'}
              </AlertDialogAction>
              <AlertDialogCancel disabled={isLoggingOut}>취소</AlertDialogCancel>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
