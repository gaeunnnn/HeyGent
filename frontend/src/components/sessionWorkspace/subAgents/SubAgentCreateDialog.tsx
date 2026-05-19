import { useState } from 'react'
import { ArrowLeft, Bot, Settings2, Sparkles, Users, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { HelpHint } from '@/components/ui/help-hint'
import { cn } from '@/components/ui/utils'
import type { AgentTemplate } from '@/apis/agents'
import { SUB_AGENT_ADAPTER_OPTIONS, type SubAgentAdapterType } from './subAgentConfigOptions'

const ADAPTER_ICONS: Record<SubAgentAdapterType, LucideIcon> = {
  openai_api_key: Bot,
  gemini_api_key: Sparkles,
}

type CreateMode = 'ceo' | 'template' | 'manual'

const MODE_OPTIONS: Array<{
  id: CreateMode
  label: string
  description: string
  icon: LucideIcon
}> = [
  {
    id: 'ceo',
    label: '팀장 에이전트에게 요청',
    description: '대화 맥락과 필요한 역할을 잘 아는 팀장 에이전트가 대신 만들어 줍니다.',
    icon: Bot,
  },
  {
    id: 'template',
    label: '기본 제공 에이전트',
    description: '미리 만들어진 역할 중에서 골라 빠르게 추가합니다.',
    icon: Users,
  },
  {
    id: 'manual',
    label: '직접 세부 설정하기',
    description: '모델 공급자와 세부 설정을 직접 골라 만듭니다.',
    icon: Settings2,
  },
]

type Step = 'select' | 'detail'

export function SubAgentCreateDialog({
  onAskCeo,
  onOpenChange,
  onPickAdapter,
  onPickTemplate,
  open,
  templates,
}: {
  onAskCeo: () => void
  onOpenChange: (open: boolean) => void
  onPickAdapter: (adapterType: SubAgentAdapterType) => void
  onPickTemplate: (templateKey: string) => void
  open: boolean
  templates: AgentTemplate[]
}) {
  const [step, setStep] = useState<Step>('select')
  const [selectedMode, setSelectedMode] = useState<CreateMode>('ceo')
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null)

  const resetState = () => {
    setStep('select')
    setSelectedMode('ceo')
    setSelectedTemplateKey(null)
  }

  const closeDialog = () => {
    resetState()
    onOpenChange(false)
  }

  const goNext = () => {
    if (selectedMode === 'ceo') {
      onAskCeo()
      return
    }
    setStep('detail')
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) resetState()
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="w-[min(94vw,42rem)] gap-0 overflow-hidden p-0 sm:max-w-2xl"
      >
        <DialogTitle className="sr-only">새 에이전트 추가</DialogTitle>
        <DialogDescription className="sr-only">
          팀장 에이전트에게 생성을 요청하거나 직접 세부 설정으로 새 서브에이전트를 추가합니다.
        </DialogDescription>
        <div className="border-border flex items-center justify-between border-b px-4 py-2.5">
          <span className="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
            새 에이전트 추가
            <HelpHint label="서브 에이전트 도움말" iconClassName="h-3.5 w-3.5">
              <p className="text-foreground font-medium">서브 에이전트</p>
              <p>
                팀장 에이전트 밑에서 일을 나눠 맡는 <span className="text-foreground">팀원</span>
                이에요.
              </p>
              <p>예) 리서처는 자료 조사, 디자이너는 시안 작업.</p>
            </HelpHint>
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            className="text-muted-foreground"
            onClick={closeDialog}
            aria-label="닫기"
          >
            <span className="text-lg leading-none">&times;</span>
          </Button>
        </div>

        <div className="space-y-5 px-4 py-5">
          {step === 'select' ? (
            <>
              <p className="text-muted-foreground text-sm">
                어떤 방법으로 새 에이전트를 만들지 골라 주세요.
              </p>

              <div role="radiogroup" aria-label="에이전트 생성 방법" className="grid gap-2">
                {MODE_OPTIONS.map((option) => {
                  const Icon = option.icon
                  const selected = selectedMode === option.id
                  return (
                    <button
                      key={option.id}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setSelectedMode(option.id)}
                      className={cn(
                        'flex items-start gap-3 rounded-md border p-3 text-left transition-colors',
                        selected
                          ? 'border-foreground/60 bg-accent/40'
                          : 'border-border hover:bg-accent/30',
                      )}
                    >
                      <span
                        className={cn(
                          'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                          selected ? 'border-foreground' : 'border-muted-foreground/50',
                        )}
                      >
                        {selected && <span className="bg-foreground h-2 w-2 rounded-full" />}
                      </span>
                      <Icon className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
                      <span className="min-w-0 flex-1 space-y-0.5">
                        <span className="block text-sm font-medium">{option.label}</span>
                        <span className="text-muted-foreground block text-xs leading-5">
                          {option.description}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>

              <Button className="w-full" size="lg" onClick={goNext}>
                다음
              </Button>
            </>
          ) : selectedMode === 'template' ? (
            <>
              <div>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition-colors"
                  onClick={() => setStep('select')}
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  뒤로
                </button>
              </div>

              {templates.length === 0 ? (
                <div className="border-border text-muted-foreground rounded-md border px-3 py-6 text-center text-xs">
                  사용 가능한 기본 에이전트가 없습니다.
                </div>
              ) : (
                <div className="grid max-h-[55vh] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                  {templates.map((template) => {
                    const selected = selectedTemplateKey === template.templateKey
                    return (
                      <button
                        key={template.templateKey}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => setSelectedTemplateKey(template.templateKey)}
                        className={cn(
                          'flex items-start gap-3 rounded-md border p-3 text-left transition-colors',
                          selected
                            ? 'border-foreground/60 bg-accent/40'
                            : 'border-border hover:bg-accent/30',
                        )}
                      >
                        <span className="bg-muted/70 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
                          <Bot className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium break-keep">
                            {template.displayName}
                          </span>
                          <span className="text-muted-foreground mt-0.5 line-clamp-3 block text-xs leading-5 break-keep">
                            {template.description}
                          </span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}

              <Button
                className="w-full"
                size="lg"
                disabled={!selectedTemplateKey}
                onClick={() => {
                  if (selectedTemplateKey) onPickTemplate(selectedTemplateKey)
                }}
              >
                에이전트 생성
              </Button>
            </>
          ) : (
            <>
              <div className="space-y-2">
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition-colors"
                  onClick={() => setStep('select')}
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  뒤로
                </button>
                <p className="text-muted-foreground text-sm">
                  사용할 모델 공급자를 고르고 세부 설정을 시작합니다.
                </p>
              </div>

              <div className="grid gap-2">
                {SUB_AGENT_ADAPTER_OPTIONS.map((option) => {
                  const Icon = ADAPTER_ICONS[option.id]
                  const comingSoon = false
                  const recommended = option.recommended
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={cn(
                        'border-border hover:bg-accent/50 relative flex items-center justify-center gap-2 rounded-md border p-3 text-xs transition-colors',
                        comingSoon && 'cursor-not-allowed opacity-40',
                      )}
                      disabled={comingSoon}
                      title={comingSoon ? '준비 중' : undefined}
                      onClick={() => {
                        if (comingSoon) return
                        onPickAdapter(option.id)
                      }}
                    >
                      {recommended && (
                        <span className="absolute -top-1.5 right-1.5 rounded-full bg-green-500 px-1.5 py-0.5 text-[9px] leading-none font-semibold text-white">
                          추천
                        </span>
                      )}
                      <Icon className="h-4 w-4" />
                      <span className="font-medium">{option.label}</span>
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
