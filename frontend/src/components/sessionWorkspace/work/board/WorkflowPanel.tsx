import { useMemo } from 'react'
import { useSessionStore } from '@/store/useSessionStore'
import type { BoardAssignee } from './issueBoardPanelTypes'
import { WorkflowTemplateEditor } from './WorkflowTemplateEditor'
import { buildWorkflowAssignees } from './workflowAssignees'

const EMPTY_AGENT_PANELS: ReturnType<
  typeof useSessionStore.getState
>['agentPanelsBySessionId'][string] = []

export function WorkflowPanel({ sessionId }: { sessionId: string }) {
  const agentPanelsBySessionId = useSessionStore((state) => state.agentPanelsBySessionId)
  const assignees = useMemo<BoardAssignee[]>(() => {
    const agentPanels = agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS
    return buildWorkflowAssignees(agentPanels)
  }, [agentPanelsBySessionId, sessionId])

  return (
    <div className="bg-background flex h-full min-h-0 w-full flex-col">
      <WorkflowTemplateEditor assignees={assignees} sessionId={sessionId} />
    </div>
  )
}
