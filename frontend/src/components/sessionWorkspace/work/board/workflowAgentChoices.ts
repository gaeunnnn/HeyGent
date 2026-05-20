import type { BoardAssignee } from './issueBoardPanelTypes'

export type WorkflowAgentChoice = {
  assigneeAgentId: string | null
  defaultTitle: string
  id: string
  imageUrl?: string | null
  name: string
  provided?: boolean
  templateKey?: string
}

export function buildWorkflowAgentChoices(assignees: BoardAssignee[]): WorkflowAgentChoice[] {
  return assignees
    .filter((assignee) => assignee.id !== 'CEO')
    .map((assignee) => ({
      id: assignee.id,
      name: assignee.name,
      defaultTitle: `${assignee.name} 작업`,
      assigneeAgentId: assignee.id,
      templateKey: assignee.templateKey,
      imageUrl: assignee.imageUrl ?? undefined,
    }))
}
