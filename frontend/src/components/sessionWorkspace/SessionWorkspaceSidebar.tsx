import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { SessionWorkspaceMenu } from './SessionWorkspaceMenu'
import { WorkflowRoutineRunner } from './work/board'
import {
  getCurrentWorkspaceSessionId,
  getWorkspacePanelFromPath,
  getWorkspacePanelPath,
} from './sessionWorkspaceUtils'
import type { WorkspaceNavId } from './sessionWorkspaceTypes'
import { useAuthStore } from '@/store/useAuthStore'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useUIStore } from '@/store/useUIStore'
import { agentProfilesToPanelItems } from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { useBuildingMappingStore } from '@/store/useBuildingMappingStore'
import { pickTopSession } from '@/components/layout/sessionListUtils'

export function SessionWorkspaceSidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const sessionWorkspaceCollapsed = useUIStore((state) => state.sessionWorkspaceCollapsed)
  const setSidebarCollapsed = useUIStore((state) => state.setSidebarCollapsed)
  const setSessionWorkspaceCollapsed = useUIStore((state) => state.setSessionWorkspaceCollapsed)
  const setSelectedSessionId = useSessionStore((state) => state.setSelectedSessionId)
  const setAgentPanelsForSession = useSessionStore((state) => state.setAgentPanelsForSession)
  const pinnedSessionIds = useSessionStore((state) => state.pinnedSessionIds)
  const sessionsById = useChatStore((state) => state.sessionsById)
  const deleteSession = useChatStore((state) => state.deleteSession)
  const accessToken = useAuthStore((state) => state.accessToken)
  const sessionId = getCurrentWorkspaceSessionId(location.pathname)
  const activePanel = getWorkspacePanelFromPath(location.pathname)
  const session = sessionId === null ? null : (sessionsById[sessionId] ?? null)
  const currentRoute = location.pathname.startsWith('/agent-status/') ? 'visualization' : 'chat'
  const searchParams = new URLSearchParams(location.search)
  const activeSubAgentId = searchParams.get('agent')

  useEffect(() => {
    if (sessionId === null || accessToken === null) return
    if (sessionId.startsWith('pending_session_')) return

    let cancelled = false
    void useAgentCacheStore
      .getState()
      .fetchSessionAgents(sessionId)
      .then((profiles) => {
        if (cancelled) return
        setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
      })
      .catch(() => {
        // 세션 확정 전 pending 경로에서는 서버 세션이 아직 없을 수 있다.
      })

    return () => {
      cancelled = true
    }
  }, [accessToken, sessionId, setAgentPanelsForSession])

  if (sessionId === null) {
    return null
  }

  const handleSelectPanel = (panelId: WorkspaceNavId) => {
    if (panelId === 'chat') {
      setSelectedSessionId(sessionId)
      setSidebarCollapsed(true)
      navigate(`/session/${sessionId}`)
      return
    }

    setSelectedSessionId(sessionId)
    navigate(getWorkspacePanelPath(sessionId, panelId))
  }

  const handleCreateSubAgent = () => {
    setSelectedSessionId(sessionId)
    navigate(`${getWorkspacePanelPath(sessionId, 'subAgents')}?create=1`)
  }

  const handleOpenSubAgent = (agentPanelId: string) => {
    setSelectedSessionId(sessionId)
    navigate(
      `${getWorkspacePanelPath(sessionId, 'subAgents')}?agent=${encodeURIComponent(agentPanelId)}`,
    )
  }

  const handleDeleteSession = async () => {
    // 세션이 건물 어느 층에 매핑돼 있으면 좀비 카드가 남지 않도록 함께 정리한다.
    // 세션 자체는 soft delete(deleted_at 박음) 이지만 매핑은 backend(Spring) DB 라
    // 자동 cascade 가 안 걸려서 사용자 화면엔 사라진 세션의 카드가 그대로 남는다.
    const mappingsByFloor = useBuildingMappingStore.getState().mappingsByFloor
    const clearFloor = useBuildingMappingStore.getState().clearFloor
    for (const [floorStr, mappedSessionId] of Object.entries(mappingsByFloor)) {
      if (mappedSessionId === sessionId) {
        const floor = Number(floorStr)
        if (Number.isFinite(floor)) {
          void clearFloor(floor).catch(() => undefined)
        }
      }
    }
    await deleteSession(sessionId)
    const nextSession = pickTopSession(sessionsById, pinnedSessionIds, sessionId ?? undefined)
    if (nextSession !== null) {
      setSelectedSessionId(nextSession.session_id)
      navigate(`/session/${nextSession.session_id}`, { replace: true })
    } else {
      setSelectedSessionId(null)
      navigate('/', { replace: true })
    }
  }

  return (
    <>
      <WorkflowRoutineRunner sessionId={sessionId} />
      <SessionWorkspaceMenu
        key={sessionId}
        activePanel={activePanel}
        collapsed={sessionWorkspaceCollapsed}
        currentRoute={currentRoute}
        session={session}
        sessionId={sessionId}
        activeSubAgentId={activeSubAgentId}
        onCollapsedChange={setSessionWorkspaceCollapsed}
        onCreateSubAgent={handleCreateSubAgent}
        onDeleteSession={handleDeleteSession}
        onOpenSubAgent={handleOpenSubAgent}
        onSelectPanel={handleSelectPanel}
      />
    </>
  )
}
