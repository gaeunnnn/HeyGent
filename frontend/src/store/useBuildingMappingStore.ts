import { create } from 'zustand'
import {
  assignBuildingFloor,
  clearBuildingFloor,
  listBuildingMappings,
  type BuildingMapping,
} from '@/apis/building'

interface BuildingMappingState {
  /** floor → sessionId 매핑. 비어있는 층은 키 자체가 없다. */
  mappingsByFloor: Record<number, string>
  loading: boolean
  loaded: boolean
  error: string | null
  inflight: Promise<BuildingMapping[]> | null

  /** 서버에서 최신 매핑을 받아온다. 이미 로드됐고 강제 새로고침이 아니면 캐시 사용. */
  fetchMappings: (force?: boolean) => Promise<BuildingMapping[]>
  /** 특정 층에 세션을 매핑한다 (이미 있으면 갱신). */
  assignFloor: (floor: number, sessionId: string) => Promise<void>
  /** 특정 층 매핑을 해제한다. */
  clearFloor: (floor: number) => Promise<void>
  /** 특정 세션이 삭제되었을 때 해당 세션이 매핑된 모든 층을 로컬에서도 비운다 (서버는 이미 처리됐다고 가정). */
  removeMappingsForSession: (sessionId: string) => void
}

function toMapByFloor(mappings: BuildingMapping[]): Record<number, string> {
  const result: Record<number, string> = {}
  for (const mapping of mappings) {
    result[mapping.floor] = mapping.sessionId
  }
  return result
}

export const useBuildingMappingStore = create<BuildingMappingState>((set, get) => ({
  mappingsByFloor: {},
  loading: false,
  loaded: false,
  error: null,
  inflight: null,

  fetchMappings: async (force = false) => {
    const state = get()
    if (!force && state.loaded && !state.inflight) {
      // 캐시 사용 — 변환된 형태가 아니라 원본을 다시 만들어 반환
      const cached: BuildingMapping[] = Object.entries(state.mappingsByFloor).map(
        ([floor, sessionId]) => ({ floor: Number(floor), sessionId }),
      )
      return cached
    }
    if (state.inflight) return state.inflight

    set({ loading: true, error: null })
    const promise = listBuildingMappings()
      .then((mappings) => {
        set({
          mappingsByFloor: toMapByFloor(mappings),
          loading: false,
          loaded: true,
          error: null,
          inflight: null,
        })
        return mappings
      })
      .catch((error) => {
        set({
          loading: false,
          error: error instanceof Error ? error.message : '건물 매핑을 불러오지 못했습니다.',
          inflight: null,
        })
        throw error
      })
    set({ inflight: promise })
    return promise
  },

  assignFloor: async (floor, sessionId) => {
    const result = await assignBuildingFloor(floor, sessionId)
    set((state) => ({
      mappingsByFloor: {
        ...state.mappingsByFloor,
        [result.floor]: result.sessionId,
      },
    }))
  },

  clearFloor: async (floor) => {
    await clearBuildingFloor(floor)
    set((state) => {
      const next = { ...state.mappingsByFloor }
      delete next[floor]
      return { mappingsByFloor: next }
    })
  },

  removeMappingsForSession: (sessionId) => {
    set((state) => {
      const next: Record<number, string> = {}
      let removed = false
      for (const [floor, currentSessionId] of Object.entries(state.mappingsByFloor)) {
        if (currentSessionId === sessionId) {
          removed = true
          continue
        }
        next[Number(floor)] = currentSessionId
      }
      return removed ? { mappingsByFloor: next } : {}
    })
  },
}))
