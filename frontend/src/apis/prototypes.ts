import aiAxiosInstance from './aiAxiosInstance'

export type PrototypeFileMap = Record<string, { code: string }>

export type PrototypeArtifact = {
  artifactId: string
  versionId: string
  sessionId: string
  title: string
  framework: 'react' | 'html' | string
  styling: 'css' | 'tailwind' | 'mixed' | string
  designPresetId?: string | null
  entryFile: string
  files: PrototypeFileMap
  versionNumber: number
  summary?: string
  createdAt?: string | null
  updatedAt?: string | null
}

export type ActivePrototypeArtifactResponse = {
  activeArtifactId: string | null
  activeArtifactVersionId: string | null
  artifact: PrototypeArtifact | null
}

export async function getActivePrototypeArtifact(sessionId: string) {
  const { data } = await aiAxiosInstance.get<ActivePrototypeArtifactResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/artifacts/active`,
  )
  return data
}
