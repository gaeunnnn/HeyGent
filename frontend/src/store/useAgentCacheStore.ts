import { create } from 'zustand'
import {
  listSessionAgents,
  listAgentTemplates,
  listUserSkills,
  getSessionMainAgent,
  type AgentProfile,
  type AgentTemplate,
  type SkillCatalogItem,
} from '@/apis/agents'

type SessionAgentsCache = {
  data: AgentProfile[]
  inflight: Promise<AgentProfile[]> | null
}

type SessionMainAgentCache = {
  data: AgentProfile
  inflight: Promise<AgentProfile> | null
}

interface AgentCacheState {
  sessionAgentsBySessionId: Record<string, SessionAgentsCache>
  sessionMainAgentBySessionId: Record<string, SessionMainAgentCache>
  userSkills: SkillCatalogItem[] | null
  userSkillsInflight: Promise<SkillCatalogItem[]> | null
  agentTemplates: AgentTemplate[] | null
  agentTemplatesInflight: Promise<AgentTemplate[]> | null

  fetchSessionAgents: (sessionId: string) => Promise<AgentProfile[]>
  fetchSessionMainAgent: (sessionId: string) => Promise<AgentProfile>
  fetchUserSkills: () => Promise<SkillCatalogItem[]>
  fetchAgentTemplates: () => Promise<AgentTemplate[]>

  invalidateSessionAgents: (sessionId: string) => void
  invalidateSessionMainAgent: (sessionId: string) => void
  invalidateUserSkills: () => void
  invalidateAgentTemplates: () => void
  invalidateAll: () => void
}

export const useAgentCacheStore = create<AgentCacheState>((set, get) => ({
  sessionAgentsBySessionId: {},
  sessionMainAgentBySessionId: {},
  userSkills: null,
  userSkillsInflight: null,
  agentTemplates: null,
  agentTemplatesInflight: null,

  fetchSessionAgents: async (sessionId) => {
    const existing = get().sessionAgentsBySessionId[sessionId]
    if (existing?.data && !existing.inflight) return existing.data
    if (existing?.inflight) return existing.inflight

    const promise = listSessionAgents(sessionId)
      .then((data) => {
        set((state) => ({
          sessionAgentsBySessionId: {
            ...state.sessionAgentsBySessionId,
            [sessionId]: { data, inflight: null },
          },
        }))
        return data
      })
      .catch((error) => {
        set((state) => {
          const next = { ...state.sessionAgentsBySessionId }
          if (next[sessionId]) {
            next[sessionId] = { ...next[sessionId], inflight: null }
          }
          return { sessionAgentsBySessionId: next }
        })
        throw error
      })

    set((state) => ({
      sessionAgentsBySessionId: {
        ...state.sessionAgentsBySessionId,
        [sessionId]: {
          data: existing?.data ?? [],
          inflight: promise,
        },
      },
    }))
    return promise
  },

  fetchSessionMainAgent: async (sessionId) => {
    const existing = get().sessionMainAgentBySessionId[sessionId]
    if (existing?.data && !existing.inflight) return existing.data
    if (existing?.inflight) return existing.inflight

    const promise = getSessionMainAgent(sessionId)
      .then((data) => {
        set((state) => ({
          sessionMainAgentBySessionId: {
            ...state.sessionMainAgentBySessionId,
            [sessionId]: { data, inflight: null },
          },
        }))
        return data
      })
      .catch((error) => {
        set((state) => {
          const next = { ...state.sessionMainAgentBySessionId }
          if (next[sessionId]) {
            next[sessionId] = { ...next[sessionId], inflight: null }
          }
          return { sessionMainAgentBySessionId: next }
        })
        throw error
      })

    if (existing?.data) {
      set((state) => ({
        sessionMainAgentBySessionId: {
          ...state.sessionMainAgentBySessionId,
          [sessionId]: { data: existing.data, inflight: promise },
        },
      }))
    } else {
      set((state) => ({
        sessionMainAgentBySessionId: {
          ...state.sessionMainAgentBySessionId,
          [sessionId]: { data: undefined as unknown as AgentProfile, inflight: promise },
        },
      }))
    }
    return promise
  },

  fetchUserSkills: async () => {
    const { userSkills, userSkillsInflight } = get()
    if (userSkills && !userSkillsInflight) return userSkills
    if (userSkillsInflight) return userSkillsInflight

    const promise = listUserSkills()
      .then((data) => {
        set({ userSkills: data, userSkillsInflight: null })
        return data
      })
      .catch((error) => {
        set({ userSkillsInflight: null })
        throw error
      })

    set({ userSkillsInflight: promise })
    return promise
  },

  fetchAgentTemplates: async () => {
    const { agentTemplates, agentTemplatesInflight } = get()
    if (agentTemplates && !agentTemplatesInflight) return agentTemplates
    if (agentTemplatesInflight) return agentTemplatesInflight

    const promise = listAgentTemplates()
      .then((data) => {
        set({ agentTemplates: data, agentTemplatesInflight: null })
        return data
      })
      .catch((error) => {
        set({ agentTemplatesInflight: null })
        throw error
      })

    set({ agentTemplatesInflight: promise })
    return promise
  },

  invalidateSessionAgents: (sessionId) => {
    set((state) => {
      const next = { ...state.sessionAgentsBySessionId }
      delete next[sessionId]
      return { sessionAgentsBySessionId: next }
    })
  },

  invalidateSessionMainAgent: (sessionId) => {
    set((state) => {
      const next = { ...state.sessionMainAgentBySessionId }
      delete next[sessionId]
      return { sessionMainAgentBySessionId: next }
    })
  },

  invalidateUserSkills: () => {
    set({ userSkills: null, userSkillsInflight: null })
  },

  invalidateAgentTemplates: () => {
    set({ agentTemplates: null, agentTemplatesInflight: null })
  },

  invalidateAll: () => {
    set({
      sessionAgentsBySessionId: {},
      sessionMainAgentBySessionId: {},
      userSkills: null,
      userSkillsInflight: null,
      agentTemplates: null,
      agentTemplatesInflight: null,
    })
  },
}))
