import { Bot } from 'lucide-react'
import aiAxiosInstance from './aiAxiosInstance'
import type { Agent } from '@/types/agent'
import type { AgentPanelItem } from '@/store/useSessionStore'

export type AgentInstructionDocument = {
  documentId?: string | null
  documentKey: string
  displayName: string
  contentFormat: string
  content: string
  version: number
}

export type AgentTemplate = {
  templateId: string
  templateKey: string
  templateVersion: number
  displayName: string
  name: string
  role: string
  title: string
  description: string
  adapterType: string
  model?: string | null
  profileImage?: string | null
  skills: string[]
  entryDocumentKey: string
  documents: AgentInstructionDocument[]
}

export type AgentProfile = {
  profileId: string
  sessionId?: string | null
  profileKey: string
  profileVersion: number
  agentType: string
  templateKey?: string | null
  name: string
  role: string
  title?: string | null
  description?: string | null
  adapterType?: string | null
  model?: string | null
  profileImage?: string | null
  visualKey?: string | null
  skills: string[]
  instructionBundleId?: string | null
  entryDocumentKey?: string | null
  configSnapshot: Record<string, unknown>
}

export type AgentInstructionBundle = {
  bundleId: string
  profileId: string
  mode: string
  entryDocumentKey: string
  documents: AgentInstructionDocument[]
}

export type SkillCatalogItem = {
  skillId: string
  name: string
  displayName: string
  description: string
  sourceType: string
  sourcePath?: string | null
  version: number
  enabled: boolean
  defaultEnabled: boolean
}

export type SkillCatalogDetail = SkillCatalogItem & {
  body: string
  files: string[]
  documents: SkillCatalogDocument[]
}

export type SkillCatalogDocument = {
  documentKey: string
  title: string
  content: string
  contentFormat: string
}

type SessionAgentInput = {
  name: string
  role: string
  title?: string
  description?: string
  adapterType?: string
  model?: string
  profileImage?: string
  skills?: string[]
  entryDocumentKey?: string
  instructionsFiles?: Record<string, string>
}

export async function listAgentTemplates(): Promise<AgentTemplate[]> {
  const { data } = await aiAxiosInstance.get<{ items: AgentTemplate[] }>('/agent-templates')
  return data.items
}

export async function listUserSkills(): Promise<SkillCatalogItem[]> {
  const { data } = await aiAxiosInstance.get<{ items: SkillCatalogItem[] }>('/skills')
  return data.items
}

export async function getUserSkillDetail(skillId: string): Promise<SkillCatalogDetail> {
  const { data } = await aiAxiosInstance.get<SkillCatalogDetail>(
    `/skills/${encodeURIComponent(skillId)}`,
  )
  return data
}

export async function updateUserSkillSetting(
  skillId: string,
  input: { enabled: boolean },
): Promise<SkillCatalogItem> {
  const { data } = await aiAxiosInstance.patch<SkillCatalogItem>(
    `/skills/${encodeURIComponent(skillId)}`,
    input,
  )
  return data
}

