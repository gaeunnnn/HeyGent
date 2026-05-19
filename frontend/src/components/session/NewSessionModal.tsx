import { useState } from 'react'
import { X, Bot, Sparkles, SlidersHorizontal, ChevronLeft, ChevronRight } from 'lucide-react'
import { motion, AnimatePresence } from 'motion/react'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { HelpHint } from '@/components/ui/help-hint'
import {
  AgentAdapterTypeDropdown,
  AgentInstructionsBundlePanel,
  AgentModelDropdown,
  AgentSectionCard,
} from '@/components/sessionWorkspace/AgentDetailPanels'
import { CEO_IMAGE_OPTIONS, defaultAgentSessionConfig } from './defaultAgentSession'

export interface CustomAgentConfig {
  seedDefaultAgents?: boolean
  agentName: string
  persona: string
  callName: string
  capabilities: string
  profileImage: string | null
  model: string
  delegationPolicy: {
    canDelegate: boolean
    maxWorkerDepth?: number
  }
  instructionsEntryFile: string
  instructionsMode: 'managed' | 'external'
  instructionsRootPath: string
  instructionsFiles: Record<string, string>
}

interface NewSessionModalProps {
  error?: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (config?: CustomAgentConfig) => void
  submitting?: boolean
}

type ModalView = 'select' | 'customize'
type CustomizeStep = 'settings' | 'instructions'

