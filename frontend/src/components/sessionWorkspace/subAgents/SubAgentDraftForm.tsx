import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Shield } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { HelpHint } from '@/components/ui/help-hint'
import {
  AgentAdapterTypeDropdown,
  AgentModelDropdown,
  AgentSectionCard,
} from '@/components/sessionWorkspace/AgentDetailPanels'
import { useChatStore } from '@/store/useChatStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import type { Agent } from '@/types/agent'
import {
  getModelFamilies,
  getModelOptions,
  groupModels,
  inferModelFamily,
} from '../sessionWorkspaceUtils'
import {
  SUB_AGENT_ADAPTER_OPTIONS,
  getDefaultModel,
  normalizeSubAgentAdapterType,
  type SubAgentAdapterType,
} from './subAgentConfigOptions'
import {
  defaultSubAgentIcon,
  getSubAgentImageBySpriteId,
  normalizeSubAgentSkillIds,
  normalizeSubAgentSpriteId,
  SUB_AGENT_PROFILE_IMAGE_OPTIONS,
  type SubAgentSpriteId,
} from './subAgentOptions'

const ROLE_OPTIONS = [
  { id: 'general', label: 'General' },
  { id: 'research', label: 'Research' },
  { id: 'engineering', label: 'Engineering' },
  { id: 'qa', label: 'QA' },
] as const