export async function listSessionAgents(sessionId: string): Promise<AgentProfile[]> {
  const { data } = await aiAxiosInstance.get<{ items: AgentProfile[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/agents`,
  )
  return data.items
}

export async function getSessionMainAgent(sessionId: string): Promise<AgentProfile> {
  const { data } = await aiAxiosInstance.get<AgentProfile>(
    `/sessions/${encodeURIComponent(sessionId)}/agents/main`,
  )
  return data
}

export async function createSessionAgent(
  sessionId: string,
  input: SessionAgentInput,
): Promise<AgentProfile> {
  const { data } = await aiAxiosInstance.post<AgentProfile>(
    `/sessions/${encodeURIComponent(sessionId)}/agents`,
    input,
  )
  return data
}

export async function updateSessionAgent(
  sessionId: string,
  profileId: string,
  input: Partial<SessionAgentInput>,
): Promise<AgentProfile> {
  const { data } = await aiAxiosInstance.patch<AgentProfile>(
    `/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(profileId)}`,
    input,
  )
  return data
}

export async function createDefaultSessionAgents(sessionId: string): Promise<AgentProfile[]> {
  const { data } = await aiAxiosInstance.post<{ items: AgentProfile[] }>(
    `/sessions/${encodeURIComponent(sessionId)}/agents/defaults`,
  )
  return data.items
}

export async function createSessionAgentFromTemplate(
  sessionId: string,
  templateKey: string,
): Promise<AgentProfile> {
  const { data } = await aiAxiosInstance.post<AgentProfile>(
    `/sessions/${encodeURIComponent(sessionId)}/agents/from-template`,
    { templateKey },
  )
  return data
}

export async function deleteSessionAgent(sessionId: string, profileId: string): Promise<void> {
  await aiAxiosInstance.delete(
    `/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(profileId)}`,
  )
}

export async function getAgentInstructionBundle(
  profileId: string,
): Promise<AgentInstructionBundle> {
  const { data } = await aiAxiosInstance.get<AgentInstructionBundle>(
    `/agent-profiles/${encodeURIComponent(profileId)}/instructions`,
  )
  return data
}

export async function saveAgentInstructionDocument(
  profileId: string,
  input: { documentKey: string; displayName: string; content: string },
): Promise<AgentInstructionDocument> {
  const { data } = await aiAxiosInstance.post<AgentInstructionDocument>(
    `/agent-profiles/${encodeURIComponent(profileId)}/instructions/documents`,
    input,
  )
  return data
}

export function agentProfilesToPanelItems(profiles: AgentProfile[]): AgentPanelItem[] {
  return profiles.map((profile) => ({
    id: profile.profileId,
    panelOpen: false,
    agent: agentProfileToAgent(profile),
  }))
}

export function agentProfileToAgent(profile: AgentProfile): Agent {
  const instructionsFiles = getInstructionsFiles(profile.configSnapshot)
  return {
    profileId: profile.profileId,
    templateKey: profile.templateKey ?? undefined,
    instructionBundleId: profile.instructionBundleId ?? undefined,
    name: profile.name,
    description: profile.description ?? '',
    instructions: instructionsFiles[profile.entryDocumentKey ?? 'AGENTS.md'] ?? '',
    instructionsEntryFile: profile.entryDocumentKey ?? 'AGENTS.md',
    instructionsFiles,
    instructionsMode: 'managed',
    instructionsRootPath: '',
    icon: Bot,
    accent: '#111827',
    title: profile.title ?? undefined,
    role: profile.role,
    adapterType: normalizeAgentAdapterType(profile.adapterType),
    command: '',
    model: profile.model ?? undefined,
    extraArgs: '',
    profileImage: profile.profileImage ?? undefined,
    spriteId: profile.visualKey ?? deriveSpriteId(profile.profileImage),
    reportsToAgentId: 'main',
    skills: profile.skills,
  }
}

// /assets/agents/agentXX/idle_front.png 또는 레거시 /assets/agents/sub/agentXX.png 형식에서 spriteId(agentXX)를 추출한다.
export function deriveSpriteId(profileImage: string | null | undefined): string | undefined {
  if (!profileImage) return undefined
  const newMatch = profileImage.match(/\/assets\/agents\/(agent\d{2})\/idle_front\.png/)
  if (newMatch) return newMatch[1]
  const legacyMatch = profileImage.match(/\/assets\/agents\/sub\/(agent\d{2})\.png/)
  return legacyMatch?.[1]
}

function normalizeAgentAdapterType(value: string | null | undefined) {
  if (value === undefined || value === null || value === '') {
    return undefined
  }
  if (value === 'openai') {
    return 'openai_api_key'
  }
  if (value === 'gemini') {
    return 'gemini_api_key'
  }
  if (value === 'openai_api_key' || value === 'gemini_api_key') {
    return value
  }
  return 'openai_api_key'
}

function getInstructionsFiles(configSnapshot: Record<string, unknown>): Record<string, string> {
  const documents = Array.isArray(configSnapshot.documents) ? configSnapshot.documents : []
  return Object.fromEntries(
    documents.flatMap((document) => {
      if (typeof document !== 'object' || document === null || Array.isArray(document)) return []
      const value = document as Record<string, unknown>
      const documentKey = typeof value.documentKey === 'string' ? value.documentKey : ''
      const content = typeof value.content === 'string' ? value.content : ''
      return documentKey ? [[documentKey, content] as const] : []
    }),
  )
}
