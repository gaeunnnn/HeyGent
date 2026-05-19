import { Bot, Code2, FlaskConical, Search, ShieldCheck } from 'lucide-react'
import type { Agent } from '@/types/agent'
import { getDefaultModel, type SubAgentAdapterType } from './subAgentConfigOptions'
import {
  defaultSubAgentIcon,
  getSubAgentImageBySpriteId,
  SUB_AGENT_PROFILE_IMAGE_OPTIONS,
  type SubAgentSkillId,
  type SubAgentSpriteId,
} from './subAgentOptions'

export type SubAgentTemplateId = (typeof SUB_AGENT_TEMPLATES)[number]['id']

type SubAgentTemplate = {
  id: string
  name: string
  title: string
  role: string
  description: string
  adapterType: SubAgentAdapterType
  spriteId: SubAgentSpriteId
  skills: SubAgentSkillId[]
  icon: typeof Bot
}

export const SUB_AGENT_TEMPLATES = [
  {
    id: 'default-agent',
    name: '기본 에이전트',
    title: 'General',
    role: 'general',
    description: '세션 맥락을 바탕으로 조사, 정리, 실행 보조 작업을 맡습니다.',
    adapterType: 'openai_api_key',
    spriteId: 'agent01',
    skills: [],
    icon: Bot,
  },
  {
    id: 'research-agent',
    name: '조사 에이전트',
    title: 'Researcher',
    role: 'research',
    description: '시장, 문서, 웹 자료를 조사하고 근거 중심으로 요약합니다.',
    adapterType: 'openai_api_key',
    spriteId: 'agent02',
    skills: [],
    icon: Search,
  },
  {
    id: 'engineering-agent',
    name: '개발 에이전트',
    title: 'Engineer',
    role: 'engineering',
    description: '코드 읽기, 구현, 테스트 보강처럼 개발 작업을 맡습니다.',
    adapterType: 'openai_api_key',
    spriteId: 'agent03',
    skills: ['code'],
    icon: Code2,
  },
  {
    id: 'qa-agent',
    name: '검증 에이전트',
    title: 'QA',
    role: 'qa',
    description: '완료 조건, 예외 상황, 화면 동작을 점검하고 피드백을 남깁니다.',
    adapterType: 'openai_api_key',
    spriteId: 'agent04',
    skills: [],
    icon: ShieldCheck,
  },
  {
    id: 'analysis-agent',
    name: '분석 에이전트',
    title: 'Analyst',
    role: 'research',
    description: '데이터와 비교 관점을 정리해 의사결정에 필요한 요약을 만듭니다.',
    adapterType: 'openai_api_key',
    spriteId: 'agent05',
    skills: [],
    icon: FlaskConical,
  },
] as const satisfies readonly SubAgentTemplate[]

export function createSubAgentFromTemplate(
  templateId: SubAgentTemplateId,
  existingNames: string[],
): Agent {
  const template =
    SUB_AGENT_TEMPLATES.find((item) => item.id === templateId) ?? SUB_AGENT_TEMPLATES[0]
  const name = createUniqueAgentName(template.name, existingNames)
  const spriteId = resolveSpriteId(template.spriteId, existingNames.length)
  return {
    name,
    description: template.description,
    instructions: '',
    instructionsEntryFile: 'AGENTS.md',
    instructionsFiles: {},
    instructionsMode: 'managed',
    instructionsRootPath: '',
    icon: defaultSubAgentIcon(),
    accent: '#111827',
    title: template.title,
    role: template.role,
    adapterType: template.adapterType,
    command: '',
    model: getDefaultModel(),
    extraArgs: '',
    profileImage: getSubAgentImageBySpriteId(spriteId).src,
    spriteId,
    reportsToAgentId: 'main',
    skills: [...template.skills],
  }
}

function createUniqueAgentName(baseName: string, existingNames: string[]) {
  const existingNameSet = new Set(existingNames.map((name) => name.trim().toLowerCase()))
  if (!existingNameSet.has(baseName.trim().toLowerCase())) return baseName
  let index = 2
  while (existingNameSet.has(`${baseName} ${index}`.toLowerCase())) {
    index += 1
  }
  return `${baseName} ${index}`
}

function resolveSpriteId(preferred: SubAgentSpriteId, seed: number): SubAgentSpriteId {
  if (SUB_AGENT_PROFILE_IMAGE_OPTIONS.some((option) => option.id === preferred)) return preferred
  return SUB_AGENT_PROFILE_IMAGE_OPTIONS[seed % SUB_AGENT_PROFILE_IMAGE_OPTIONS.length].id
}
