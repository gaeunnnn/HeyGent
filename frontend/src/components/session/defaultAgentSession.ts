import type { CustomAgentConfig } from './NewSessionModal'

// 메인(팀장) 에이전트의 고정 프로필 이미지. 더 이상 여러 옵션을 좌우 화살표로 바꿀 수 없으며
// 모든 화면에서 동일한 이미지를 사용한다.
export const CEO_PROFILE_IMAGE_SRC = '/assets/agents/ceo/ceo_profile_img.png'

export const CEO_IMAGE_OPTIONS = [
  { id: 'profile', label: '프로필', src: CEO_PROFILE_IMAGE_SRC },
] as const

export function defaultAgentSessionConfig(): CustomAgentConfig {
  return {
    seedDefaultAgents: true,
    agentName: '팀장 에이전트',
    persona: '',
    callName: '팀장 에이전트',
    capabilities: '',
    profileImage: CEO_IMAGE_OPTIONS[0].src,
    model: 'gpt-5.4',
    delegationPolicy: { canDelegate: true },
    instructionsEntryFile: 'AGENTS.md',
    instructionsMode: 'managed',
    instructionsRootPath: '',
    instructionsFiles: {},
  }
}
