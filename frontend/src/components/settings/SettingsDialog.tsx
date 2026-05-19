import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import {
  Key,
  Pencil,
  Plus,
  ChevronDown,
  Check,
  Eye,
  Search,
  Globe,
  Loader2,
  CheckCircle2,
  BarChart2,
  RefreshCw,
  Code2,
  GripVertical,
  Send,
  Star,
  Trash2,
  X,
} from 'lucide-react'
import {
  getCommandUsage,
  type CommandUsageSummary,
  type CommandUsageParams,
} from '@/apis/aiCommandUsage'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { HelpHint } from '@/components/ui/help-hint'
import { Switch } from '@/components/ui/switch'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { motion, AnimatePresence } from 'motion/react'
import { useChatStore } from '@/store/useChatStore'
import { getOpenAiModels, type OpenAiModelsResponse } from '@/apis/openaiModels'
import { saveOpenAiApiKey, deleteOpenAiApiKey, type ProviderName } from '@/apis/openaiApiKey'
import { getOpenAiProviders } from '@/apis/openaiProviders'
import {
  getUserSkillDetail,
  updateUserSkillSetting,
  type SkillCatalogDetail,
  type SkillCatalogItem,
} from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import {
  createMattermostChannel,
  deleteMattermostChannel,
  getMattermostChannels,
  sendMattermostMessage,
  setDefaultMattermostChannel,
  updateMattermostChannel,
  type MattermostChannel,
} from '@/apis/mattermost'

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  sessionId?: string
  initialTab?: SettingsTab
  /** true이면 좌측 탭 사이드바를 숨기고 initialTab 하나만 단독으로 보여준다. */
  singleTab?: boolean
}

type SettingsTab = 'general' | 'skills' | 'models' | 'personalization' | 'apiKeys' | 'external'

const isVisibleSettingsTab = (tab?: SettingsTab): tab is 'apiKeys' | 'external' =>
  tab === 'apiKeys' || tab === 'external'

