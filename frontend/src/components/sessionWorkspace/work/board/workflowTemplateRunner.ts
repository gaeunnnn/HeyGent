import {
  instantiateWorkflowTemplate,
  type WorkflowTemplate,
  type WorkflowTemplateInstantiateResponse,
} from '@/apis/workflowTemplates'
import type { WorkflowRunInputPayload } from '@/utils/workflowRunPayload'
import { buildWorkflowRunInputPayload, buildWorkflowRunTrigger } from '@/utils/workflowRunPayload'
import type { BoardAssignee } from './issueBoardPanelTypes'

type SendChatMessage = (input: {
  content: string
  inputPayload: WorkflowRunInputPayload
  sessionId: string
}) => Promise<unknown>

export type WorkflowTemplateRunResult = {
  chatError: unknown | null
  chatSent: boolean
  execution: WorkflowTemplateInstantiateResponse
}

export async function runWorkflowTemplate(input: {
  assignees: BoardAssignee[]
  sendChatMessage: SendChatMessage
  sessionId: string
  template: WorkflowTemplate
}): Promise<WorkflowTemplateRunResult> {
  const execution = await instantiateWorkflowTemplate(input.sessionId, input.template.templateId)
  const children = execution.children.map((child) => {
    const templateNode = input.template.graph.nodes.find((node) => node.slotKey === child.slotKey)
    return {
      slotKey: child.slotKey,
      workId: child.workId,
      identifier: child.identifier,
      title: child.title,
      description: templateNode?.description ?? child.title,
      assigneeAgentId: child.assigneeAgentId,
      assigneeName:
        input.assignees.find((assignee) => assignee.id === child.assigneeAgentId)?.name ??
        '에이전트',
    }
  })
  const trigger = buildWorkflowRunTrigger({
    templateName: input.template.name,
    templateDescription: input.template.description,
    children,
    edges: input.template.graph.edges,
  })
  const inputPayload = buildWorkflowRunInputPayload({
    templateId: input.template.templateId,
    templateName: input.template.name,
    rootWorkId: execution.rootWorkId,
    childWorkIds: execution.childWorkIds,
    childrenBySlotKey: execution.childrenBySlotKey,
    children,
  })

  try {
    await input.sendChatMessage({ sessionId: input.sessionId, content: trigger, inputPayload })
    return { chatError: null, chatSent: true, execution }
  } catch (chatError) {
    return { chatError, chatSent: false, execution }
  }
}
