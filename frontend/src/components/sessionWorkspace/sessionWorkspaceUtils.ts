import type { JsonObject } from '@/realtime/aiRealtimeTypes'
import type { AiModelOption } from '@/types/aiChat'
import type { WorkspacePanelId } from './sessionWorkspaceTypes'

export type ModelFamily = 'gpt' | 'other'
export type WorkspaceConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error'

export const MODEL_FAMILIES: Array<{ id: ModelFamily; label: string }> = [
  { id: 'gpt', label: 'GPT' },
  { id: 'other', label: '기타 모델' },
]

export function getCurrentWorkspaceSessionId(pathname: string) {
  const sessionRoutePrefixes = ['/session/', '/agent-status/']
  const prefix = sessionRoutePrefixes.find((value) => pathname.startsWith(value))
  if (prefix === undefined) {
    return null
  }

  const sessionId = pathname.slice(prefix.length).split('/')[0]
  return sessionId.trim() === '' ? null : sessionId
}

export function getWorkspacePanelFromPath(pathname: string): WorkspacePanelId | null {
  const match = pathname.match(/^\/session\/[^/]+\/workspace\/([^/]+)/)
  const panelSlug = match?.[1]
  if (panelSlug === 'settings' || panelSlug === 'model') {
    return 'ceo'
  }
  if (panelSlug === 'ceo') {
    return 'ceo'
  }
  if (panelSlug === 'sub-agents') {
    return 'subAgents'
  }
  if (panelSlug === 'visualization') {
    return 'visualization'
  }
  if (panelSlug === 'issue-board') {
    return 'issueBoard'
  }
  if (panelSlug === 'workflow') {
    return 'workflow'
  }
  if (panelSlug === 'routine') {
    return 'routine'
  }
  return null
}

export function getWorkspacePanelPath(sessionId: string, panelId: WorkspacePanelId) {
  if (panelId === 'ceo') {
    return `/session/${sessionId}/workspace/ceo`
  }
  if (panelId === 'subAgents') {
    return `/session/${sessionId}/workspace/sub-agents`
  }
  if (panelId === 'issueBoard') {
    return `/session/${sessionId}/workspace/issue-board`
  }
  if (panelId === 'workflow') {
    return `/session/${sessionId}/workspace/workflow`
  }
  if (panelId === 'routine') {
    return `/session/${sessionId}/workspace/routine`
  }
  return `/session/${sessionId}/workspace/visualization`
}

export function toJsonObject(value: unknown): JsonObject {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as JsonObject
  }
  return {}
}

export function getString(source: JsonObject, key: string) {
  const value = source[key]
  return typeof value === 'string' ? value : null
}

export function setOptionalUiString(target: JsonObject, key: string, value: string) {
  const trimmed = value.trim()
  if (trimmed === '') {
    delete target[key]
    return
  }
  target[key] = trimmed
}

export function getModelOptions(models: AiModelOption[] | undefined) {
  const seen = new Set<string>()
  return (models ?? []).filter((model) => {
    if (seen.has(model.id)) {
      return false
    }
    seen.add(model.id)
    return true
  })
}

export function groupModels(models: AiModelOption[]) {
  return {
    gpt: models.filter(
      (model) => inferModelFamily(model.id, model.label, model.provider) === 'gpt',
    ),
    other: models.filter(
      (model) => inferModelFamily(model.id, model.label, model.provider) === 'other',
    ),
  } satisfies Record<ModelFamily, AiModelOption[]>
}

export function getModelFamilies(modelGroups: Record<ModelFamily, AiModelOption[]>) {
  if (modelGroups.other.length === 0) {
    return MODEL_FAMILIES.filter((family) => family.id !== 'other')
  }
  return MODEL_FAMILIES
}

export function inferModelFamily(...values: Array<string | null | undefined>): ModelFamily {
  const text = values.filter(Boolean).join(' ').toLowerCase()
  if (text.includes('gpt') || text.includes('openai')) {
    return 'gpt'
  }
  return 'other'
}

export function shallowJsonEqual(first: JsonObject, second: JsonObject) {
  return JSON.stringify(first) === JSON.stringify(second)
}

export function getWorkspaceConnectionState(
  connectionStatus: string,
  authStatus: string,
  accessToken: string | null,
  realtimeError: string | null,
): WorkspaceConnectionState {
  if (realtimeError !== null || authStatus === 'failed') {
    return 'error'
  }
  if (accessToken === null || accessToken.trim() === '') {
    return 'error'
  }

  switch (connectionStatus) {
    case 'authenticated':
      return 'connected'
    case 'connecting':
    case 'open':
      return 'connecting'
    case 'reconnecting':
      return 'reconnecting'
    case 'error':
    case 'closed':
      return 'error'
    case 'idle':
    default:
      return 'idle'
  }
}

export function getWorkspaceConnectionText(state: WorkspaceConnectionState) {
  switch (state) {
    case 'connected':
      return '서버 연결됨'
    case 'connecting':
      return '서버 연결 중'
    case 'reconnecting':
      return '서버 연결 복구 중'
    case 'error':
      return '서버 연결 확인 필요'
    case 'idle':
    default:
      return '서버 대기 중'
  }
}
