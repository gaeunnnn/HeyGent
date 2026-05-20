import { useMemo } from 'react'
import { Bot, UserRound } from 'lucide-react'
import { useSessionStore } from '@/store/useSessionStore'
import {
  agentProfilesToPanelItems,
  createDefaultSessionAgents,
  createSessionAgentFromTemplate,
} from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import type { BoardAssignee } from './issueBoardPanelTypes'
import { WorkflowTemplateEditor } from './WorkflowTemplateEditor'

const MAIN_AGENT_ASSIGNEE: BoardAssignee = {
  id: 'CEO',
  name: '팀장 에이전트',
  icon: UserRound,
  imageUrl: '/assets/agents/ceo/ceo_profile_img.png',
}

const EMPTY_AGENT_PANELS: ReturnType<
  typeof useSessionStore.getState
>['agentPanelsBySessionId'][string] = []

export function WorkflowPanel({ sessionId }: { sessionId: string }) {
  const agentPanelsBySessionId = useSessionStore((state) => state.agentPanelsBySessionId)
  const setAgentPanelsForSession = useSessionStore((state) => state.setAgentPanelsForSession)

  const assignees = useMemo<BoardAssignee[]>(() => {
    const agentPanels = agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS
    return [
      MAIN_AGENT_ASSIGNEE,
      ...agentPanels.map((panel) => ({
        id: panel.id,
        name: panel.agent.name,
        icon: Bot,
        templateKey: panel.agent.templateKey,
        imageUrl: panel.agent.profileImage ?? null,
      })),
    ]
  }, [agentPanelsBySessionId, sessionId])

  const ensureDefaultFlowAgents = async (): Promise<BoardAssignee[]> => {
    await createDefaultSessionAgents(sessionId)
    // 기본 에이전트들이 새로 생성됐으므로 캐시 무효화 후 fresh fetch.
    useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
    const profiles = await useAgentCacheStore.getState().fetchSessionAgents(sessionId)
    const panels = agentProfilesToPanelItems(profiles)
    setAgentPanelsForSession(sessionId, panels)
    return [
      MAIN_AGENT_ASSIGNEE,
      ...panels.map((panel) => ({
        id: panel.id,
        name: panel.agent.name,
        icon: Bot,
        templateKey: panel.agent.templateKey,
        imageUrl: panel.agent.profileImage ?? null,
      })),
    ]
  }

  const ensureProvidedFlowAgent = async (templateKey: string): Promise<BoardAssignee[]> => {
    await createSessionAgentFromTemplate(sessionId, templateKey)
    useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
    const profiles = await useAgentCacheStore.getState().fetchSessionAgents(sessionId)
    const panels = agentProfilesToPanelItems(profiles)
    setAgentPanelsForSession(sessionId, panels)
    return [
      MAIN_AGENT_ASSIGNEE,
      ...panels.map((panel) => ({
        id: panel.id,
        name: panel.agent.name,
        icon: Bot,
        templateKey: panel.agent.templateKey,
        imageUrl: panel.agent.profileImage ?? null,
      })),
    ]
  }

  return (
    <div className="bg-background flex h-full min-h-0 w-full flex-col">
      <WorkflowTemplateEditor
        assignees={assignees}
        sessionId={sessionId}
        onEnsureDefaultAgents={ensureDefaultFlowAgents}
        onEnsureProvidedAgent={ensureProvidedFlowAgent}
      />
    </div>
  )
}
