import aiAxiosInstance from './aiAxiosInstance'

export type WorkflowTemplateNode = {
  slotKey: string
  title: string
  description: string
  assigneeAgentId: string | null
  templateKey: string | null
  positionX: number
  positionY: number
}

export type WorkflowTemplateEdge = {
  sourceSlotKey: string
  targetSlotKey: string
}

export type WorkflowTemplateGraph = {
  nodes: WorkflowTemplateNode[]
  edges: WorkflowTemplateEdge[]
}

export type WorkflowTemplate = {
  templateId: string
  ownerKey: string
  sessionId: string | null
  name: string
  description: string
  graph: WorkflowTemplateGraph
  createdAt: string | null
  updatedAt: string | null
}

export type WorkflowTemplateListResponse = {
  items: WorkflowTemplate[]
  totalCount: number
}

export type WorkflowTemplateInstantiateChild = {
  slotKey: string
  workId: string
  identifier: string
  title: string
  assigneeAgentId: string | null
}

export type WorkflowTemplateInstantiateResponse = {
  rootWorkId: string
  childWorkIds: string[]
  childrenBySlotKey: Record<string, string>
  children: WorkflowTemplateInstantiateChild[]
}

function basePath(sessionId: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}/workflow-templates`
}

export async function listWorkflowTemplates(
  sessionId: string,
): Promise<WorkflowTemplateListResponse> {
  const { data } = await aiAxiosInstance.get<WorkflowTemplateListResponse>(basePath(sessionId))
  return data
}

export async function getWorkflowTemplate(
  sessionId: string,
  templateId: string,
): Promise<WorkflowTemplate> {
  const { data } = await aiAxiosInstance.get<WorkflowTemplate>(
    `${basePath(sessionId)}/${encodeURIComponent(templateId)}`,
  )
  return data
}

export async function createWorkflowTemplate(
  sessionId: string,
  payload: {
    name: string
    description?: string
    graph: WorkflowTemplateGraph
  },
): Promise<WorkflowTemplate> {
  const { data } = await aiAxiosInstance.post<WorkflowTemplate>(basePath(sessionId), {
    name: payload.name,
    description: payload.description ?? '',
    graph: payload.graph,
  })
  return data
}

export async function updateWorkflowTemplate(
  sessionId: string,
  templateId: string,
  payload: { name?: string; description?: string; graph?: WorkflowTemplateGraph },
): Promise<WorkflowTemplate> {
  const { data } = await aiAxiosInstance.put<WorkflowTemplate>(
    `${basePath(sessionId)}/${encodeURIComponent(templateId)}`,
    payload,
  )
  return data
}

export async function deleteWorkflowTemplate(sessionId: string, templateId: string): Promise<void> {
  await aiAxiosInstance.delete(`${basePath(sessionId)}/${encodeURIComponent(templateId)}`)
}

export async function instantiateWorkflowTemplate(
  sessionId: string,
  templateId: string,
): Promise<WorkflowTemplateInstantiateResponse> {
  const { data } = await aiAxiosInstance.post<WorkflowTemplateInstantiateResponse>(
    `${basePath(sessionId)}/${encodeURIComponent(templateId)}/instantiate`,
    {},
  )
  return data
}