export function SubAgentDraftForm({
  initialAgent,
  initialAdapterType,
  onCancel,
  onSave,
  reservedNames,
}: {
  initialAgent?: Agent
  initialAdapterType?: SubAgentAdapterType
  onCancel: () => void
  onSave: (agent: Agent) => void
  reservedNames: string[]
}) {
  const [nameDraft, setNameDraft] = useState(initialAgent?.name ?? '')
  const [titleDraft, setTitleDraft] = useState(initialAgent?.title ?? initialAgent?.role ?? '')
  const [roleDraft, setRoleDraft] = useState(initialAgent?.role ?? 'general')
  const [descriptionDraft, setDescriptionDraft] = useState(initialAgent?.description ?? '')
  const initialNormalizedAdapterType = normalizeSubAgentAdapterType(
    initialAgent?.adapterType ?? initialAdapterType,
  )
  const [adapterType, setAdapterType] = useState<SubAgentAdapterType>(initialNormalizedAdapterType)
  const [commandDraft] = useState(initialAgent?.command ?? '')
  const [modelDraft, setModelDraft] = useState(
    initialAgent?.model ?? getDefaultModel(initialNormalizedAdapterType),
  )
  const [extraArgsDraft] = useState(initialAgent?.extraArgs ?? '')
  const [modelOptionsLoading, setModelOptionsLoading] = useState(false)
  const [modelOptionsError, setModelOptionsError] = useState<string | null>(null)
  const [modelOptions, setModelOptions] = useState(getModelOptions(undefined))
  const [spriteId, setSpriteId] = useState<SubAgentSpriteId>(
    normalizeSubAgentSpriteId(initialAgent?.spriteId),
  )
  const [roleOpen, setRoleOpen] = useState(false)
  const fetchModelOptions = useChatStore((state) => state.fetchModelOptions)
  const authenticatedReady = useAiRealtimeStore((state) => state.authenticatedReady)
  const profileImage = getSubAgentImageBySpriteId(spriteId).src
  const providerModelOptions = useMemo(
    () =>
      modelOptions.filter((model) => {
        const provider = model.provider?.toLowerCase()
        if (adapterType === 'openai_api_key') {
          return (
            provider === undefined || provider.includes('openai') || provider === 'openai_api_key'
          )
        }
        return provider === adapterType || model.id.toLowerCase().startsWith('gemini-')
      }),
    [adapterType, modelOptions],
  )
  const modelGroups = useMemo(() => groupModels(providerModelOptions), [providerModelOptions])
  const effectiveModelDraft = providerModelOptions.some((model) => model.id === modelDraft)
    ? modelDraft
    : (providerModelOptions[0]?.id ?? getDefaultModel(adapterType))
  const selectedModelOption = providerModelOptions.find((model) => model.id === effectiveModelDraft)
  const modelFamilies = getModelFamilies(modelGroups)
  const inferredSelectedFamily = inferModelFamily(
    effectiveModelDraft,
    selectedModelOption?.label,
    selectedModelOption?.provider,
  )
  const effectiveSelectedFamily = modelFamilies.some(
    (family) => family.id === inferredSelectedFamily,
  )
    ? inferredSelectedFamily
    : (modelFamilies[0]?.id ?? 'gpt')
  const visibleModels = modelGroups[effectiveSelectedFamily]
  const visibleModelOptions = visibleModels.map((model) => ({
    value: model.id,
    label: model.label,
    description: model.provider ?? effectiveSelectedFamily,
  }))
  const selectedSpriteIndex = Math.max(
    0,
    SUB_AGENT_PROFILE_IMAGE_OPTIONS.findIndex((option) => option.id === spriteId),
  )
  const selectedSkillIds = normalizeSubAgentSkillIds(initialAgent?.skills ?? [])
  const trimmedName = nameDraft.trim()
  const duplicateName = reservedNames.some(
    (name) => name.trim().toLowerCase() === trimmedName.toLowerCase(),
  )
  const canSave = trimmedName !== '' && !duplicateName

  useEffect(() => {
    if (!authenticatedReady) {
      return
    }

    let active = true

    void fetchModelOptions()
      .then((options) => {
        if (!active) return
        const providerModels =
          options.providers?.flatMap((provider) => provider.models) ?? options.models
        const nextModels = getModelOptions(providerModels)
        setModelOptions(nextModels)
        setModelOptionsLoading(false)
      })
      .catch((error) => {
        if (!active) return
        setModelOptionsError(
          error instanceof Error ? error.message : '모델 목록 조회에 실패했습니다.',
        )
        setModelOptionsLoading(false)
      })

    return () => {
      active = false
    }
  }, [authenticatedReady, fetchModelOptions])

  const handleSave = () => {
    if (!canSave) return
    onSave({
      name: trimmedName,
      description: descriptionDraft.trim(),
      instructions: initialAgent?.instructions ?? '',
      instructionsEntryFile: initialAgent?.instructionsEntryFile ?? 'AGENTS.md',
      instructionsFiles: initialAgent?.instructionsFiles ?? {},
      instructionsMode: initialAgent?.instructionsMode ?? 'managed',
      instructionsRootPath: initialAgent?.instructionsRootPath ?? '',
      icon: initialAgent?.icon ?? defaultSubAgentIcon(),
      accent: initialAgent?.accent ?? '#111827',
      title: titleDraft.trim(),
      role: roleDraft,
      adapterType,
      command: commandDraft.trim(),
      model: effectiveModelDraft.trim(),
      extraArgs: extraArgsDraft.trim(),
      profileImage,
      spriteId,
      reportsToAgentId: initialAgent?.reportsToAgentId ?? 'main',
      skills: selectedSkillIds,
    })
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.7fr)]">
        <div className="space-y-4">
          <AgentSectionCard title="프로필">
            <div className="grid gap-4 sm:grid-cols-[13rem_minmax(0,1fr)]">
              <div aria-label="프로필 이미지">
                <SubAgentImageStepper
                  profileImage={profileImage}
                  selectedSpriteIndex={selectedSpriteIndex}
                  onSpriteChange={setSpriteId}
                />
              </div>
              <div className="space-y-3">
                <Field label="이름">
                  <input
                    autoFocus
                    value={nameDraft}
                    onChange={(event) => setNameDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') handleSave()
                      if (event.key === 'Escape') onCancel()
                    }}
                    className={inputClass}
                    placeholder="에이전트 이름"
                  />
                  {duplicateName && (
                    <p className="text-destructive mt-1 text-xs">
                      같은 이름의 서브 에이전트가 이미 있습니다.
                    </p>
                  )}
                </Field>
                <Field
                  label="호칭"
                  hint={
                    <>
                      <p className="text-foreground font-medium">호칭</p>
                      <p>
                        대화에서 부르는 <span className="text-foreground">별명·직함</span>이에요.
                      </p>
                      <p>예) “디자이너님”, “마케팅 담당자”.</p>
                    </>
                  }
                >
                  <input
                    value={titleDraft}
                    onChange={(event) => setTitleDraft(event.target.value)}
                    className={inputClass}
                    placeholder="호칭 또는 역할"
                  />
                </Field>
              </div>
            </div>
          </AgentSectionCard>

          <AgentSectionCard title="역할과 능력">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="역할"
                hint={
                  <>
                    <p className="text-foreground font-medium">역할</p>
                    <p>
                      이 에이전트가 팀에서 맡는 <span className="text-foreground">자리</span>예요.
                    </p>
                    <p>예) 리서처, 디자이너처럼 담당 분야를 정해 줍니다.</p>
                  </>
                }
              >
                <Popover open={roleOpen} onOpenChange={setRoleOpen}>
                  <PopoverTrigger asChild>
                    <button className={`${inputClass} flex items-center justify-between gap-2`}>
                      <span className="inline-flex items-center gap-2">
                        <Shield className="text-muted-foreground h-3.5 w-3.5" />
                        {ROLE_OPTIONS.find((role) => role.id === roleDraft)?.label ?? roleDraft}
                      </span>
                      <ChevronDown className="text-muted-foreground h-3.5 w-3.5" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent className="w-36 p-1" align="start">
                    {ROLE_OPTIONS.map((role) => (
                      <button
                        key={role.id}
                        type="button"
                        className={`hover:bg-accent/50 flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs ${
                          role.id === roleDraft ? 'bg-accent' : ''
                        }`}
                        onClick={() => {
                          setRoleDraft(role.id)
                          setRoleOpen(false)
                        }}
                      >
                        {role.label}
                      </button>
                    ))}
                  </PopoverContent>
                </Popover>
              </Field>
              <Field
                label="상위 에이전트"
                hint={
                  <>
                    <p className="text-foreground font-medium">상위 에이전트</p>
                    <p>
                      이 에이전트에게 일을 시키는 <span className="text-foreground">상사</span>예요.
                    </p>
                    <p>
                      지금은 모두 <span className="text-foreground">팀장 에이전트</span>가 맡습니다.
                    </p>
                  </>
                }
              >
                <input
                  className={`${inputClass} opacity-70`}
                  value="팀장 에이전트"
                  disabled
                  readOnly
                />
              </Field>
            </div>
            <Field
              label="할 수 있는 일"
              hint={
                <>
                  <p className="text-foreground font-medium">할 수 있는 일</p>
                  <p>
                    이 에이전트의 <span className="text-foreground">담당 업무 설명</span>이에요.
                  </p>
                  <p>팀장이 누구에게 일을 맡길지 정할 때 참고합니다.</p>
                  <p>예) “회의록 요약, 다음 일정 정리”.</p>
                </>
              }
            >
              <textarea
                value={descriptionDraft}
                onChange={(event) => setDescriptionDraft(event.target.value)}
                rows={3}
                className={`${inputClass} min-h-[72px] resize-y leading-6`}
                placeholder="이 에이전트가 할 수 있는 일을 적어주세요."
              />
            </Field>
          </AgentSectionCard>
        </div>

        <div className="space-y-4">
          <AgentSectionCard title="모델">
            <Field label="공급자">
              <AgentAdapterTypeDropdown
                value={adapterType}
                options={SUB_AGENT_ADAPTER_OPTIONS.map((option) => ({
                  value: option.id,
                  label: option.label,
                  description: option.description,
                }))}
                onChange={(value) => setAdapterType(normalizeSubAgentAdapterType(value))}
              />
            </Field>
            <Field label="모델">
              {authenticatedReady && modelOptionsLoading && (
                <span className="text-muted-foreground mb-1 inline-flex items-center gap-1.5 text-xs">
                  조회 중
                </span>
              )}
              {authenticatedReady && modelOptionsError ? (
                <p className="text-destructive text-sm">{modelOptionsError}</p>
              ) : (
                <AgentModelDropdown
                  value={modelDraft}
                  options={visibleModelOptions}
                  onChange={(modelId) => {
                    setModelDraft(modelId)
                  }}
                  allowDefault
                  placeholder={getDefaultModel(adapterType)}
                />
              )}
            </Field>
          </AgentSectionCard>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-2">
        <Button type="button" size="sm" onClick={handleSave} disabled={!canSave}>
          {initialAgent ? '에이전트 저장' : '에이전트 만들기'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          취소
        </Button>
      </div>
    </div>
  )
}