export function SettingsDialog({
  open,
  onOpenChange,
  sessionId,
  initialTab,
  singleTab = false,
}: SettingsDialogProps) {
  const [prevOpen, setPrevOpen] = useState(open)
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    isVisibleSettingsTab(initialTab) ? initialTab : 'apiKeys',
  )

  if (prevOpen !== open) {
    setPrevOpen(open)
    if (open && initialTab) {
      setActiveTab(isVisibleSettingsTab(initialTab) ? initialTab : 'apiKeys')
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    onOpenChange(nextOpen)
  }

  const tabs = [
    { id: 'apiKeys' as const, label: 'API 키', icon: Key },
    { id: 'external' as const, label: '외부 서비스', icon: Globe },
  ]

  return (
    <Dialog open={open} onOpenChange={handleOpenChange} key={`${String(open)}-${initialTab ?? ''}`}>
      <DialogContent
        className="flex h-[85vh] w-[min(90vw,760px)] max-w-none gap-0 overflow-hidden p-0"
        aria-describedby="settings-description"
      >
        <DialogTitle className="sr-only">설정</DialogTitle>
        <DialogDescription id="settings-description" className="sr-only">
          애플리케이션 설정을 관리합니다
        </DialogDescription>

        <div className="flex h-full min-w-0 flex-1 overflow-hidden">
          {/* Left Sidebar — singleTab 모드일 땐 숨김 */}
          {!singleTab && (
            <div className="border-border bg-muted/30 flex w-52 shrink-0 flex-col border-r p-4">
              <div className="mb-6">
                <h2 className="text-foreground text-lg font-semibold">설정</h2>
              </div>
              <div className="space-y-1">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                      activeTab === tab.id
                        ? 'text-foreground bg-white shadow-sm'
                        : 'text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    <tab.icon className="h-4 w-4 shrink-0" />
                    <span className="text-sm font-medium">{tab.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Right Content */}
          <div className="relative min-h-0 flex-1 overflow-y-auto p-6">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                {activeTab === 'general' && <GeneralContent />}
                {activeTab === 'skills' && <SkillsContent />}
                {activeTab === 'models' && <ModelsContent sessionId={sessionId} />}
                {activeTab === 'personalization' && <PersonalizationContent />}
                {activeTab === 'apiKeys' && <ApiKeysContent />}
                {activeTab === 'external' && <ExternalServicesContent />}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// General Content
// ────────────────────────────────────────────────────────────────────────────
function GeneralContent() {
  const [settings, setSettings] = useState({
    language: '한국어',
    theme: '시스템 설정',
    notifications: true,
    soundEffects: true,
  })

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-foreground mb-2 text-xl font-semibold">일반</h3>
        <p className="text-muted-foreground text-sm">애플리케이션의 기본 설정을 관리합니다</p>
      </div>

      <div className="space-y-3">
        {/* Language */}
        <div className="border-border rounded-xl border p-4">
          <div className="mb-1 flex items-start justify-between">
            <div className="flex-1">
              <h4 className="text-foreground mb-1 text-sm font-medium">언어</h4>
              <p className="text-muted-foreground text-xs">애플리케이션 표시 언어를 선택합니다</p>
            </div>
          </div>

          <Popover>
            <PopoverTrigger asChild>
              <button className="border-border hover:bg-muted/30 mt-3 flex w-full items-center justify-between rounded-lg border px-3 py-2 transition-colors">
                <span className="text-foreground text-sm">{settings.language}</span>
                <ChevronDown className="text-muted-foreground h-4 w-4" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-2" align="start">
              <div className="space-y-1">
                {['한국어', 'English', '日本語', '中文'].map((lang) => (
                  <button
                    key={lang}
                    onClick={() => setSettings({ ...settings, language: lang })}
                    className="hover:bg-muted flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left transition-colors"
                  >
                    <span className="text-foreground text-sm font-medium">{lang}</span>
                    {settings.language === lang && <Check className="text-primary h-4 w-4" />}
                  </button>
                ))}
              </div>
            </PopoverContent>
          </Popover>
        </div>

        {/* Theme */}
        <div className="border-border rounded-xl border p-4">
          <div className="mb-1 flex items-start justify-between">
            <div className="flex-1">
              <h4 className="text-foreground mb-1 text-sm font-medium">테마</h4>
              <p className="text-muted-foreground text-xs">화면 테마를 선택합니다</p>
            </div>
          </div>

          <Popover>
            <PopoverTrigger asChild>
              <button className="border-border hover:bg-muted/30 mt-3 flex w-full items-center justify-between rounded-lg border px-3 py-2 transition-colors">
                <span className="text-foreground text-sm">{settings.theme}</span>
                <ChevronDown className="text-muted-foreground h-4 w-4" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-2" align="start">
              <div className="space-y-1">
                {['시스템 설정', '라이트 모드', '다크 모드'].map((theme) => (
                  <button
                    key={theme}
                    onClick={() => setSettings({ ...settings, theme })}
                    className="hover:bg-muted flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left transition-colors"
                  >
                    <span className="text-foreground text-sm font-medium">{theme}</span>
                    {settings.theme === theme && <Check className="text-primary h-4 w-4" />}
                  </button>
                ))}
              </div>
            </PopoverContent>
          </Popover>
        </div>

        {/* Notifications */}
        <div className="bg-muted/30 border-border flex items-start justify-between rounded-xl border p-4">
          <div className="flex-1 pr-4">
            <h4 className="text-foreground mb-1 text-sm font-medium">알림</h4>
            <p className="text-muted-foreground text-xs">데스크톱 알림을 활성화합니다</p>
          </div>
          <Switch
            checked={settings.notifications}
            onCheckedChange={(checked) => setSettings({ ...settings, notifications: checked })}
          />
        </div>

        {/* Sound Effects */}
        <div className="bg-muted/30 border-border flex items-start justify-between rounded-xl border p-4">
          <div className="flex-1 pr-4">
            <h4 className="text-foreground mb-1 text-sm font-medium">효과음</h4>
            <p className="text-muted-foreground text-xs">알림 및 상호작용 시 효과음을 재생합니다</p>
          </div>
          <Switch
            checked={settings.soundEffects}
            onCheckedChange={(checked) => setSettings({ ...settings, soundEffects: checked })}
          />
        </div>
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Skills Content
// ────────────────────────────────────────────────────────────────────────────
function SkillsContent() {
  const [skills, setSkills] = useState<SkillCatalogItem[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draftEnabled, setDraftEnabled] = useState<Record<string, boolean>>({})
  const [detail, setDetail] = useState<SkillCatalogDetail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  const [saving, setSaving] = useState(false)
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor))

  useEffect(() => {
    let alive = true
    void useAgentCacheStore
      .getState()
      .fetchUserSkills()
      .then((items) => {
        if (!alive) return
        setSkills(items)
        setDraftEnabled(Object.fromEntries(items.map((item) => [item.skillId, item.enabled])))
        setError(null)
      })
      .catch(() => {
        if (alive) setError('스킬 목록을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const filteredSkills = skills.filter((skill) => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return true
    return (
      skill.displayName.toLowerCase().includes(query) ||
      skill.name.toLowerCase().includes(query) ||
      skill.description.toLowerCase().includes(query)
    )
  })
  const activeSkills = filteredSkills.filter(
    (skill) => draftEnabled[skill.skillId] ?? skill.enabled,
  )
  const inactiveSkills = filteredSkills.filter(
    (skill) => !(draftEnabled[skill.skillId] ?? skill.enabled),
  )
  const changedSkills = skills.filter(
    (skill) => (draftEnabled[skill.skillId] ?? skill.enabled) !== skill.enabled,
  )

  const setSkillDraftState = (skillId: string, enabled: boolean) => {
    setDraftEnabled((current) => ({ ...current, [skillId]: enabled }))
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const skillId = String(event.active.id)
    const target =
      event.over?.id === 'enabled-skills'
        ? true
        : event.over?.id === 'disabled-skills'
          ? false
          : null
    if (target === null || !skills.some((skill) => skill.skillId === skillId)) return
    setSkillDraftState(skillId, target)
  }

  const openSkillDetail = (skillId: string) => {
    setDetailOpen(true)
    setDetail(null)
    setDetailLoading(true)
    void getUserSkillDetail(skillId)
      .then((item) => {
        setDetail(item)
        setViewMode('preview')
        setError(null)
      })
      .catch(() => {
        setError('스킬 상세를 불러오지 못했습니다.')
      })
      .finally(() => setDetailLoading(false))
  }

  const resetDraft = () => {
    setDraftEnabled(Object.fromEntries(skills.map((item) => [item.skillId, item.enabled])))
    setError(null)
  }

  const saveChanges = async () => {
    if (changedSkills.length === 0) return
    setSaving(true)
    try {
      const savedItems = await Promise.all(
        changedSkills.map((skill) =>
          updateUserSkillSetting(skill.skillId, {
            enabled: draftEnabled[skill.skillId] ?? skill.enabled,
          }),
        ),
      )
      const savedById = new Map(savedItems.map((item) => [item.skillId, item]))
      setSkills((current) => current.map((item) => savedById.get(item.skillId) ?? item))
      setDraftEnabled((current) => ({
        ...current,
        ...Object.fromEntries(savedItems.map((item) => [item.skillId, item.enabled])),
      }))
      // 스킬 활성 상태가 바뀌었으므로 캐시 무효화 — 다음 패널 진입에서 다시 받는다.
      useAgentCacheStore.getState().invalidateUserSkills()
      setError(null)
    } catch {
      setError('스킬 설정을 저장하지 못했습니다.')
      try {
        // 저장 실패로 서버 상태가 의도와 어긋났을 수 있어 캐시 무효화 후 최신본을 다시 받는다.
        useAgentCacheStore.getState().invalidateUserSkills()
        const latest = await useAgentCacheStore.getState().fetchUserSkills()
        setSkills(latest)
        setDraftEnabled(Object.fromEntries(latest.map((item) => [item.skillId, item.enabled])))
      } catch {
        // 저장 실패 뒤 재조회도 실패하면 기존 draft를 유지해 사용자가 다시 시도할 수 있게 둔다.
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="border-border flex flex-wrap items-start justify-between gap-3 border-b px-0 pb-4">
        <div>
          <h3 className="text-foreground mb-2 text-xl font-semibold">스킬 목록</h3>
          <p className="text-muted-foreground text-sm">
            사용자 단위 스킬 catalog와 적용 상태를 관리합니다
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={changedSkills.length === 0 || saving}
            onClick={resetDraft}
            className="border-border hover:bg-accent inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            되돌리기
          </button>
          <button
            type="button"
            disabled={changedSkills.length === 0 || saving}
            onClick={() => void saveChanges()}
            className="bg-foreground text-background hover:bg-foreground/90 inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            저장
          </button>
        </div>
      </div>

      {error ? <p className="text-destructive py-3 text-sm">{error}</p> : null}

      <div className="relative py-3">
        <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="스킬 검색..."
          className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-md border bg-transparent py-2 pr-3 pl-9 text-sm focus:ring-2 focus:outline-none"
        />
      </div>

      {loading ? (
        <div className="text-muted-foreground flex items-center gap-2 py-6 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          조회 중
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 overflow-hidden">
            <SkillDropColumn id="enabled-skills" title="사용 중" count={activeSkills.length}>
              {activeSkills.map((skill) => (
                <DraggableSkillRow
                  key={skill.skillId}
                  skill={skill}
                  changed={(draftEnabled[skill.skillId] ?? skill.enabled) !== skill.enabled}
                  onOpen={() => openSkillDetail(skill.skillId)}
                  onMove={() => setSkillDraftState(skill.skillId, false)}
                  moveLabel="미사용으로"
                />
              ))}
            </SkillDropColumn>
            <SkillDropColumn id="disabled-skills" title="미사용" count={inactiveSkills.length}>
              {inactiveSkills.map((skill) => (
                <DraggableSkillRow
                  key={skill.skillId}
                  skill={skill}
                  changed={(draftEnabled[skill.skillId] ?? skill.enabled) !== skill.enabled}
                  onOpen={() => openSkillDetail(skill.skillId)}
                  onMove={() => setSkillDraftState(skill.skillId, true)}
                  moveLabel="사용으로"
                />
              ))}
            </SkillDropColumn>
          </div>
        </DndContext>
      )}

      {!loading && filteredSkills.length === 0 ? (
        <p className="text-muted-foreground px-3 py-8 text-sm">검색 결과가 없습니다</p>
      ) : null}

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-h-[82vh] max-w-4xl overflow-hidden p-0">
          <DialogHeader className="border-border border-b px-5 py-4">
            <DialogTitle>{detail?.displayName ?? '스킬 상세'}</DialogTitle>
            <DialogDescription>
              {detail?.description ?? '스킬 정보를 확인합니다.'}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[68vh] overflow-y-auto px-5 py-4">
            {detailLoading ? (
              <div className="text-muted-foreground flex items-center gap-2 py-10 text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                상세 조회 중
              </div>
            ) : detail === null ? null : (
              <div className="space-y-4">
                <div className="border-border grid gap-2 border-y py-3 text-sm sm:grid-cols-2">
                  <SkillMeta label="키" value={detail.name} />
                  <SkillMeta
                    label="상태"
                    value={(draftEnabled[detail.skillId] ?? detail.enabled) ? '사용 중' : '미사용'}
                  />
                  <SkillMeta label="타입" value={detail.sourceType} />
                  <SkillMeta label="경로" value={detail.sourcePath ?? '-'} />
                </div>

                {detail.files.length ? (
                  <div className="border-border rounded-md border p-3">
                    <div className="text-muted-foreground mb-2 text-[11px] tracking-[0.16em] uppercase">
                      파일
                    </div>
                    <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
                      {detail.files.map((file) => (
                        <span
                          key={file}
                          className="bg-muted/60 rounded px-2 py-1 font-mono text-[11px]"
                        >
                          {file}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="border-border flex items-center justify-between border-b pb-3">
                  <div className="font-mono text-sm">SKILL.md</div>
                  <div className="border-border flex overflow-hidden rounded-md border">
                    <button
                      type="button"
                      onClick={() => setViewMode('preview')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm ${
                        viewMode === 'preview'
                          ? 'bg-accent text-foreground'
                          : 'text-muted-foreground'
                      }`}
                    >
                      <Eye className="h-3.5 w-3.5" />
                      보기
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode('code')}
                      className={`border-border inline-flex items-center gap-1.5 border-l px-3 py-1.5 text-sm ${
                        viewMode === 'code' ? 'bg-accent text-foreground' : 'text-muted-foreground'
                      }`}
                    >
                      <Code2 className="h-3.5 w-3.5" />
                      코드
                    </button>
                  </div>
                </div>

                {viewMode === 'code' ? (
                  <pre className="bg-muted/30 border-border max-h-[42vh] overflow-auto rounded-md border p-4 text-xs leading-5">
                    <code>{detail.body || '내용이 없습니다.'}</code>
                  </pre>
                ) : (
                  <div className="border-border bg-muted/20 max-h-[42vh] overflow-auto rounded-md border p-4">
                    <pre className="text-foreground font-sans text-sm leading-6 whitespace-pre-wrap">
                      {stripSkillFrontmatter(detail.body) ||
                        detail.description ||
                        '내용이 없습니다.'}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SkillDropColumn({
  id,
  title,
  count,
  children,
}: {
  id: string
  title: string
  count: number
  children: ReactNode
}) {
  const { isOver, setNodeRef } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      className={`border-border min-h-0 overflow-hidden rounded-md border ${
        isOver ? 'ring-primary/30 ring-2' : ''
      }`}
    >
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-muted-foreground font-mono text-xs">{count}</div>
      </div>
      <div className="max-h-[50vh] min-h-60 space-y-2 overflow-y-auto p-2">{children}</div>
    </div>
  )
}

function DraggableSkillRow({
  skill,
  changed,
  moveLabel,
  onOpen,
  onMove,
}: {
  skill: SkillCatalogItem
  changed: boolean
  moveLabel: string
  onOpen: () => void
  onMove: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: skill.skillId,
  })
  const style = {
    transform: CSS.Transform.toString(transform),
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`border-border bg-background grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-md border p-2 text-sm shadow-sm ${
        isDragging ? 'z-10 opacity-70' : ''
      }`}
    >
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground cursor-grab rounded p-1"
        aria-label="드래그"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{skill.displayName}</span>
          {changed ? (
            <span className="bg-accent rounded px-1.5 py-0.5 text-[10px]">변경됨</span>
          ) : null}
        </div>
        <div className="text-muted-foreground truncate font-mono text-[11px]">{skill.name}</div>
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onOpen}
          className="border-border hover:bg-accent rounded border px-2 py-1 text-xs"
        >
          상세
        </button>
        <button
          type="button"
          onClick={onMove}
          className="border-border hover:bg-accent rounded border px-2 py-1 text-xs"
        >
          {moveLabel}
        </button>
      </div>
    </div>
  )
}

function SkillMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-muted-foreground text-[11px] tracking-[0.16em] uppercase">{label}</div>
      <div className="mt-1 truncate font-mono text-xs" title={value}>
        {value}
      </div>
    </div>
  )
}

function stripSkillFrontmatter(markdown: string) {
  const normalized = markdown.replace(/\r\n/g, '\n')
  if (!normalized.startsWith('---\n')) return normalized.trim()
  const closing = normalized.indexOf('\n---\n', 4)
  if (closing < 0) return normalized.trim()
  return normalized.slice(closing + 5).trim()
}

// ────────────────────────────────────────────────────────────────────────────
// Models Content
// ────────────────────────────────────────────────────────────────────────────
function ModelsContent({ sessionId }: { sessionId?: string }) {
  const updateSessionSettings = useChatStore((state) => state.updateSessionSettings)
  const [modelData, setModelData] = useState<OpenAiModelsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    getOpenAiModels()
      .then((data) => {
        setModelData(data)
        setSelectedModel(data.defaultModel)
      })
      .catch(() => setError('모델 목록을 불러오는데 실패했습니다.'))
      .finally(() => setLoading(false))
  }, [])

  const handleSelectModel = async (modelId: string) => {
    if (sessionId === undefined) {
      setSaveError('세션을 연 뒤 모델을 저장할 수 있습니다.')
      return
    }
    setSelectedModel(modelId)
    setSaveError(null)
    try {
      await updateSessionSettings({ sessionId, settingsPatch: { model: modelId } })
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : '모델 설정 저장에 실패했습니다.')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-foreground mb-2 text-xl font-semibold">모델</h3>
        <p className="text-muted-foreground text-sm">
          사용 가능한 AI 모델 목록을 확인하고 현재 대화의 모델을 선택합니다
        </p>
      </div>

      {loading && (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          모델 목록을 불러오는 중입니다.
        </div>
      )}

      {error && (
        <div className="border-border bg-muted/30 text-muted-foreground rounded-xl border p-4 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && modelData && (
        <div className="space-y-5">
          {modelData.providers.map((provider) => (
            <div key={provider.providerName}>
              <h4 className="text-foreground mb-2 text-sm font-semibold">{provider.displayName}</h4>
              <div className="space-y-2">
                {provider.models.map((modelId) => (
                  <button
                    key={modelId}
                    type="button"
                    onClick={() => void handleSelectModel(modelId)}
                    className={`border-border flex w-full items-start justify-between rounded-xl border p-4 text-left transition-colors ${
                      selectedModel === modelId ? 'bg-primary/5 border-primary/30' : 'bg-muted/30'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <h5 className="text-foreground truncate text-sm font-medium">{modelId}</h5>
                      <p className="text-muted-foreground mt-1 text-xs">{provider.displayName}</p>
                    </div>
                    {selectedModel === modelId && (
                      <Check className="text-primary h-4 w-4 shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {saveError && <p className="text-destructive text-sm">{saveError}</p>}
      {sessionId === undefined && (
        <p className="text-muted-foreground text-xs">
          대화별 모델 저장은 채팅 화면에서 설정을 열었을 때만 적용됩니다.
        </p>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Personalization Content
// ────────────────────────────────────────────────────────────────────────────
function PersonalizationContent() {
  const [settings, setSettings] = useState({
    nickname: 'Heygent',
    tone: '기본값',
    formality: '보통',
    language: '자동 탐지',
  })

  const sections = [
    {
      id: 'tone',
      title: '기본 스타일 및 말투',
      description:
        'ChatGPT가 응답하는 스타일과 말투를 지정합니다. ChatGPT의 성능에는 영향을 주지 않습니다.',
      value: settings.tone,
      options: [
        { value: '기본값', label: '기본값', description: '기본 스타일과 말투' },
        { value: '전문적인', label: '전문적인', description: '정제되어 있고 전문적임' },
        { value: '친근한', label: '친근한', description: '따뜻하고 수다스러움' },
        { value: '솔직함', label: '솔직함', description: '직설적이면서도 격려적' },
        { value: '독특함', label: '독특함', description: '유쾌하고 상상력이 풍부함' },
        { value: '냉소적', label: '냉소적', description: '비꼬면서 비판적임' },
      ],
    },

    {
      id: 'language',
      title: '언어',
      description: '응답 언어를 선택합니다',
      value: settings.language,
      options: [
        { value: '자동 탐지', label: '자동 탐지', description: '' },
        { value: '한국어', label: '한국어', description: '' },
        { value: 'English', label: 'English', description: '' },
        { value: '日本語', label: '日本語', description: '' },
      ],
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-foreground mb-2 text-xl font-semibold">개인 맞춤 설정</h3>
        <p className="text-muted-foreground text-sm">Heygent의 스타일과 말투를 개인화합니다</p>
      </div>

      <div className="space-y-3">
        {/* Nickname */}
        <div className="border-border rounded-xl border p-4">
          <div className="mb-1 flex items-start justify-between">
            <div className="flex-1">
              <h4 className="text-foreground mb-1 text-sm font-medium">음성 호출 이름</h4>
              <p className="text-muted-foreground text-xs">
                음성으로 AI를 호출할 때 사용할 이름을 설정합니다 (예: "헤이전트", "자비스")
              </p>
            </div>
          </div>

          <input
            type="text"
            value={settings.nickname}
            onChange={(e) => setSettings({ ...settings, nickname: e.target.value })}
            placeholder="음성 호출 이름을 입력하세요"
            className="border-border text-foreground placeholder:text-muted-foreground focus:ring-primary/20 mt-3 w-full rounded-lg border bg-white px-3 py-2 text-sm focus:ring-2 focus:outline-none"
          />
          <p className="text-muted-foreground mt-2 text-xs">예시: "안녕, {settings.nickname}"</p>
        </div>

        {sections.map((section) => (
          <div key={section.id} className="border-border rounded-xl border p-4">
            <div className="mb-1 flex items-start justify-between">
              <div className="flex-1">
                <h4 className="text-foreground mb-1 text-sm font-medium">{section.title}</h4>
                <p className="text-muted-foreground text-xs">{section.description}</p>
              </div>
            </div>

            <Popover>
              <PopoverTrigger asChild>
                <button className="border-border hover:bg-muted/30 mt-3 flex w-full items-center justify-between rounded-lg border px-3 py-2 transition-colors">
                  <span className="text-foreground text-sm">{section.value}</span>
                  <ChevronDown className="text-muted-foreground h-4 w-4" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-80 p-2" align="start">
                <div className="space-y-1">
                  {section.options.map((option) => (
                    <button
                      key={option.value}
                      onClick={() => {
                        setSettings({ ...settings, [section.id]: option.value })
                      }}
                      className="hover:bg-muted flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors"
                    >
                      <div className="flex-1">
                        <div className="mb-0.5 flex items-center gap-2">
                          <span className="text-foreground text-sm font-medium">
                            {option.label}
                          </span>
                          {settings[section.id as keyof typeof settings] === option.value && (
                            <Check className="text-primary h-4 w-4" />
                          )}
                        </div>
                        {option.description && (
                          <p className="text-muted-foreground text-xs">{option.description}</p>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          </div>
        ))}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// API Keys Content
// ────────────────────────────────────────────────────────────────────────────
const API_KEY_GUIDES = {
  openai_api_key: {
    placeholder: 'sk-proj-...',
    steps: [
      {
        before: '',
        linkLabel: 'OpenAI Platform',
        href: 'https://platform.openai.com',
        after: '에 접속합니다.',
      },
      { text: '로그인 후 우측 상단 메뉴에서 API Keys를 선택합니다.' },
      { text: 'Create new secret key 버튼을 눌러 키를 생성합니다.' },
      { text: '생성된 키는 한 번만 표시됩니다. 바로 복사해 안전한 곳에 저장하세요.' },
    ],
  },
  gemini_api_key: {
    placeholder: 'AIza...',
    steps: [
      {
        before: '',
        linkLabel: 'Google AI Studio',
        href: 'https://aistudio.google.com/apikey',
        after: '에 접속합니다.',
      },
      { text: 'Google 계정으로 로그인합니다.' },
      { text: 'Create API key 버튼을 눌러 키를 생성합니다.' },
      { text: '생성된 키를 복사해 안전한 곳에 저장하세요.' },
    ],
  },
} as const

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

// 등록된 API 키가 있다는 시각적 표시 — 실제 값과는 무관하며 자릿수만 비슷하게 점으로 채운 placeholder
const MASKED_KEY_LENGTHS: Record<string, number> = {
  openai_api_key: 51, // sk-... 약 51자
  gemini_api_key: 39, // AIza... 약 39자
  claude_api_key: 108, // sk-ant-api03-... 약 108자
}

function getMaskedKeyPlaceholder(providerName: string): string {
  const length = MASKED_KEY_LENGTHS[providerName] ?? 40
  return '•'.repeat(length)
}

function ApiKeysContent() {
  const [apiKeys, setApiKeys] = useState([
    { id: 'openai_api_key' as const, name: 'OpenAI API', value: '' },
    { id: 'gemini_api_key' as const, name: 'Gemini API', value: '' },
  ])
  const [connectedProviders, setConnectedProviders] = useState<Record<string, boolean>>({})

  useEffect(() => {
    void getOpenAiProviders()
      .then((res) => {
        const map = Object.fromEntries(res.providers.map((p) => [p.providerName, p.connected]))
        setConnectedProviders(map)
      })
      .catch(() => {})
  }, [])

  // ── 토큰 사용량 ──────────────────────────────────────────────────────────────
  const today = new Date().toISOString().slice(0, 10)
  const firstOfMonth = today.slice(0, 7) + '-01'
  const [usageFrom, setUsageFrom] = useState(firstOfMonth)
  const [usageTo, setUsageTo] = useState(today)
  const [usageSummary, setUsageSummary] = useState<CommandUsageSummary | null>(null)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageError, setUsageError] = useState<string | null>(null)

  const fetchUsage = useCallback(async (params: CommandUsageParams) => {
    setUsageLoading(true)
    setUsageError(null)
    try {
      const result = await getCommandUsage(params)
      setUsageSummary(result.summary)
    } catch {
      setUsageError('사용량을 불러오지 못했습니다.')
    } finally {
      setUsageLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchUsage({ from: firstOfMonth, to: today })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [saveStatuses, setSaveStatuses] = useState<Record<string, SaveStatus>>({})
  const [saveErrors, setSaveErrors] = useState<Record<string, string | null>>({})
  const [deleteStatuses, setDeleteStatuses] = useState<Record<string, SaveStatus>>({})

  const handleDelete = async (id: ProviderName) => {
    setDeleteStatuses((prev) => ({ ...prev, [id]: 'saving' }))
    try {
      await deleteOpenAiApiKey(id)
      setConnectedProviders((prev) => ({ ...prev, [id]: false }))
      setApiKeys((prev) => prev.map((k) => (k.id === id ? { ...k, value: '' } : k)))
      setDeleteStatuses((prev) => ({ ...prev, [id]: 'saved' }))
      setTimeout(() => setDeleteStatuses((prev) => ({ ...prev, [id]: 'idle' })), 2000)
    } catch {
      setDeleteStatuses((prev) => ({ ...prev, [id]: 'error' }))
    }
  }

  const handleSave = async (id: ProviderName) => {
    const key = apiKeys.find((k) => k.id === id)
    if (!key || !key.value.trim()) return
    setSaveStatuses((prev) => ({ ...prev, [id]: 'saving' }))
    setSaveErrors((prev) => ({ ...prev, [id]: null }))
    try {
      await saveOpenAiApiKey(id, { apiKey: key.value.trim() })
      setConnectedProviders((prev) => ({ ...prev, [id]: true }))
      setSaveStatuses((prev) => ({ ...prev, [id]: 'saved' }))
      setTimeout(() => setSaveStatuses((prev) => ({ ...prev, [id]: 'idle' })), 2000)
    } catch (e) {
      setSaveStatuses((prev) => ({ ...prev, [id]: 'error' }))
      setSaveErrors((prev) => ({
        ...prev,
        [id]: e instanceof Error ? e.message : '저장에 실패했습니다.',
      }))
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-foreground text-xl font-semibold">API 키</h3>
          <HelpHint label="API 키 도움말" iconClassName="h-4 w-4" triggerTabIndex={-1}>
            <p className="text-foreground font-medium">API 키란?</p>
            <p>
              OpenAI·Gemini 같은 외부 AI 서비스를 내 계정으로 쓰기 위한{' '}
              <span className="text-foreground">출입증</span>이에요.
            </p>
            <p>각 서비스 홈페이지에서 발급받아 여기에 붙여넣으면 끝입니다.</p>
            <p className="text-red-500 dark:text-red-400">
              ⚠ 비밀번호와 같은 정보입니다. 절대 다른 사람과 공유하거나 메신저·문서에 붙여넣지
              마세요.
            </p>
          </HelpHint>
        </div>
        <p className="text-muted-foreground text-sm">
          외부 서비스 연동을 위한 API 키를 입력해 주세요
        </p>
      </div>

      <div className="space-y-3">
        {apiKeys.map(
          (key: { id: 'openai_api_key' | 'gemini_api_key'; name: string; value: string }) => {
            const guide = API_KEY_GUIDES[key.id]
            return (
              <div
                key={key.id}
                className="bg-muted/30 border-border space-y-3 rounded-xl border p-4"
              >
                {/* 레이블 + 버튼 행 */}
                <div className="flex items-center justify-between gap-4">
                  <div className="flex shrink-0 items-center gap-2">
                    <label className="text-foreground text-sm font-medium">{key.name}</label>
                    {connectedProviders[key.id] && (
                      <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="h-3 w-3" />
                        등록됨
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedId(expandedId === key.id ? null : key.id)}
                      className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs whitespace-nowrap transition-colors"
                    >
                      <span>{expandedId === key.id ? '접기' : '발급 방법 보기'}</span>
                      <ChevronDown
                        className={`h-3.5 w-3.5 transition-transform duration-200 ${expandedId === key.id ? 'rotate-180' : ''}`}
                      />
                    </button>
                  </div>
                </div>

                {/* 입력창 */}
                <div className="relative">
                  <input
                    type="password"
                    value={key.value}
                    onChange={(e) =>
                      setApiKeys((prev) =>
                        prev.map((k) => (k.id === key.id ? { ...k, value: e.target.value } : k)),
                      )
                    }
                    placeholder={
                      connectedProviders[key.id]
                        ? getMaskedKeyPlaceholder(key.id)
                        : guide.placeholder
                    }
                    className="border-border text-foreground placeholder:text-muted-foreground/80 focus:ring-ring/20 w-full rounded-lg border bg-transparent px-3 py-2 text-sm focus:ring-2 focus:outline-none"
                  />
                </div>

                {/* 저장/삭제 버튼 행 */}
                <div className="flex items-center justify-between gap-2">
                  {saveStatuses[key.id] === 'error' && saveErrors[key.id] ? (
                    <p className="text-destructive text-xs">{saveErrors[key.id]}</p>
                  ) : saveStatuses[key.id] === 'saved' ? (
                    <p className="flex items-center gap-1 text-xs text-emerald-500">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      저장됐습니다
                    </p>
                  ) : deleteStatuses[key.id] === 'saved' ? (
                    <p className="flex items-center gap-1 text-xs text-emerald-500">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      삭제됐습니다
                    </p>
                  ) : deleteStatuses[key.id] === 'error' ? (
                    <p className="text-destructive text-xs">삭제에 실패했습니다.</p>
                  ) : (
                    <span />
                  )}
                  <div className="flex items-center gap-2">
                    {connectedProviders[key.id] && (
                      <button
                        type="button"
                        disabled={deleteStatuses[key.id] === 'saving'}
                        onClick={() => void handleDelete(key.id)}
                        className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-500 transition-colors hover:bg-red-50 disabled:opacity-40 dark:border-red-800 dark:hover:bg-red-950"
                      >
                        {deleteStatuses[key.id] === 'saving' ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        {deleteStatuses[key.id] === 'saving' ? '삭제 중...' : '삭제'}
                      </button>
                    )}
                    {key.value.trim() && (
                      <button
                        type="button"
                        disabled={saveStatuses[key.id] === 'saving'}
                        onClick={() => void handleSave(key.id)}
                        className="bg-foreground text-background hover:bg-foreground/85 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40"
                      >
                        {saveStatuses[key.id] === 'saving' ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        {saveStatuses[key.id] === 'saving' ? '저장 중...' : '저장'}
                      </button>
                    )}
                  </div>
                </div>

                {/* 아코디언 발급 안내 */}
                {expandedId === key.id && (
                  <div className="border-border/60 space-y-3 border-t pt-3">
                    <ol className="space-y-2">
                      {guide.steps.map((step, i) => (
                        <li key={i} className="flex gap-2.5 text-sm">
                          <span className="text-muted-foreground shrink-0 font-medium">
                            {i + 1}.
                          </span>
                          <span className="text-muted-foreground leading-5">
                            {'href' in step ? (
                              <>
                                {step.before}
                                <a
                                  href={step.href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-foreground underline underline-offset-2 transition-opacity hover:opacity-70"
                                >
                                  {step.linkLabel}
                                </a>
                                {step.after}
                              </>
                            ) : (
                              step.text
                            )}
                          </span>
                        </li>
                      ))}
                    </ol>
                    <div className="bg-muted space-y-1 rounded-lg px-3 py-2.5">
                      <p className="text-foreground text-xs font-medium">⚠️ 보안 주의사항</p>
                      <ul className="text-muted-foreground space-y-0.5 text-xs leading-5">
                        <li>• API 키는 비밀번호와 같습니다. 절대 타인과 공유하지 마세요.</li>
                        <li>• 키가 노출되었다면 즉시 삭제 후 재발급받으세요.</li>
                      </ul>
                    </div>
                  </div>
                )}
              </div>
            )
          },
        )}
      </div>

      {/* 토큰 사용량 */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <BarChart2 className="text-muted-foreground h-4 w-4" />
          <h4 className="text-foreground text-base font-semibold">토큰 사용량</h4>
        </div>

        {/* 기간 필터 */}
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={usageFrom}
            max={usageTo}
            onChange={(e) => setUsageFrom(e.target.value)}
            className="border-border bg-muted/30 text-foreground rounded-lg border px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-white/20"
          />
          <span className="text-muted-foreground text-sm">~</span>
          <input
            type="date"
            value={usageTo}
            min={usageFrom}
            max={today}
            onChange={(e) => setUsageTo(e.target.value)}
            className="border-border bg-muted/30 text-foreground rounded-lg border px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-white/20"
          />
          <button
            onClick={() => void fetchUsage({ from: usageFrom, to: usageTo })}
            disabled={usageLoading}
            className="bg-muted text-foreground hover:bg-muted/80 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${usageLoading ? 'animate-spin' : ''}`} />
            조회
          </button>
        </div>

        {/* 결과 */}
        {usageError && <p className="text-destructive text-sm">{usageError}</p>}
        {usageSummary && !usageLoading && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {[
              { label: '총 토큰', value: usageSummary.totalTokens.toLocaleString() },
              { label: '입력 토큰', value: usageSummary.inputTokens.toLocaleString() },
              { label: '출력 토큰', value: usageSummary.outputTokens.toLocaleString() },
              { label: '캐시 토큰', value: usageSummary.cachedInputTokens.toLocaleString() },
              { label: '추론 토큰', value: usageSummary.reasoningTokens.toLocaleString() },
              {
                label: '예상 비용',
                value: `$${usageSummary.estimatedCostUsd.toFixed(4)}`,
              },
            ].map(({ label, value }) => (
              <div key={label} className="bg-muted/30 border-border rounded-xl border px-4 py-3">
                <p className="text-muted-foreground mb-1 text-xs">{label}</p>
                <p className="text-foreground text-sm font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>
        )}
        {usageSummary && (
          <p className="text-muted-foreground text-xs">
            조회된 기록 {usageSummary.recordCount.toLocaleString()}건
          </p>
        )}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Channels Content
// ────────────────────────────────────────────────────────────────────────────
function ChannelsContent({
  embedded = false,
  onChannelsChange,
}: {
  embedded?: boolean
  onChannelsChange?: (channels: MattermostChannel[]) => void
} = {}) {
  const [channels, setChannels] = useState<MattermostChannel[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState({
    alias: '',
    webhookUrl: '',
    defaultChannel: false,
  })
  const [testMessage, setTestMessage] = useState(
    '[Heygent] Mattermost 채널 설정 테스트 메시지입니다.',
  )
  const [testingAlias, setTestingAlias] = useState<string | null>(null)
  const [statusText, setStatusText] = useState<string | null>(null)
  const [errorText, setErrorText] = useState<string | null>(null)

  const isEditing = editingId !== null
  const canSave = form.alias.trim() !== '' && (isEditing || form.webhookUrl.trim() !== '')

  const resetForm = () => {
    setEditingId(null)
    setForm({
      alias: '',
      webhookUrl: '',
      defaultChannel: false,
    })
  }

  const loadChannels = useCallback(async () => {
    setLoading(true)
    setErrorText(null)
    try {
      const nextChannels = await getMattermostChannels()
      setChannels(nextChannels)
      onChannelsChange?.(nextChannels)
    } catch {
      setErrorText('Mattermost 채널 설정을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [onChannelsChange])

  useEffect(() => {
    let cancelled = false
    void Promise.resolve().then(() => {
      if (!cancelled) {
        void loadChannels()
      }
    })
    return () => {
      cancelled = true
    }
  }, [loadChannels])

  const handleSaveChannel = async () => {
    if (!canSave) return
    setSaving(true)
    setErrorText(null)
    setStatusText(null)
    try {
      const payload = {
        alias: form.alias.trim(),
        displayName: form.alias.trim(),
        webhookUrl: form.webhookUrl.trim(),
        defaultChannel: form.defaultChannel,
      }
      if (editingId === null) {
        await createMattermostChannel(payload)
        setStatusText('Mattermost 채널 설정을 추가했습니다.')
      } else {
        await updateMattermostChannel(editingId, payload)
        setStatusText('Mattermost 채널 설정을 수정했습니다.')
      }
      resetForm()
      await loadChannels()
    } catch {
      setErrorText('채널 설정 저장에 실패했습니다. 별칭과 Webhook URL을 확인하세요.')
    } finally {
      setSaving(false)
    }
  }

  const handleEditChannel = (channel: MattermostChannel) => {
    setEditingId(channel.id)
    setStatusText(null)
    setErrorText(null)
    setForm({
      alias: channel.alias,
      webhookUrl: '',
      defaultChannel: channel.defaultChannel,
    })
  }

  const handleDeleteChannel = async (channelId: number) => {
    setErrorText(null)
    setStatusText(null)
    try {
      await deleteMattermostChannel(channelId)
      setStatusText('Mattermost 채널 설정을 삭제했습니다.')
      if (editingId === channelId) {
        resetForm()
      }
      await loadChannels()
    } catch {
      setErrorText('채널 설정 삭제에 실패했습니다.')
    }
  }

  const handleSetDefaultChannel = async (channelId: number) => {
    setErrorText(null)
    setStatusText(null)
    try {
      await setDefaultMattermostChannel(channelId)
      setStatusText('기본 Mattermost 채널을 변경했습니다.')
      await loadChannels()
    } catch {
      setErrorText('기본 채널 변경에 실패했습니다.')
    }
  }

  const handleSendTest = async (target: string) => {
    if (testMessage.trim() === '') return
    setTestingAlias(target)
    setErrorText(null)
    setStatusText(null)
    try {
      await sendMattermostMessage({
        target,
        message: testMessage.trim(),
      })
      setStatusText(`${target} 채널로 테스트 메시지를 보냈습니다.`)
    } catch {
      setErrorText('테스트 메시지 전송에 실패했습니다. 채널 설정을 확인하세요.')
    } finally {
      setTestingAlias(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        {embedded ? (
          <h4 className="text-foreground mb-2 text-sm font-semibold">Mattermost 채널 설정</h4>
        ) : (
          <h3 className="text-foreground mb-2 text-xl font-semibold">채널 연결</h3>
        )}
        <p className="text-muted-foreground text-sm">
          Mattermost 채널 별칭과 Incoming Webhook URL을 등록합니다.
        </p>
      </div>

      <div className="bg-muted/30 border-border space-y-4 rounded-xl border p-4">
        <label className="block min-w-0">
          <span className="text-foreground mb-1.5 block text-xs font-medium">채널 별칭</span>
          <input
            type="text"
            value={form.alias}
            onChange={(event) => setForm((prev) => ({ ...prev, alias: event.target.value }))}
            placeholder="free 또는 자유채널"
            className="border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border px-3 py-2 text-sm focus:ring-2 focus:outline-none"
          />
          <span className="text-muted-foreground mt-1.5 block text-xs">
            대화에서 이 별칭을 말하면 해당 Mattermost 채널로 전송합니다.
          </span>
        </label>

        <label className="block">
          <span className="text-foreground mb-1.5 block text-xs font-medium">
            Incoming Webhook URL
          </span>
          <input
            type="url"
            value={form.webhookUrl}
            onChange={(event) => setForm((prev) => ({ ...prev, webhookUrl: event.target.value }))}
            placeholder={
              isEditing ? '변경할 때만 새 URL을 입력하세요' : 'https://meeting.ssafy.com/hooks/...'
            }
            className="border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border px-3 py-2 text-sm focus:ring-2 focus:outline-none"
          />
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2">
            <Switch
              checked={form.defaultChannel}
              onCheckedChange={(checked) =>
                setForm((prev) => ({ ...prev, defaultChannel: checked }))
              }
            />
            <span className="text-foreground text-sm">기본 채널로 지정</span>
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSaveChannel()}
              disabled={!canSave || saving}
              className="bg-foreground text-background hover:bg-foreground/85 inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:opacity-40"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {isEditing ? '수정' : '추가'}
            </button>
            {isEditing && (
              <button
                type="button"
                onClick={resetForm}
                className="border-border text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors"
              >
                <X className="h-4 w-4" />
                취소
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block">
          <span className="text-foreground mb-1.5 block text-xs font-medium">테스트 메시지</span>
          <textarea
            value={testMessage}
            onChange={(event) => setTestMessage(event.target.value)}
            rows={3}
            className="border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:ring-primary/20 w-full rounded-lg border px-3 py-2 text-sm focus:ring-2 focus:outline-none"
          />
        </label>

        {loading && (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            채널 설정을 불러오는 중입니다.
          </div>
        )}

        {!loading && channels.length === 0 && (
          <div className="border-border text-muted-foreground rounded-xl border p-4 text-sm">
            등록된 Mattermost 채널이 없습니다.
          </div>
        )}

        {channels.map((channel) => (
          <div
            key={channel.id}
            className="bg-muted/30 border-border space-y-3 rounded-xl border p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-foreground text-sm font-semibold">{channel.alias}</h4>
                  {channel.defaultChannel && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                      <Star className="h-3 w-3" />
                      기본
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground mt-1 text-xs">
                  채팅 호출 이름: <span className="text-foreground">{channel.alias}</span>
                  {channel.webhookConfigured ? ' · webhook 등록됨' : ''}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap justify-end gap-2">
                {!channel.defaultChannel && (
                  <button
                    type="button"
                    onClick={() => void handleSetDefaultChannel(channel.id)}
                    className="border-border text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors"
                  >
                    <Star className="h-3.5 w-3.5" />
                    기본
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void handleSendTest(channel.alias)}
                  disabled={testingAlias === channel.alias || testMessage.trim() === ''}
                  className="border-border text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-40"
                >
                  {testingAlias === channel.alias ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Send className="h-3.5 w-3.5" />
                  )}
                  테스트
                </button>
                <button
                  type="button"
                  onClick={() => handleEditChannel(channel)}
                  className="border-border text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  수정
                </button>
                <button
                  type="button"
                  onClick={() => void handleDeleteChannel(channel.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-500 transition-colors hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  삭제
                </button>
              </div>
            </div>
          </div>
        ))}

        {statusText && (
          <p className="flex items-center gap-1.5 text-xs text-emerald-500">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {statusText}
          </p>
        )}
        {errorText && <p className="text-destructive text-xs">{errorText}</p>}
      </div>

      <div className="border-border text-muted-foreground rounded-xl border p-4 text-sm leading-6">
        대화에서 <span className="text-foreground">free 채널에 보내줘</span>처럼 요청하면 등록된
        별칭을 기준으로 전송할 수 있습니다. Webhook URL은 목록에 표시하지 않습니다.
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// External Services Content
// ────────────────────────────────────────────────────────────────────────────
function ExternalServicesContent() {
  const [notionConnected, setNotionConnected] = useState(false)
  const [gmailConnected, setGmailConnected] = useState(false)
  const [mattermostChannels, setMattermostChannels] = useState<MattermostChannel[]>([])
  const [mattermostLoading, setMattermostLoading] = useState(true)
  const [mattermostSettingsOpen, setMattermostSettingsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [gmailLoading, setGmailLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const gmailPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const mattermostConnected = mattermostChannels.length > 0
  const defaultMattermostChannel = mattermostChannels.find((channel) => channel.defaultChannel)

  // 마운트 시 연결 상태 조회
  useEffect(() => {
    import('@/apis/notion').then(({ getNotionStatus }) => {
      getNotionStatus()
        .then((res) => setNotionConnected(res.data.connected))
        .catch(() => {})
    })
    import('@/apis/gmail').then(({ getGmailStatus }) => {
      getGmailStatus()
        .then((res) => setGmailConnected(res.data.connected))
        .catch(() => {})
    })
  }, [])

  const loadMattermostChannels = useCallback(async () => {
    setMattermostLoading(true)
    try {
      const channels = await getMattermostChannels()
      setMattermostChannels(channels)
    } catch {
      setMattermostChannels([])
    } finally {
      setMattermostLoading(false)
    }
  }, [])

  const handleMattermostChannelsChange = useCallback((channels: MattermostChannel[]) => {
    setMattermostChannels(channels)
  }, [])

  useEffect(() => {
    void Promise.resolve().then(() => loadMattermostChannels())
  }, [loadMattermostChannels])

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const handleNotionConnect = async () => {
    try {
      setLoading(true)
      // 팝업 차단 방지: 창 먼저 열고 URL 나중에 설정
      const popup = window.open('about:blank', '_blank')
      const { getNotionConnectUrl, getNotionStatus } = await import('@/apis/notion')
      const res = await getNotionConnectUrl()
      if (popup) {
        popup.location.href = res.data.url
      } else {
        window.open(res.data.url, '_blank')
      }

      // OAuth 창 열고 나서 연결 완료될 때까지 폴링
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await getNotionStatus()
          if (statusRes.data.connected) {
            setNotionConnected(true)
            stopPolling()
            setLoading(false)
          }
        } catch {
          stopPolling()
          setLoading(false)
        }
      }, 2000)

      // 2분 후 자동 폴링 중단
      setTimeout(() => {
        stopPolling()
        setLoading(false)
      }, 120000)
    } catch {
      setLoading(false)
    }
  }

  const handleNotionDisconnect = async () => {
    try {
      const { disconnectNotion } = await import('@/apis/notion')
      await disconnectNotion()
      setNotionConnected(false)
    } catch {
      // 에러 무시
    }
  }

  const stopGmailPolling = () => {
    if (gmailPollRef.current) {
      clearInterval(gmailPollRef.current)
      gmailPollRef.current = null
    }
  }

  const handleGmailConnect = async () => {
    try {
      setGmailLoading(true)
      const popup = window.open('about:blank', '_blank')
      const { getGmailConnectUrl, getGmailStatus } = await import('@/apis/gmail')
      const res = await getGmailConnectUrl()
      if (popup) {
        popup.location.href = res.data.url
      } else {
        window.open(res.data.url, '_blank')
      }

      gmailPollRef.current = setInterval(async () => {
        try {
          const statusRes = await getGmailStatus()
          if (statusRes.data.connected) {
            setGmailConnected(true)
            stopGmailPolling()
            setGmailLoading(false)
          }
        } catch {
          stopGmailPolling()
          setGmailLoading(false)
        }
      }, 2000)

      setTimeout(() => {
        stopGmailPolling()
        setGmailLoading(false)
      }, 120000)
    } catch {
      setGmailLoading(false)
    }
  }

  const handleGmailDisconnect = async () => {
    try {
      const { disconnectGmail } = await import('@/apis/gmail')
      await disconnectGmail()
      setGmailConnected(false)
    } catch {
      // 에러 무시
    }
  }

  useEffect(
    () => () => {
      stopPolling()
      stopGmailPolling()
    },
    [],
  )

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-foreground mb-2 text-xl font-semibold">외부 서비스</h3>
        <p className="text-muted-foreground text-sm">외부 서비스를 연결하여 기능을 확장합니다</p>
      </div>

      <div className="space-y-3">
        <div
          className={`rounded-xl border p-4 transition-colors ${
            notionConnected ? 'bg-muted/40 border-border' : 'bg-background border-border'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-black">
                <svg
                  viewBox="0 0 24 24"
                  className="h-5 w-5 fill-white"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.139c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z" />
                </svg>
              </div>
              <div>
                <h4 className="text-foreground text-sm font-medium">Notion</h4>
                <span
                  className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${
                    notionConnected ? 'text-switch-on' : 'text-muted-foreground'
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      notionConnected ? 'bg-switch-on' : 'bg-muted-foreground/60'
                    }`}
                  />
                  {notionConnected ? '연결됨' : '미연결'}
                </span>
              </div>
            </div>
            <button
              onClick={notionConnected ? handleNotionDisconnect : handleNotionConnect}
              disabled={loading}
              className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 ${
                notionConnected
                  ? 'border-border bg-background text-foreground hover:bg-muted'
                  : 'border-foreground bg-foreground text-background hover:bg-foreground/90'
              }`}
            >
              {loading ? '연결 중...' : notionConnected ? '연결 해제' : '연결하기'}
            </button>
          </div>
        </div>

        <div
          className={`rounded-xl border p-4 transition-colors ${
            gmailConnected ? 'bg-muted/40 border-border' : 'bg-background border-border'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white">
                <svg viewBox="0 0 24 24" className="h-5 w-5" xmlns="http://www.w3.org/2000/svg">
                  <path
                    fill="#4285F4"
                    d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z"
                  />
                </svg>
              </div>
              <div>
                <h4 className="text-foreground text-sm font-medium">Gmail</h4>
                <span
                  className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${
                    gmailConnected ? 'text-switch-on' : 'text-muted-foreground'
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      gmailConnected ? 'bg-switch-on' : 'bg-muted-foreground/60'
                    }`}
                  />
                  {gmailConnected ? '연결됨' : '미연결'}
                </span>
              </div>
            </div>
            <button
              onClick={gmailConnected ? handleGmailDisconnect : handleGmailConnect}
              disabled={gmailLoading}
              className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 ${
                gmailConnected
                  ? 'border-border bg-background text-foreground hover:bg-muted'
                  : 'border-foreground bg-foreground text-background hover:bg-foreground/90'
              }`}
            >
              {gmailLoading ? '연결 중...' : gmailConnected ? '연결 해제' : '연결하기'}
            </button>
          </div>
        </div>

        <div
          className={`rounded-xl border p-4 transition-colors ${
            mattermostConnected ? 'bg-muted/40 border-border' : 'bg-background border-border'
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg">
                <img
                  src="/assets/integrations/mattermost.jpg"
                  alt="Mattermost"
                  className="h-10 w-10 scale-[1.55] object-cover"
                />
              </div>
              <div className="min-w-0">
                <h4 className="text-foreground text-sm font-medium">Mattermost</h4>
                <span
                  className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${
                    mattermostConnected ? 'text-switch-on' : 'text-muted-foreground'
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      mattermostConnected ? 'bg-switch-on' : 'bg-muted-foreground/60'
                    }`}
                  />
                  {mattermostLoading
                    ? '확인 중'
                    : mattermostConnected
                      ? `${mattermostChannels.length}개 채널 연결됨`
                      : '미연결'}
                </span>
                {defaultMattermostChannel && (
                  <p className="text-muted-foreground mt-1 truncate text-xs">
                    기본 채널: {defaultMattermostChannel.alias}
                  </p>
                )}
              </div>
            </div>
            <button
              onClick={() => setMattermostSettingsOpen((open) => !open)}
              className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                mattermostSettingsOpen
                  ? 'border-border bg-background text-foreground hover:bg-muted'
                  : 'border-foreground bg-foreground text-background hover:bg-foreground/90'
              }`}
            >
              {mattermostSettingsOpen ? '닫기' : mattermostConnected ? '관리하기' : '연결하기'}
            </button>
          </div>
        </div>

        {mattermostSettingsOpen && (
          <ChannelsContent embedded onChannelsChange={handleMattermostChannelsChange} />
        )}
      </div>
    </div>
  )
}
