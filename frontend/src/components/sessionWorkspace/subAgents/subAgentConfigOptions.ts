export const SUB_AGENT_ADAPTER_OPTIONS = [
  {
    id: 'openai_api_key',
    label: 'OpenAI',
    description: 'OpenAI API 키로 실행',
    recommended: true,
  },
  {
    id: 'gemini_api_key',
    label: 'Gemini',
    description: 'Gemini API 키로 실행',
    recommended: false,
  },
] as const

export type SubAgentAdapterType = (typeof SUB_AGENT_ADAPTER_OPTIONS)[number]['id']

export function normalizeSubAgentAdapterType(value: string | undefined): SubAgentAdapterType {
  if (value === 'openai') {
    return 'openai_api_key'
  }
  if (value === 'gemini') {
    return 'gemini_api_key'
  }
  if (SUB_AGENT_ADAPTER_OPTIONS.some((option) => option.id === value)) {
    return value as SubAgentAdapterType
  }
  return 'openai_api_key'
}

export function getDefaultModel(adapterType: SubAgentAdapterType = 'openai_api_key') {
  if (adapterType === 'gemini_api_key') {
    return 'gemini-2.5-pro'
  }
  return 'gpt-5.4'
}
