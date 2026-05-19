import { useState } from 'react'
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Edit3,
  FolderKanban,
  GitBranch,
  Loader2,
  Map,
  MessageSquare,
  Palette,
  Plus,
  Target,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { SubAgentProfileImage } from '@/components/sessionWorkspace/subAgents'
import { useAgentVisualizationStore } from '@/store/useAgentVisualizationStore'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { DEFAULT_SIDEBAR_COLLAPSED_WIDTH, useUIStore } from '@/store/useUIStore'
import type { RawAiSession } from '@/types/aiChat'
import { getString, toJsonObject } from './sessionWorkspaceUtils'
import type { WorkspaceNavId, WorkspacePanelId } from './sessionWorkspaceTypes'

interface SessionWorkspaceMenuProps {
  activePanel: WorkspacePanelId | null
  collapsed: boolean
  currentRoute: 'chat' | 'visualization'
  session: RawAiSession | null
  sessionId: string
  activeSubAgentId: string | null
  onCollapsedChange: (collapsed: boolean) => void
  onCreateSubAgent: () => void
  onDeleteSession: () => Promise<void>
  onOpenSubAgent: (agentPanelId: string) => void
  onSelectPanel: (panelId: WorkspaceNavId) => void
}

const MENU_ITEMS: Array<{
  id: Exclude<WorkspaceNavId, 'ceo' | 'subAgents'>
  label: string
  icon: typeof Target
}> = [
  { id: 'chat', label: '채팅', icon: MessageSquare },
  { id: 'visualization', label: '시각화', icon: Map },
  { id: 'workflow', label: '워크플로우', icon: GitBranch },
  { id: 'issueBoard', label: '작업', icon: FolderKanban },
]

