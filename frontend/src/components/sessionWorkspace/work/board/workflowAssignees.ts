import { Bot, UserRound } from 'lucide-react'
import type { AgentPanelItem } from '@/store/useSessionStore'
import type { BoardAssignee } from './issueBoardPanelTypes'

export const MAIN_WORKFLOW_ASSIGNEE: BoardAssignee = {
  id: 'CEO',
  name: '팀장 에이전트',
  icon: UserRound,
  imageUrl: '/assets/agents/ceo/ceo_profile_img.png',
}

export function buildWorkflowAssignees(agentPanels: AgentPanelItem[]): BoardAssignee[] {
  return [
    MAIN_WORKFLOW_ASSIGNEE,
    ...agentPanels.map((panel) => ({
      id: panel.id,
      name: panel.agent.name,
      icon: Bot,
      templateKey: panel.agent.templateKey,
      imageUrl: panel.agent.profileImage ?? null,
    })),
  ]
}