const inputClass =
  'border-border placeholder:text-muted-foreground/40 focus-visible:ring-ring w-full rounded-md border bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2'

function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: ReactNode
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
        {label}
        {hint ? (
          <HelpHint label={`${label} 도움말`} iconClassName="h-3 w-3">
            {hint}
          </HelpHint>
        ) : null}
      </span>
      {children}
    </label>
  )
}

function SubAgentImageStepper({
  onSpriteChange,
  profileImage,
  selectedSpriteIndex,
}: {
  onSpriteChange: (spriteId: SubAgentSpriteId) => void
  profileImage: string
  selectedSpriteIndex: number
}) {
  return (
    <div
      className="flex min-h-36 w-full min-w-0 items-center justify-center gap-5 rounded-lg"
      aria-label="에이전트 이미지"
    >
      <button
        type="button"
        onClick={() => {
          const nextIndex =
            (selectedSpriteIndex - 1 + SUB_AGENT_PROFILE_IMAGE_OPTIONS.length) %
            SUB_AGENT_PROFILE_IMAGE_OPTIONS.length
          onSpriteChange(SUB_AGENT_PROFILE_IMAGE_OPTIONS[nextIndex].id)
        }}
        className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-10 w-10 shrink-0 items-center justify-center rounded transition-colors"
        aria-label="이전 에이전트 이미지"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => {
          const nextIndex = (selectedSpriteIndex + 1) % SUB_AGENT_PROFILE_IMAGE_OPTIONS.length
          onSpriteChange(SUB_AGENT_PROFILE_IMAGE_OPTIONS[nextIndex].id)
        }}
        className="bg-accent hover:bg-accent/80 flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-lg transition-colors"
        aria-label="에이전트 이미지 변경"
      >
        <img src={profileImage} alt="" className="h-24 w-24 object-contain" draggable={false} />
      </button>
      <button
        type="button"
        onClick={() => {
          const nextIndex = (selectedSpriteIndex + 1) % SUB_AGENT_PROFILE_IMAGE_OPTIONS.length
          onSpriteChange(SUB_AGENT_PROFILE_IMAGE_OPTIONS[nextIndex].id)
        }}
        className="text-muted-foreground hover:bg-accent/50 hover:text-foreground flex h-10 w-10 shrink-0 items-center justify-center rounded transition-colors"
        aria-label="다음 에이전트 이미지"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}
