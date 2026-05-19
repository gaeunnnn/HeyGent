import { useEffect, useMemo, useState } from 'react'
import { Bot, Camera, Check, Loader2, Sparkles, X } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { useChatStore } from '@/store/useChatStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import type { JsonObject } from '@/realtime/aiRealtimeTypes'
import type {
  AiModelOption,
  AiSessionSettingsPatch,
  ModelOptionsResultPayload,
  RawAiSession,
} from '@/types/aiChat'

interface SessionSettingsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  session: RawAiSession | null
}

interface SessionSettingsFormProps {
  session: RawAiSession
  onOpenChange: (open: boolean) => void
}

type ModelFamily = 'gpt' | 'other'

const MODEL_FAMILIES: Array<{ id: ModelFamily; label: string }> = [
  { id: 'gpt', label: 'GPT' },
  { id: 'other', label: '기타' },
]

export function SessionSettingsModal({ open, onOpenChange, session }: SessionSettingsModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[88vh] w-[820px] max-w-[calc(100vw-24px)] gap-0 overflow-hidden p-0 [&>button]:hidden"
        aria-describedby="session-settings-description"
      >
        <DialogTitle className="sr-only">세션 설정</DialogTitle>
        <DialogDescription id="session-settings-description" className="sr-only">
          현재 세션 이름, 에이전트 표시 정보, 페르소나, 모델을 설정합니다.
        </DialogDescription>
        {open && session !== null && (
          <SessionSettingsForm
            key={session.session_id}
            session={session}
            onOpenChange={onOpenChange}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function SessionSettingsForm({ session, onOpenChange }: SessionSettingsFormProps) {
  const updateSession = useChatStore((state) => state.updateSession)
  const updateSessionSettings = useChatStore((state) => state.updateSessionSettings)
  const fetchModelOptions = useChatStore((state) => state.fetchModelOptions)
  const authenticatedReady = useAiRealtimeStore((state) => state.authenticatedReady)

  const metadata = useMemo(() => toJsonObject(session.metadata), [session.metadata])
  const uiMetadata = useMemo(() => toJsonObject(metadata.ui), [metadata])
  const settings = useMemo(() => toJsonObject(session.settings), [session.settings])
  const currentSessionName = getString(uiMetadata, 'sessionName') ?? ''
  const currentAgentName = getString(uiMetadata, 'agentName') ?? ''
  const currentCallName = getString(uiMetadata, 'callName') ?? ''
  const currentPersona =
    getString(settings, 'systemPrompt') ?? getString(settings, 'system_prompt') ?? ''
  const currentModel = getString(settings, 'model') ?? ''
  const [localModelOptions, setLocalModelOptions] = useState<ModelOptionsResultPayload | null>(null)
  const [modelOptionsLoading, setModelOptionsLoading] = useState(authenticatedReady)
  const [modelOptionsError, setModelOptionsError] = useState<string | null>(null)
  const models = useMemo(
    () => getModelOptions(localModelOptions?.models),
    [localModelOptions?.models],
  )
  const modelGroups = useMemo(() => groupModels(models), [models])
  const modelFamilies = useMemo(() => getModelFamilies(modelGroups), [modelGroups])

  const [sessionName, setSessionName] = useState(currentSessionName)
  const [agentName, setAgentName] = useState(currentAgentName)
  const [persona, setPersona] = useState(currentPersona)
  const [callName, setCallName] = useState(currentCallName)
  const [selectedFamily, setSelectedFamily] = useState<ModelFamily>(inferModelFamily(currentModel))
  const [selectedModel, setSelectedModel] = useState(currentModel)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const sessionId = session.session_id
  const selectedModelId = selectedModel
  const visibleModels = modelGroups[selectedFamily]

  useEffect(() => {
    if (!authenticatedReady) {
      return
    }

    let active = true

    void fetchModelOptions(sessionId)
      .then((options) => {
        if (!active) {
          return
        }
        setLocalModelOptions(options)
        setModelOptionsError(null)
        setModelOptionsLoading(false)
        if (currentModel === '' && typeof options.model === 'string' && options.model.trim()) {
          setSelectedModel(options.model)
          setSelectedFamily(inferModelFamily(options.model))
        }
      })
      .catch((error) => {
        if (!active) {
          return
        }
        setModelOptionsError(
          error instanceof Error ? error.message : '모델 목록 조회에 실패했습니다.',
        )
        setModelOptionsLoading(false)
      })

    return () => {
      active = false
    }
  }, [authenticatedReady, currentModel, fetchModelOptions, sessionId])

  const handleClose = () => {
    if (saving) {
      return
    }
    onOpenChange(false)
  }

  const handleSave = async () => {
    const nextSessionName = sessionName.trim()
    if (nextSessionName === '') {
      setSaveError('세션 이름을 입력하세요.')
      return
    }

    const nextUiMetadata: JsonObject = {
      ...uiMetadata,
      sessionName: nextSessionName,
    }
    setOptionalUiString(nextUiMetadata, 'agentName', agentName)
    setOptionalUiString(nextUiMetadata, 'callName', callName)

    const settingsPatch: AiSessionSettingsPatch = {}
    const nextPersona = persona.trim()
    if (nextPersona !== currentPersona) {
      settingsPatch.systemPrompt = nextPersona
    }
    if (selectedModelId !== '' && selectedModelId !== currentModel) {
      settingsPatch.model = selectedModelId
    }

    setSaving(true)
    setSaveError(null)

    try {
      const shouldUpdateMetadata = !shallowJsonEqual(uiMetadata, nextUiMetadata)
      if (shouldUpdateMetadata) {
        try {
          await updateSession({ sessionId, metadataPatch: { ui: nextUiMetadata } })
        } catch (error) {
          setSaveError(error instanceof Error ? error.message : '표시 정보 저장에 실패했습니다.')
          return
        }
      }
      if (Object.keys(settingsPatch).length > 0) {
        try {
          await updateSessionSettings({ sessionId, settingsPatch })
        } catch (error) {
          setSaveError(
            shouldUpdateMetadata
              ? '표시 정보는 저장됐지만 응답 설정 저장에 실패했습니다.'
              : error instanceof Error
                ? error.message
                : '응답 설정 저장에 실패했습니다.',
          )
          return
        }
      }
      onOpenChange(false)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '세션 설정 저장에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="border-border flex items-center justify-between border-b px-4 py-4 sm:px-6">
        <div>
          <h2 className="text-foreground text-base font-semibold">세션 설정</h2>
          <p className="text-muted-foreground mt-0.5 text-xs">이 대화에만 적용됩니다</p>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="세션 설정 닫기"
          className="text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 w-7 items-center justify-center rounded-md transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid max-h-[calc(88vh-164px)] min-h-0 grid-cols-1 overflow-y-auto md:max-h-[calc(88vh-133px)] md:grid-cols-[minmax(0,1fr)_260px] md:overflow-hidden">
        <div className="space-y-5 px-4 py-5 sm:px-6 md:overflow-y-auto">
          <div className="flex items-center gap-3 sm:gap-4">
            <div className="relative shrink-0">
              <div className="border-border flex h-14 w-14 overflow-hidden rounded-full border-2 sm:h-20 sm:w-20">
                <img
                  src="/assets/agents/ceo/ceo_profile_img.png"
                  alt="에이전트 프로필"
                  className="h-full w-full object-cover"
                />
              </div>
              <button
                type="button"
                disabled
                title="이미지 변경"
                className="bg-muted text-muted-foreground absolute right-0 bottom-0 flex h-7 w-7 items-center justify-center rounded-full shadow-sm"
              >
                <Camera className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="min-w-0 flex-1">
              <div className="bg-muted/40 text-muted-foreground mb-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs">
                <Bot className="h-3.5 w-3.5" />
                메인 에이전트
              </div>
              <label htmlFor="session-agent-name" className="sr-only">
                에이전트 이름
              </label>
              <input
                id="session-agent-name"
                type="text"
                value={agentName}
                onChange={(event) => setAgentName(event.target.value)}
                placeholder="에이전트 이름"
                className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border bg-white px-3 py-2 text-sm focus:ring-2 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="text-foreground mb-1.5 block text-xs font-medium">세션 이름</span>
              <input
                type="text"
                value={sessionName}
                onChange={(event) => setSessionName(event.target.value)}
                placeholder="예: 기획 회의, API 정리"
                className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border bg-white px-3 py-2 text-sm focus:ring-2 focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-foreground mb-1.5 block text-xs font-medium">
                어떻게 불러드릴까요?
              </span>
              <input
                type="text"
                value={callName}
                onChange={(event) => setCallName(event.target.value)}
                placeholder="예: 팀장님, 민수님"
                className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border bg-white px-3 py-2 text-sm focus:ring-2 focus:outline-none"
              />
            </label>
          </div>

          <label className="block">
            <span className="text-foreground mb-1.5 block text-xs font-medium">페르소나</span>
            <textarea
              value={persona}
              onChange={(event) => setPersona(event.target.value)}
              placeholder="예: 차분하고 논리적인 성격으로, 항상 데이터에 근거해 조언합니다."
              className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 h-36 w-full resize-none rounded-lg border bg-white px-3 py-2 text-sm leading-6 focus:ring-2 focus:outline-none sm:h-40"
            />
          </label>
        </div>

        <aside className="border-border bg-muted/15 flex min-h-0 flex-col border-t px-4 py-5 sm:px-6 md:border-t-0 md:border-l">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-foreground text-sm font-semibold">이 대화에서 사용할 모델</span>
            {authenticatedReady && modelOptionsLoading && (
              <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                불러오는 중
              </span>
            )}
          </div>

          <div
            className={`bg-muted grid gap-1 rounded-lg p-1 ${
              modelFamilies.length >= 3 ? 'grid-cols-3' : 'grid-cols-2'
            }`}
            role="group"
            aria-label="모델 계열"
          >
            {modelFamilies.map((family) => (
              <button
                key={family.id}
                type="button"
                onClick={() => setSelectedFamily(family.id)}
                aria-pressed={selectedFamily === family.id}
                className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  selectedFamily === family.id
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {family.label}
              </button>
            ))}
          </div>

          <div
            className="mt-4 min-h-0 space-y-2 md:overflow-y-auto"
            role="group"
            aria-label="모델 선택"
          >
            {authenticatedReady && modelOptionsError ? (
              <div className="border-border bg-background text-muted-foreground rounded-lg border p-3 text-xs">
                {modelOptionsError}
              </div>
            ) : authenticatedReady && visibleModels.length === 0 && !modelOptionsLoading ? (
              <div className="border-border bg-background text-muted-foreground rounded-lg border p-3 text-xs">
                선택 가능한 모델이 없습니다.
              </div>
            ) : (
              visibleModels.map((model) => (
                <button
                  key={`${model.provider ?? selectedFamily}:${model.id}`}
                  type="button"
                  onClick={() => setSelectedModel(model.id)}
                  aria-pressed={selectedModelId === model.id}
                  className={`border-border bg-background flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    selectedModelId === model.id
                      ? 'border-primary/40 bg-primary/3'
                      : 'hover:bg-muted/50'
                  }`}
                >
                  <span className="min-w-0">
                    <span className="text-foreground block truncate text-sm font-medium">
                      {model.label}
                    </span>
                    <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                      {model.provider ?? selectedFamily}
                    </span>
                  </span>
                  {selectedModelId === model.id && (
                    <Check className="text-primary h-4 w-4 shrink-0" />
                  )}
                </button>
              ))
            )}
          </div>
        </aside>
      </div>

      <div className="border-border flex flex-col gap-3 border-t px-4 py-3 sm:px-6 sm:py-4 md:flex-row md:items-center md:justify-between">
        <div className="min-h-4 min-w-0">
          {saveError && <p className="text-destructive truncate text-xs">{saveError}</p>}
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2 md:flex">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="bg-primary text-primary-foreground hover:bg-primary/90 flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            저장
          </button>
          <button
            type="button"
            onClick={handleClose}
            disabled={saving}
            className="bg-muted text-foreground hover:bg-muted/80 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50"
          >
            취소
          </button>
        </div>
      </div>
    </>
  )
}

function toJsonObject(value: unknown): JsonObject {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as JsonObject
  }
  return {}
}

function getString(source: JsonObject, key: string) {
  const value = source[key]
  return typeof value === 'string' ? value : null
}

function setOptionalUiString(target: JsonObject, key: string, value: string) {
  const trimmed = value.trim()
  if (trimmed === '') {
    delete target[key]
    return
  }
  target[key] = trimmed
}

function getModelOptions(models: AiModelOption[] | undefined) {
  const seen = new Set<string>()
  return (models ?? []).filter((model) => {
    if (seen.has(model.id)) {
      return false
    }
    seen.add(model.id)
    return true
  })
}

function groupModels(models: AiModelOption[]) {
  return {
    gpt: models.filter(
      (model) => inferModelFamily(model.id, model.label, model.provider) === 'gpt',
    ),
    other: models.filter(
      (model) => inferModelFamily(model.id, model.label, model.provider) === 'other',
    ),
  } satisfies Record<ModelFamily, AiModelOption[]>
}

function getModelFamilies(modelGroups: Record<ModelFamily, AiModelOption[]>) {
  if (modelGroups.other.length === 0) {
    return MODEL_FAMILIES.filter((family) => family.id !== 'other')
  }
  return MODEL_FAMILIES
}

function inferModelFamily(...values: Array<string | null | undefined>): ModelFamily {
  const text = values.filter(Boolean).join(' ').toLowerCase()
  if (text.includes('gpt') || text.includes('openai')) {
    return 'gpt'
  }
  return 'other'
}

function shallowJsonEqual(first: JsonObject, second: JsonObject) {
  return JSON.stringify(first) === JSON.stringify(second)
}