export function SessionWorkspaceMenu({
  activePanel,
  collapsed,
  currentRoute,
  session,
  sessionId,
  activeSubAgentId,
  onCollapsedChange,
  onCreateSubAgent,
  onDeleteSession,
  onOpenSubAgent,
  onSelectPanel,
}: SessionWorkspaceMenuProps) {
  const updateSession = useChatStore((state) => state.updateSession)
  const updateAgentInfo = useAgentVisualizationStore((state) => state.updateAgentInfo)
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const setSidebarWidth = useUIStore((state) => state.setSidebarWidth)
  const prototypePanelSessionId = useUIStore((state) => state.prototypePanelSessionId)
  const requestPrototypePanel = useUIStore((state) => state.requestPrototypePanel)
  const { agentPanelsBySessionId } = useSessionStore()
  const sessionDraftName = useSessionStore(
    (state) => state.mainAgentNameDraftBySessionId[sessionId],
  )
  const agentPanels = agentPanelsBySessionId[sessionId] ?? []
  const title = getSessionTitle(session)
  const persistedMainAgentName = getMainAgentName(session)
  const mainAgentName = sessionDraftName?.trim() ? sessionDraftName : persistedMainAgentName
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState(title)
  const [titleSaving, setTitleSaving] = useState(false)
  const [editingMainAgent, setEditingMainAgent] = useState(false)
  const [mainAgentDraft, setMainAgentDraft] = useState(mainAgentName)
  const [mainAgentSaving, setMainAgentSaving] = useState(false)
  const [lastSyncedMainAgentName, setLastSyncedMainAgentName] = useState(mainAgentName)
  if (!editingMainAgent && lastSyncedMainAgentName !== mainAgentName) {
    setLastSyncedMainAgentName(mainAgentName)
    setMainAgentDraft(mainAgentName)
  }
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const showPrototypeButton = prototypePanelSessionId === sessionId

  const handleSaveTitle = async () => {
    const trimmed = titleDraft.trim()
    if (session === null || trimmed === '' || trimmed === title) {
      setTitleDraft(title)
      setEditingTitle(false)
      return
    }

    const metadata = toJsonObject(session.metadata)
    const uiMetadata = toJsonObject(metadata.ui)
    const nextUiMetadata = { ...uiMetadata, sessionName: trimmed }

    // 옵티미스틱: UI는 즉시 닫고 사이드바 표시명도 곧바로 새 이름으로 반영.
    setEditingTitle(false)
    const previousSession = session
    patchSessionInStore(session.session_id, {
      ...session,
      metadata: { ...metadata, ui: nextUiMetadata },
    })

    setTitleSaving(true)
    try {
      await updateSession({
        sessionId: session.session_id,
        metadataPatch: { ui: nextUiMetadata },
      })
    } catch (error) {
      // 실패하면 이전 세션 상태로 롤백
      patchSessionInStore(previousSession.session_id, previousSession)
      console.error('세션 이름 저장에 실패했습니다.', error)
    } finally {
      setTitleSaving(false)
    }
  }

  const handleSaveMainAgentName = async () => {
    const trimmed = mainAgentDraft.trim()
    if (session === null || trimmed === '' || trimmed === mainAgentName) {
      setMainAgentDraft(mainAgentName)
      setEditingMainAgent(false)
      return
    }

    const metadata = toJsonObject(session.metadata)
    const uiMetadata = toJsonObject(metadata.ui)
    const nextUiMetadata = { ...uiMetadata, agentName: trimmed }

    // 옵티미스틱: 편집 모드 즉시 닫고, 사이드바·채팅·시각화 store도 즉시 새 이름으로.
    setEditingMainAgent(false)
    const previousSession = session
    const previousCeoName = useAgentVisualizationStore.getState().agentInfoMap.ceo?.name ?? null
    patchSessionInStore(session.session_id, {
      ...session,
      metadata: { ...metadata, ui: nextUiMetadata },
    })
    updateAgentInfo('ceo', { name: trimmed })

    setMainAgentSaving(true)
    try {
      await updateSession({
        sessionId: session.session_id,
        metadataPatch: { ui: nextUiMetadata },
      })
    } catch (error) {
      // 실패하면 이전 상태로 롤백
      patchSessionInStore(previousSession.session_id, previousSession)
      if (previousCeoName !== null) {
        updateAgentInfo('ceo', { name: previousCeoName })
      }
      console.error('팀장 에이전트 이름 저장에 실패했습니다.', error)
    } finally {
      setMainAgentSaving(false)
    }
  }

  const handleDeleteSession = async () => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDeleteSession()
      setDeleteDialogOpen(false)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : '대화를 삭제하지 못했습니다.')
    } finally {
      setDeleting(false)
    }
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

  if (collapsed) {
    return (
      <aside
        className="bg-background border-border relative flex h-full shrink-0 flex-col items-center gap-1.5 overflow-hidden border-r px-2 py-4 transition-[width] duration-200 ease-in-out"
        style={{ width: DEFAULT_SIDEBAR_COLLAPSED_WIDTH }}
      >
        <div className="flex h-12 items-center justify-center">
          <button
            type="button"
            onClick={() => onCollapsedChange(false)}
            className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-12 w-12 items-center justify-center rounded-xl transition-colors"
            aria-label="세션 메뉴 펼치기"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
        {showPrototypeButton && (
          <div className="flex h-12 items-center justify-center">
            <button
              type="button"
              onClick={() => requestPrototypePanel(sessionId)}
              className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-12 w-12 items-center justify-center rounded-xl transition-colors"
              aria-label="프로토타입 패널 열기"
            >
              <Palette className="h-5 w-5" />
            </button>
          </div>
        )}
        <div className="mt-auto flex h-12 items-center justify-center">
          <button
            type="button"
            onClick={() => setDeleteDialogOpen(true)}
            className="text-destructive hover:bg-destructive/10 hover:text-destructive flex h-12 w-12 items-center justify-center rounded-xl transition-colors"
            aria-label="대화 삭제"
          >
            <Trash2 className="h-5 w-5" />
          </button>
        </div>
        <DeleteSessionDialog
          deleteError={deleteError}
          deleting={deleting}
          open={deleteDialogOpen}
          sessionTitle={title}
          onConfirm={() => void handleDeleteSession()}
          onOpenChange={(open) => {
            if (!open && !deleting) setDeleteError(null)
            setDeleteDialogOpen(open)
          }}
        />
      </aside>
    )
  }

  return (
    <aside
      className="bg-background border-border relative flex h-full shrink-0 flex-col border-r"
      style={{ width: sidebarWidth }}
    >
      <div className="flex h-14 shrink-0 items-center gap-1 px-4 pt-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {editingTitle ? (
            <input
              autoFocus
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.target.value)}
              onBlur={() => void handleSaveTitle()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.currentTarget.blur()
                }
                if (event.key === 'Escape') {
                  setTitleDraft(title)
                  setEditingTitle(false)
                }
              }}
              className="border-border bg-background text-foreground focus:ring-ring h-8 min-w-0 flex-1 border px-2 text-sm font-medium outline-none focus:ring-1"
            />
          ) : (
            <h2 className="text-foreground truncate text-sm font-semibold">{title}</h2>
          )}
          {session !== null && (
            <button
              type="button"
              onClick={() => {
                setTitleDraft(title)
                setEditingTitle(true)
              }}
              className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-colors"
              aria-label="세션 이름 편집"
            >
              {titleSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : editingTitle ? (
                <Check className="h-4 w-4" />
              ) : (
                <Edit3 className="h-4 w-4" />
              )}
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => onCollapsedChange(true)}
          className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors"
          aria-label="세션 메뉴 접기"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 py-3">
        <div>
          <div className="mt-0.5 flex flex-col gap-0.5">
            {MENU_ITEMS.map((item) => {
              const Icon = item.icon
              const isActive =
                activePanel === null ? currentRoute === item.id : activePanel === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectPanel(item.id)}
                  className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-accent text-foreground'
                      : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                  }`}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <span className="block truncate">{item.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        <section>
          <SectionHeader label="팀장 에이전트" />
          <div className="group/main relative flex items-center">
            {editingMainAgent ? (
              <div
                className={`flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2.5 py-2.5 pr-8 text-left text-sm font-medium ${
                  activePanel === 'ceo' ? 'bg-accent text-foreground' : 'text-foreground/80'
                }`}
              >
                <img
                  src="/assets/agents/ceo/ceo_profile.png"
                  alt="팀장"
                  draggable={false}
                  className="h-6 w-6 shrink-0 object-contain"
                />
                <input
                  autoFocus
                  value={mainAgentDraft}
                  onChange={(event) => setMainAgentDraft(event.target.value)}
                  onBlur={() => void handleSaveMainAgentName()}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.currentTarget.blur()
                    }
                    if (event.key === 'Escape') {
                      setMainAgentDraft(mainAgentName)
                      setEditingMainAgent(false)
                    }
                  }}
                  className="border-border bg-background text-foreground focus:ring-ring h-7 min-w-0 flex-1 border px-2 text-sm font-medium outline-none focus:ring-1"
                />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => onSelectPanel('ceo')}
                className={`flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2.5 py-2.5 pr-8 text-left text-sm font-medium transition-colors ${
                  activePanel === 'ceo'
                    ? 'bg-accent text-foreground'
                    : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                }`}
              >
                <img
                  src="/assets/agents/ceo/ceo_profile.png"
                  alt="팀장"
                  draggable={false}
                  className="h-6 w-6 shrink-0 object-contain"
                />
                <span className="truncate">{mainAgentName}</span>
              </button>
            )}
            {session !== null && (
              <button
                type="button"
                onMouseDown={(event) => {
                  if (editingMainAgent) {
                    event.preventDefault()
                  }
                }}
                onClick={() => {
                  if (editingMainAgent) {
                    void handleSaveMainAgentName()
                  } else {
                    setMainAgentDraft(mainAgentName)
                    setEditingMainAgent(true)
                  }
                }}
                className="text-muted-foreground hover:bg-accent/50 hover:text-foreground absolute top-1/2 right-1 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg transition-colors"
                aria-label={
                  editingMainAgent
                    ? '팀장 에이전트 이름 저장'
                    : `${mainAgentName} 팀장 에이전트 이름 편집`
                }
              >
                {mainAgentSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : editingMainAgent ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Edit3 className="h-4 w-4" />
                )}
              </button>
            )}
          </div>
        </section>

        <section>
          <div className="group flex items-center">
            <button
              type="button"
              onClick={() => onSelectPanel('subAgents')}
              className="flex min-w-0 flex-1 items-center gap-1 rounded-lg px-2.5 py-1.5 text-left"
            >
              <ChevronRight className="text-muted-foreground/60 h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
              <span className="text-muted-foreground/60 font-mono text-[10px] font-medium tracking-widest uppercase">
                에이전트
              </span>
            </button>
            <button
              type="button"
              onClick={onCreateSubAgent}
              className="text-muted-foreground/60 hover:bg-accent/50 hover:text-foreground mr-1 flex h-7 w-7 items-center justify-center rounded-lg transition-colors"
              aria-label="에이전트 추가"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-0.5">
            {agentPanels.length === 0 ? (
              <p className="text-muted-foreground px-2.5 py-2.5 text-sm font-medium">
                추가된 에이전트 없음
              </p>
            ) : (
              <div className="flex flex-col gap-0.5">
                {agentPanels.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onOpenSubAgent(item.id)}
                    className={`flex min-w-0 items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm font-medium transition-colors ${
                      activePanel === 'subAgents' && activeSubAgentId === item.id
                        ? 'bg-accent text-foreground'
                        : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground'
                    }`}
                  >
                    <SubAgentProfileImage
                      accent={item.agent.accent}
                      profileImage={item.agent.profileImage}
                      spriteId={item.agent.spriteId}
                    />
                    <span className="truncate">{item.agent.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>
      </nav>
      <div className="border-border/70 shrink-0 border-t px-3 py-3">
        <button
          type="button"
          onClick={() => setDeleteDialogOpen(true)}
          className="text-destructive hover:bg-destructive/10 hover:text-destructive flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-sm font-medium transition-colors"
        >
          <Trash2 className="h-4 w-4 shrink-0" />
          <span className="truncate">대화 삭제</span>
        </button>
      </div>
      <div
        role="separator"
        aria-label="사이드바 너비 조절"
        className="hover:bg-primary/40 absolute top-0 right-0 z-20 h-full w-1 cursor-col-resize touch-none transition-colors"
        onPointerDown={handleSidebarResizeStart}
      />
      <DeleteSessionDialog
        deleteError={deleteError}
        deleting={deleting}
        open={deleteDialogOpen}
        sessionTitle={title}
        onConfirm={() => void handleDeleteSession()}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteError(null)
          setDeleteDialogOpen(open)
        }}
      />
    </aside>
  )
}

function DeleteSessionDialog({
  deleteError,
  deleting,
  open,
  sessionTitle,
  onConfirm,
  onOpenChange,
}: {
  deleteError: string | null
  deleting: boolean
  open: boolean
  sessionTitle: string
  onConfirm: () => void
  onOpenChange: (open: boolean) => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>정말로 삭제하시겠습니까?</AlertDialogTitle>
          <AlertDialogDescription>
            `{sessionTitle}` 대화와 저장된 메시지가 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
        <AlertDialogFooter>
          <Button variant="destructive" onClick={onConfirm} disabled={deleting}>
            {deleting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                삭제 중
              </>
            ) : (
              '삭제'
            )}
          </Button>
          <AlertDialogCancel disabled={deleting}>취소</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function getSessionTitle(session: RawAiSession | null) {
  if (session === null) {
    return '세션'
  }
  const metadata = toJsonObject(session.metadata)
  const uiMetadata = toJsonObject(metadata.ui)
  return getString(uiMetadata, 'sessionName') ?? getTrimmedString(session.title) ?? '세션'
}

function getMainAgentName(session: RawAiSession | null) {
  if (session === null) {
    return '팀장 에이전트'
  }
  const metadata = toJsonObject(session.metadata)
  const uiMetadata = toJsonObject(metadata.ui)
  return getString(uiMetadata, 'agentName') ?? '팀장 에이전트'
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-3 py-1.5">
      <span className="text-muted-foreground/60 font-mono text-[10px] font-medium tracking-widest uppercase">
        {label}
      </span>
    </div>
  )
}

function getTrimmedString(value: unknown) {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined
}

// 옵티미스틱 업데이트용 — 서버 응답을 기다리지 않고 sessionsById를 즉시 패치한다.
function patchSessionInStore(sessionId: string, nextSession: RawAiSession) {
  useChatStore.setState((state) => ({
    sessionsById: { ...state.sessionsById, [sessionId]: nextSession },
  }))
}
