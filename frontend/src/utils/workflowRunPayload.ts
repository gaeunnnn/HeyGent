export type WorkflowRunChild = {
  slotKey: string
  workId: string
  identifier: string
  title: string
  description?: string | null
  assigneeAgentId?: string | null
  assigneeName?: string | null
}

export type WorkflowRunEdge = {
  sourceSlotKey: string
  targetSlotKey: string
}

export type WorkflowRunInputPayload = {
  workId: string
  workflowExecution: {
    mode: 'strict_reuse_children'
    templateId: string
    templateName: string
    rootWorkId: string
    childWorkIds: string[]
    childrenBySlotKey: Record<string, string>
    children: WorkflowRunChild[]
  }
}

export function buildWorkflowRunInputPayload(input: {
  templateId: string
  templateName: string
  rootWorkId: string
  childWorkIds: string[]
  childrenBySlotKey: Record<string, string>
  children: WorkflowRunChild[]
}): WorkflowRunInputPayload {
  return {
    workId: input.rootWorkId,
    workflowExecution: {
      mode: 'strict_reuse_children',
      templateId: input.templateId,
      templateName: input.templateName,
      rootWorkId: input.rootWorkId,
      childWorkIds: input.childWorkIds,
      childrenBySlotKey: input.childrenBySlotKey,
      children: input.children,
    },
  }
}

export function buildWorkflowRunTrigger(input: {
  templateName: string
  templateDescription: string
  children: WorkflowRunChild[]
  edges: WorkflowRunEdge[]
}): string {
  const childrenBySlotKey = new Map(input.children.map((child) => [child.slotKey, child]))
  const childList = input.children
    .map((child, index) => {
      const assignee = child.assigneeName?.trim() || child.assigneeAgentId || '에이전트'
      const description = child.description?.trim() || child.title
      return [
        `${index + 1}. [${assignee}] ${child.title}`,
        `   - identifier: ${child.identifier}`,
        `   - childWorkId: ${child.workId}`,
        `   - workflowSlotKey: ${child.slotKey}`,
        `   - 지시: ${description}`,
      ].join('\n')
    })
    .join('\n')
    .trim()

  const orderList = input.edges
    .map((edge) => {
      const source = childrenBySlotKey.get(edge.sourceSlotKey)?.title ?? edge.sourceSlotKey
      const target = childrenBySlotKey.get(edge.targetSlotKey)?.title ?? edge.targetSlotKey
      return `- "${source}" 완료 후 → "${target}" 시작`
    })
    .join('\n')
    .trim()

  return [
    `[워크플로우 "${input.templateName}" 실행 시작]`,
    '',
    '## 팀장 지시사항',
    input.templateDescription || input.templateName,
    '',
    '## 이미 생성된 하위 작업',
    '새 작업 만들지 마세요. 아래 childWorkId 중 하나를 session_agent_task의 childWorkId로 선택해 실행하세요.',
    childList || '(없음)',
    orderList ? `\n## 실행 순서\n${orderList}` : '',
    '',
    '위 하위 작업들을 정의된 순서대로 진행하고, 모든 결과를 종합해 최종 결과를 보고하세요.',
  ]
    .filter(Boolean)
    .join('\n')
}