export function NewSessionModal({
  error,
  open,
  onOpenChange,
  onConfirm,
  submitting = false,
}: NewSessionModalProps) {
  const [view, setView] = useState<ModalView>('select')
  const [customizeStep, setCustomizeStep] = useState<CustomizeStep>('settings')
  const [agentName, setAgentName] = useState('')
  const [persona, setPersona] = useState('')
  const [callName, setCallName] = useState('')
  const [profileImage, setProfileImage] = useState<string>(CEO_IMAGE_OPTIONS[0].src)
  const [instructionsEntryFile, setInstructionsEntryFile] = useState('AGENTS.md')
  const [instructionsMode, setInstructionsMode] = useState<'managed' | 'external'>('managed')
  const [instructionsRootPath, setInstructionsRootPath] = useState('')
  const [instructionsFiles, setInstructionsFiles] = useState<Record<string, string>>({})
  const [model, setModel] = useState('gpt-5.4')
  const [canDelegate, setCanDelegate] = useState(false)

  const handleClose = () => {
    onOpenChange(false)
    // 닫을 때 상태 초기화 (애니메이션 후)
    setTimeout(() => {
      setView('select')
      setCustomizeStep('settings')
      setAgentName('')
      setPersona('')
      setCallName('')
      setProfileImage(CEO_IMAGE_OPTIONS[0].src)
      setInstructionsEntryFile('AGENTS.md')
      setInstructionsMode('managed')
      setInstructionsRootPath('')
      setInstructionsFiles({})
      setModel('gpt-5.4')
      setCanDelegate(false)
    }, 200)
  }

  const handleCustomizeConfirm = () => {
    onConfirm({
      agentName,
      persona,
      callName,
      capabilities: '',
      profileImage,
      model,
      delegationPolicy: { canDelegate },
      instructionsEntryFile,
      instructionsMode,
      instructionsRootPath,
      instructionsFiles,
    })
    setTimeout(() => {
      setView('select')
      setCustomizeStep('settings')
      setAgentName('')
      setPersona('')
      setCallName('')
      setProfileImage(CEO_IMAGE_OPTIONS[0].src)
      setInstructionsEntryFile('AGENTS.md')
      setInstructionsMode('managed')
      setInstructionsRootPath('')
      setInstructionsFiles({})
      setModel('gpt-5.4')
      setCanDelegate(false)
    }, 200)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className="max-h-[calc(100vh-24px)] w-full max-w-lg gap-0 overflow-hidden p-0 [&>button]:hidden"
        aria-describedby="new-session-description"
      >
        <DialogTitle className="sr-only">새 대화 시작</DialogTitle>
        <DialogDescription id="new-session-description" className="sr-only">
          세션 유형을 선택하거나 에이전트를 커스터마이징합니다
        </DialogDescription>

        <AnimatePresence mode="wait">
          {view === 'select' ? (
            <motion.div
              key="select"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              transition={{ duration: 0.18 }}
            >
              {/* Header */}
              <div className="border-border flex items-center justify-between border-b px-6 py-4">
                <div>
                  <div className="flex items-center gap-1.5">
                    <h2 className="text-foreground text-base font-semibold">새 대화 시작</h2>
                    <HelpHint label="세션 도움말" iconClassName="h-3.5 w-3.5">
                      <p className="text-foreground font-medium">세션 (대화방)</p>
                      <p>
                        한 가지 주제로 진행하는 <span className="text-foreground">대화방</span>
                        이에요.
                      </p>
                      <p>주제별로 따로 만들면 기록이 섞이지 않습니다.</p>
                      <p>예) “3월 마케팅”, “신입 교육 자료”.</p>
                    </HelpHint>
                  </div>
                  <p className="text-muted-foreground mt-0.5 text-xs">대화 유형을 선택하세요</p>
                </div>
                <button
                  onClick={handleClose}
                  className="text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 w-7 items-center justify-center rounded-md transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Options */}
              <div className="space-y-3 p-6">
                {/* 기본 제공 에이전트 */}
                <button
                  onClick={() => onConfirm(defaultAgentSessionConfig())}
                  disabled={submitting}
                  className="hover:bg-muted/60 group flex w-full items-start gap-4 rounded-xl p-4 text-left transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50"
                >
                  <div className="bg-muted group-hover:bg-muted/80 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-colors">
                    <Bot className="text-foreground/70 h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <p className="text-foreground text-sm font-semibold">기본 제공 에이전트</p>
                      <HelpHint label="기본 제공 에이전트 도움말" iconClassName="h-3 w-3">
                        <p className="text-foreground font-medium">기본 제공 에이전트</p>
                        <p>
                          팀장과 자주 쓰는 <span className="text-foreground">팀원 에이전트</span>가
                          미리 준비된 묶음이에요.
                        </p>
                        <p>설정이 어렵게 느껴진다면 이 옵션을 선택하세요.</p>
                      </HelpHint>
                    </div>
                    <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
                      미리 설정된 전문 에이전트를 바로 사용합니다
                    </p>
                  </div>
                </button>

                {/* 에이전트 커스터마이징 */}
                <button
                  onClick={() => {
                    setCustomizeStep('settings')
                    setView('customize')
                  }}
                  disabled={submitting}
                  className="hover:bg-muted/60 group flex w-full items-start gap-4 rounded-xl p-4 text-left transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50"
                >
                  <div className="bg-muted group-hover:bg-muted/80 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-colors">
                    <SlidersHorizontal className="text-foreground/70 h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-foreground text-sm font-semibold">에이전트 커스터마이징</p>
                    <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
                      새 대화 시작 전에 표시용 이름과 페르소나를 입력합니다
                    </p>
                  </div>
                </button>
                {error && (
                  <p className="text-destructive border-destructive/30 rounded-lg border px-3 py-2 text-xs">
                    {error}
                  </p>
                )}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="customize"
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.18 }}
            >
              {/* Header */}
              <div className="border-border flex items-center gap-3 border-b px-6 py-4">
                <button
                  onClick={() => {
                    if (customizeStep === 'instructions') {
                      setCustomizeStep('settings')
                      return
                    }
                    setView('select')
                  }}
                  className="text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 w-7 items-center justify-center rounded-md transition-colors"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <div className="flex-1">
                  <h2 className="text-foreground text-base font-semibold">에이전트 커스터마이징</h2>
                  <p className="text-muted-foreground mt-0.5 text-xs">
                    {customizeStep === 'settings'
                      ? '새 대화에 사용할 기본 설정을 입력합니다'
                      : '에이전트가 따를 지침을 입력합니다'}
                  </p>
                </div>
                <button
                  onClick={handleClose}
                  className="text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 w-7 items-center justify-center rounded-md transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="max-h-[calc(100vh-200px)] space-y-4 overflow-y-auto px-5 py-4">
                {customizeStep === 'settings' ? (
                  <div className="grid gap-3">
                    <div className="space-y-3">
                      <AgentSectionCard title="프로필">
                        <div className="grid gap-3 sm:grid-cols-[13rem_minmax(0,1fr)]">
                          <AgentImageStepper profileImage={profileImage} />
                          <div className="space-y-2.5">
                            <Field label="이름">
                              <input
                                type="text"
                                value={agentName}
                                onChange={(event) => setAgentName(event.target.value)}
                                placeholder="에이전트 이름"
                                className={inputClass}
                              />
                            </Field>
                            <Field label="호칭">
                              <input
                                type="text"
                                value={callName}
                                onChange={(event) => setCallName(event.target.value)}
                                placeholder="팀장 에이전트"
                                className={inputClass}
                              />
                            </Field>
                          </div>
                        </div>
                      </AgentSectionCard>
                    </div>

                    <div className="space-y-3">
                      <AgentSectionCard title="모델">
                        <Field label="공급자">
                          <AgentAdapterTypeDropdown
                            value="openai"
                            options={[{ value: 'openai', label: 'OpenAI' }]}
                            onChange={() => undefined}
                          />
                        </Field>
                        <Field label="모델">
                          <AgentModelDropdown
                            value={model}
                            options={[{ value: 'gpt-5.4', label: 'gpt-5.4' }]}
                            onChange={setModel}
                            allowDefault
                          />
                        </Field>
                      </AgentSectionCard>

                      <AgentSectionCard title="실행 규칙">
                        <label className="border-border hover:bg-accent/40 flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors">
                          <input
                            type="checkbox"
                            checked={canDelegate}
                            onChange={(event) => setCanDelegate(event.target.checked)}
                            className="border-border mt-0.5 h-4 w-4 rounded"
                          />
                          <span className="min-w-0">
                            <span className="block text-sm font-medium">
                              서브에이전트 호출 허용
                            </span>
                            <span className="text-muted-foreground mt-0.5 block text-xs leading-5">
                              세션 안에서 필요한 서브에이전트를 호출할 수 있습니다.
                            </span>
                          </span>
                        </label>
                      </AgentSectionCard>
                    </div>
                  </div>
                ) : (
                  <AgentSectionCard title="지침">
                    <AgentInstructionsBundlePanel
                      compact
                      content={persona}
                      entryFile={instructionsEntryFile}
                      files={instructionsFiles}
                      mode={instructionsMode}
                      rootPath={instructionsRootPath}
                      onContentChange={setPersona}
                      onEntryFileChange={setInstructionsEntryFile}
                      onFilesChange={setInstructionsFiles}
                      onModeChange={setInstructionsMode}
                      onRootPathChange={setInstructionsRootPath}
                    />
                  </AgentSectionCard>
                )}
              </div>

              {/* Footer */}
              <div className="border-border flex gap-2 border-t px-6 py-4">
                <button
                  onClick={() => {
                    if (customizeStep === 'instructions') {
                      setCustomizeStep('settings')
                      return
                    }
                    setView('select')
                  }}
                  className="bg-muted text-foreground hover:bg-muted/80 flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  이전
                </button>
                {customizeStep === 'settings' ? (
                  <button
                    onClick={() => setCustomizeStep('instructions')}
                    disabled={!agentName.trim()}
                    className="bg-primary hover:bg-primary/90 flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40"
                  >
                    다음
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={handleCustomizeConfirm}
                    disabled={!agentName.trim()}
                    className="bg-primary hover:bg-primary/90 flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    설정 완료
                  </button>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </DialogContent>
    </Dialog>
  )
}

const inputClass =
  'border-border placeholder:text-muted-foreground/40 focus-visible:ring-ring w-full rounded-md border bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-muted-foreground text-xs">{label}</span>
      {children}
    </label>
  )
}

function AgentImageStepper({ profileImage }: { profileImage: string }) {
  return (
    <div
      className="flex min-h-36 w-full min-w-0 items-center justify-center rounded-lg"
      aria-label="에이전트 이미지"
    >
      <div className="bg-accent flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-lg">
        <img src={profileImage} alt="" className="h-24 w-24 object-contain" draggable={false} />
      </div>
    </div>
  )
}
