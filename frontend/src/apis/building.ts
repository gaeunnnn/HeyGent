import axiosInstance from './axiosInstance'

export interface BuildingMapping {
  floor: number
  sessionId: string
}

interface ApiEnvelope<T> {
  status: number
  message: string
  data: T
}

/**
 * 사용자의 건물 페이지 층 ↔ AI 세션 매핑 전체 목록을 조회한다.
 */
export const listBuildingMappings = async (): Promise<BuildingMapping[]> => {
  const { data } = await axiosInstance.get<ApiEnvelope<BuildingMapping[]>>(
    '/api/v1/building/mappings',
  )
  return data.data
}

/**
 * 특정 층에 AI 세션을 매핑한다 (이미 있으면 갱신).
 */
export const assignBuildingFloor = async (
  floor: number,
  sessionId: string,
): Promise<BuildingMapping> => {
  const { data } = await axiosInstance.put<ApiEnvelope<BuildingMapping>>(
    `/api/v1/building/mappings/${floor}`,
    { sessionId },
  )
  return data.data
}

/**
 * 특정 층의 매핑을 해제한다.
 */
export const clearBuildingFloor = async (floor: number): Promise<void> => {
  await axiosInstance.delete(`/api/v1/building/mappings/${floor}`)
}
