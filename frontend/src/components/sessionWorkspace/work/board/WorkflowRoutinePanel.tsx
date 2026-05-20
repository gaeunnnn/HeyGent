import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowUpDown,
  Check,
  ChevronRight,
  Layers,
  Loader2,
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Repeat,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { listWorkflowTemplates, type WorkflowTemplate } from '@/apis/workflowTemplates'
import { PageTabBar } from '@/components/PageTabBar'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { buildWorkflowAssignees } from './workflowAssignees'
import {
  createWorkflowRoutineSchedule,
  formatWorkflowRoutineLastRunLabel,
  formatWorkflowRoutineScheduleLabel,
  markWorkflowRoutineRan,
  readWorkflowRoutineSchedules,
  removeWorkflowRoutineSchedule,
  updateWorkflowRoutineSchedule,
  upsertWorkflowRoutineSchedule,
  WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT,
  writeWorkflowRoutineSchedules,
  type WorkflowRoutineSchedule,
} from './workflowRoutineSchedule'
import {
  describeWorkflowRoutineSchedule,
  WorkflowRoutineScheduleEditor,
} from './WorkflowRoutineScheduleEditor'
import { runWorkflowTemplate } from './workflowTemplateRunner'

type RoutineTab = 'routines' | 'runs'
type RoutineGroupBy = 'none' | 'workflow' | 'status'
type RoutineSortField = 'scheduled' | 'created' | 'lastRun' | 'title'
type RoutineSortDir = 'asc' | 'desc'

type RoutineViewState = {
  collapsedGroups: string[]
  groupBy: RoutineGroupBy
  sortDir: RoutineSortDir
  sortField: RoutineSortField
}

const EMPTY_AGENT_PANELS: ReturnType<
  typeof useSessionStore.getState
>['agentPanelsBySessionId'][string] = []
const DEFAULT_CRON_EXPRESSION = '0 10 * * *'
const DEFAULT_VIEW_STATE: RoutineViewState = {
  collapsedGroups: [],
  groupBy: 'none',
  sortDir: 'asc',
  sortField: 'scheduled',
}

export function WorkflowRoutinePanel({ sessionId }: { sessionId: string }) {
  const agentPanelsBySessionId = useSessionStore((state) => state.agentPanelsBySessionId)
  const sendChatMessage = useChatStore((state) => state.sendMessage)
  const assignees = useMemo(
    () => buildWorkflowAssignees(agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS),
    [agentPanelsBySessionId, sessionId],
  )
  const titleInputRef = useRef<HTMLTextAreaElement | null>(null)
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [schedules, setSchedules] = useState<WorkflowRoutineSchedule[]>(() =>
    readWorkflowRoutineSchedules(sessionId),
  )
  const [activeTab, setActiveTab] = useState<RoutineTab>('routines')
  const [composerOpen, setComposerOpen] = useState(false)
  const [editingScheduleId, setEditingScheduleId] = useState<string | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [routineTitle, setRoutineTitle] = useState('')
  const [triggerKind, setTriggerKind] = useState<'once' | 'schedule'>('once')
  const [scheduledDate, setScheduledDate] = useState(() => getDefaultScheduledDate())
  const [scheduledTime, setScheduledTime] = useState(() => getDefaultScheduledTime())
  const [cronExpression, setCronExpression] = useState(DEFAULT_CRON_EXPRESSION)
  const [loadingTemplates, setLoadingTemplates] = useState(true)
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null)
  const [viewState, setViewState] = useState<RoutineViewState>(DEFAULT_VIEW_STATE)

  const selectedTemplate = templates.find((template) => template.templateId === selectedTemplateId)

  const refreshSchedules = useCallback(() => {
    setSchedules(readWorkflowRoutineSchedules(sessionId))
  }, [sessionId])

  const refreshTemplates = useCallback(
    async (showLoading = true) => {
      if (showLoading) setLoadingTemplates(true)
      try {
        const response = await listWorkflowTemplates(sessionId)
        setTemplates(response.items)
        setSelectedTemplateId((current) => current || response.items[0]?.templateId || '')
      } catch (error) {
        console.error(error)
        toast.error('워크플로우 목록을 불러오지 못했습니다')
      } finally {
        setLoadingTemplates(false)
      }
    },
    [sessionId],
  )

  useEffect(() => {
    queueMicrotask(() => {
      void refreshTemplates(false)
    })
  }, [refreshTemplates])

  useEffect(() => {
    const handleSchedulesChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string }>).detail
      if (detail?.sessionId === sessionId) {
        refreshSchedules()
      }
    }
    window.addEventListener(WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT, handleSchedulesChanged)
    return () => {
      window.removeEventListener(WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT, handleSchedulesChanged)
    }
  }, [refreshSchedules, sessionId])

  useEffect(() => {
    autoResizeTextarea(titleInputRef.current)
  }, [routineTitle, composerOpen])

  const sortedSchedules = useMemo(
    () => sortSchedules(schedules, viewState.sortField, viewState.sortDir),
    [schedules, viewState.sortDir, viewState.sortField],
  )
  const routineGroups = useMemo(
    () => buildRoutineGroups(sortedSchedules, viewState.groupBy),
    [sortedSchedules, viewState.groupBy],
  )
  const recentRuns = useMemo(
    () =>
      schedules
        .filter((schedule) => schedule.lastRunAt !== null)
        .sort((a, b) => timestampValue(b.lastRunAt) - timestampValue(a.lastRunAt)),
    [schedules],
  )

  const updateRoutineView = (patch: Partial<RoutineViewState>) => {
    setViewState((current) => ({ ...current, ...patch }))
  }

  const openComposer = () => {
    const firstTemplate = templates[0]
    setEditingScheduleId(null)
    setSelectedTemplateId(firstTemplate?.templateId ?? '')
    setRoutineTitle(firstTemplate?.name ?? '')
    setTriggerKind('once')
    setScheduledDate(getDefaultScheduledDate())
    setScheduledTime(getDefaultScheduledTime())
    setCronExpression(DEFAULT_CRON_EXPRESSION)
    setComposerOpen(true)
  }

  const openEditComposer = (schedule: WorkflowRoutineSchedule) => {
    const [date = getDefaultScheduledDate(), time = getDefaultScheduledTime()] =
      schedule.scheduledAt.split('T')
    setEditingScheduleId(schedule.id)
    setSelectedTemplateId(schedule.templateId)
    setRoutineTitle(schedule.templateName)
    setTriggerKind(schedule.triggerKind)
    setScheduledDate(date)
    setScheduledTime(time)
    setCronExpression(schedule.cronExpression ?? DEFAULT_CRON_EXPRESSION)
    setComposerOpen(true)
  }

  const handleSaveRoutine = () => {
    const template = templates.find((item) => item.templateId === selectedTemplateId)
    if (!template) {
      toast.warning('불러올 워크플로우를 선택하세요')
      return
    }
    if (scheduledDate === '' || scheduledTime === '') {
      toast.warning('시작 날짜와 시간을 입력하세요')
      return
    }
    const title = routineTitle.trim() || template.name
    const schedule = createWorkflowRoutineSchedule({
      cronExpression: triggerKind === 'schedule' ? cronExpression : null,
      scheduledAt: `${scheduledDate}T${scheduledTime}`,
      sessionId,
      templateId: template.templateId,
      templateName: title,
      triggerKind,
    })
    const existing = editingScheduleId
      ? (schedules.find((item) => item.id === editingScheduleId) ?? null)
      : null
    const scheduleChanged =
      existing !== null &&
      (existing.templateId !== schedule.templateId ||
        existing.scheduledAt !== schedule.scheduledAt ||
        existing.triggerKind !== schedule.triggerKind ||
        existing.cronExpression !== schedule.cronExpression)
    const nextSchedule =
      existing === null
        ? schedule
        : {
            ...schedule,
            createdAt: existing.createdAt,
            enabled: scheduleChanged ? true : existing.enabled,
            lastRunAt: scheduleChanged ? null : existing.lastRunAt,
          }
    const baseSchedules = editingScheduleId
      ? schedules.filter((item) => item.id !== editingScheduleId)
      : schedules
    const next = upsertWorkflowRoutineSchedule(baseSchedules, nextSchedule)
    setSchedules(next)
    writeWorkflowRoutineSchedules(sessionId, next)
    setComposerOpen(false)
    setEditingScheduleId(null)
    toast.success(
      existing === null ? '워크플로우를 루틴으로 불러왔습니다' : '워크플로우 루틴을 수정했습니다',
    )
  }

  const handleToggle = (schedule: WorkflowRoutineSchedule) => {
    const next = updateWorkflowRoutineSchedule(schedules, schedule.id, {
      enabled: !schedule.enabled,
      lastRunAt: !schedule.enabled && schedule.triggerKind === 'once' ? null : schedule.lastRunAt,
    })
    setSchedules(next)
    writeWorkflowRoutineSchedules(sessionId, next)
  }

  const handleRemove = (scheduleId: string) => {
    const next = removeWorkflowRoutineSchedule(schedules, scheduleId)
    setSchedules(next)
    writeWorkflowRoutineSchedules(sessionId, next)
  }

  const handleRunNow = async (schedule: WorkflowRoutineSchedule) => {
    const template = templates.find((item) => item.templateId === schedule.templateId)
    if (!template) {
      toast.warning('연결된 워크플로우를 찾지 못했습니다')
      return
    }
    setRunningScheduleId(schedule.id)
    try {
      const result = await runWorkflowTemplate({
        assignees,
        sendChatMessage,
        sessionId,
        template,
      })
      if (!result.chatSent) {
        console.error('sendChatMessage failed', result.chatError)
        toast.warning('작업은 생성됐지만 채팅 메시지 전송은 실패했습니다')
      } else {
        toast.success(`"${schedule.templateName}" 루틴을 실행했습니다`)
      }
      const next = schedules.map((item) =>
        item.id === schedule.id ? markWorkflowRoutineRan(item) : item,
      )
      setSchedules(next)
      writeWorkflowRoutineSchedules(sessionId, next)
    } catch (error) {
      console.error(error)
      toast.error('루틴 실행에 실패했습니다')
    } finally {
      setRunningScheduleId(null)
    }
  }

  return (
    <div className="bg-background h-full min-h-0 overflow-y-auto">
      <main className="min-h-full p-6">
        <div className="w-full space-y-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight">루틴</h1>
              <p className="text-muted-foreground text-sm">
                워크플로우를 불러와 한 번 실행하거나 반복 실행되도록 예약합니다.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => void refreshTemplates()}>
                {loadingTemplates ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                새로고침
              </Button>
              <Button onClick={openComposer} disabled={loadingTemplates || templates.length === 0}>
                <Plus className="h-4 w-4" />
                워크플로우 불러오기
              </Button>
            </div>
          </div>

          <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as RoutineTab)}>
            <PageTabBar
              align="start"
              value={activeTab}
              onValueChange={(value) => setActiveTab(value as RoutineTab)}
              items={[
                { value: 'routines', label: '루틴' },
                { value: 'runs', label: '최근 실행' },
              ]}
            />
            <TabsContent value="routines" className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-muted-foreground text-sm">{schedules.length}개 루틴</p>
                <div className="flex items-center gap-1">
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button variant="ghost" size="sm" className="text-xs" title="정렬">
                        <ArrowUpDown className="h-3.5 w-3.5 sm:mr-1 sm:h-3 sm:w-3" />
                        <span className="hidden sm:inline">정렬</span>
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-44 p-0">
                      <div className="space-y-0.5 p-2">
                        {(
                          [
                            ['scheduled', '예약 시간'],
                            ['created', '생성일'],
                            ['lastRun', '마지막 실행'],
                            ['title', '이름'],
                          ] as const
                        ).map(([field, label]) => (
                          <button
                            key={field}
                            className={`flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm ${
                              viewState.sortField === field
                                ? 'bg-accent/50 text-foreground'
                                : 'text-muted-foreground hover:bg-accent/50'
                            }`}
                            onClick={() => {
                              updateRoutineView(
                                viewState.sortField === field
                                  ? { sortDir: viewState.sortDir === 'asc' ? 'desc' : 'asc' }
                                  : {
                                      sortDir: field === 'title' ? 'asc' : 'desc',
                                      sortField: field,
                                    },
                              )
                            }}
                          >
                            <span>{label}</span>
                            {viewState.sortField === field ? (
                              <span className="text-muted-foreground text-xs">
                                {viewState.sortDir === 'asc' ? 'Asc' : 'Desc'}
                              </span>
                            ) : null}
                          </button>
                        ))}
                      </div>
                    </PopoverContent>
                  </Popover>
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button variant="ghost" size="sm" className="text-xs" title="그룹">
                        <Layers className="h-3.5 w-3.5 sm:mr-1 sm:h-3 sm:w-3" />
                        <span className="hidden sm:inline">그룹</span>
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-44 p-0">
                      <div className="space-y-0.5 p-2">
                        {(
                          [
                            ['workflow', '워크플로우'],
                            ['status', '상태'],
                            ['none', '없음'],
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            className={`flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm ${
                              viewState.groupBy === value
                                ? 'bg-accent/50 text-foreground'
                                : 'text-muted-foreground hover:bg-accent/50'
                            }`}
                            onClick={() =>
                              updateRoutineView({ collapsedGroups: [], groupBy: value })
                            }
                          >
                            <span>{label}</span>
                            {viewState.groupBy === value ? <Check className="h-3.5 w-3.5" /> : null}
                          </button>
                        ))}
                      </div>
                    </PopoverContent>
                  </Popover>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="runs" className="space-y-4">
              <p className="text-muted-foreground text-sm">{recentRuns.length}개 실행 기록</p>
            </TabsContent>
          </Tabs>

          {activeTab === 'routines' ? (
            schedules.length === 0 ? (
              <div className="py-12">
                <EmptyRoutineState />
              </div>
            ) : (
              <div className="border-border rounded-lg border">
                {routineGroups.map((group) => (
                  <Collapsible
                    key={group.key}
                    open={!viewState.collapsedGroups.includes(group.key)}
                    onOpenChange={(open) => {
                      updateRoutineView({
                        collapsedGroups: open
                          ? viewState.collapsedGroups.filter((item) => item !== group.key)
                          : [...viewState.collapsedGroups, group.key],
                      })
                    }}
                  >
                    {group.label ? (
                      <div className="border-border flex items-center gap-2 border-b px-3 py-2">
                        <CollapsibleTrigger className="flex items-center gap-1.5">
                          <ChevronRight className="text-muted-foreground h-3.5 w-3.5 shrink-0 transition-transform [[data-state=open]>&]:rotate-90" />
                          <span className="text-sm font-semibold tracking-wide uppercase">
                            {group.label}
                          </span>
                        </CollapsibleTrigger>
                        <span className="text-muted-foreground text-xs">{group.items.length}</span>
                      </div>
                    ) : null}
                    <CollapsibleContent>
                      {group.items.map((schedule) => (
                        <WorkflowRoutineRow
                          key={schedule.id}
                          schedule={schedule}
                          runningScheduleId={runningScheduleId}
                          onRemove={handleRemove}
                          onEdit={openEditComposer}
                          onRunNow={(item) => void handleRunNow(item)}
                          onToggleEnabled={handleToggle}
                        />
                      ))}
                    </CollapsibleContent>
                  </Collapsible>
                ))}
              </div>
            )
          ) : (
            <div className="border-border rounded-lg border">
              {recentRuns.length === 0 ? (
                <div className="text-muted-foreground px-3 py-8 text-center text-sm">
                  아직 실행된 루틴이 없습니다.
                </div>
              ) : (
                recentRuns.map((schedule) => (
                  <WorkflowRoutineRow
                    key={schedule.id}
                    schedule={schedule}
                    runningScheduleId={runningScheduleId}
                    onRemove={handleRemove}
                    onEdit={openEditComposer}
                    onRunNow={(item) => void handleRunNow(item)}
                    onToggleEnabled={handleToggle}
                  />
                ))
              )}
            </div>
          )}
        </div>
      </main>

      <Dialog
        open={composerOpen}
        onOpenChange={(open) => {
          setComposerOpen(open)
          if (!open) setEditingScheduleId(null)
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="flex max-h-[calc(100dvh-2rem)] max-w-3xl flex-col gap-0 overflow-hidden p-0"
        >
          <div className="border-border/60 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
            <div>
              <p className="text-muted-foreground text-xs font-medium tracking-[0.2em] uppercase">
                {editingScheduleId ? '루틴 편집' : '새 루틴'}
              </p>
              <p className="text-muted-foreground text-sm">
                불러올 워크플로우와 트리거를 먼저 정합니다.
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setComposerOpen(false)}>
              취소
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="px-5 pt-5 pb-3">
              <textarea
                ref={titleInputRef}
                className="placeholder:text-muted-foreground/50 w-full resize-none overflow-hidden bg-transparent text-xl font-semibold outline-none"
                placeholder="루틴 이름"
                rows={1}
                value={routineTitle}
                onChange={(event) => {
                  setRoutineTitle(event.target.value)
                  autoResizeTextarea(event.target)
                }}
                autoFocus
              />
            </div>

            <div className="px-5 pb-3">
              <div className="overflow-x-auto overscroll-x-contain">
                <div className="inline-flex min-w-full flex-wrap items-center gap-2 text-sm sm:min-w-max sm:flex-nowrap">
                  <span className="text-muted-foreground">불러올 워크플로우</span>
                  <select
                    value={selectedTemplateId}
                    onChange={(event) => {
                      const template = templates.find(
                        (item) => item.templateId === event.target.value,
                      )
                      setSelectedTemplateId(event.target.value)
                      setRoutineTitle((current) => current || template?.name || '')
                    }}
                    className="border-border bg-background text-foreground h-8 min-w-48 rounded-md border px-2 text-sm outline-none"
                  >
                    {templates.map((template) => (
                      <option key={template.templateId} value={template.templateId}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                  <span className="text-muted-foreground">실행</span>
                  <select
                    value={triggerKind}
                    onChange={(event) => setTriggerKind(event.target.value as 'once' | 'schedule')}
                    className="border-border bg-background text-foreground h-8 rounded-md border px-2 text-sm outline-none"
                  >
                    <option value="once">한 번</option>
                    <option value="schedule">반복</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="border-border/60 border-t px-5 py-4">
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-muted-foreground text-xs font-medium tracking-[0.18em] uppercase">
                    시작 날짜
                  </span>
                  <input
                    type="date"
                    value={scheduledDate}
                    onChange={(event) => setScheduledDate(event.target.value)}
                    className="border-border bg-background text-foreground h-10 w-full rounded-md border px-3 text-sm outline-none"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-muted-foreground text-xs font-medium tracking-[0.18em] uppercase">
                    시작 시간
                  </span>
                  <input
                    type="time"
                    value={scheduledTime}
                    onChange={(event) => setScheduledTime(event.target.value)}
                    className="border-border bg-background text-foreground h-10 w-full rounded-md border px-3 text-sm outline-none"
                  />
                </label>
              </div>
            </div>

            {triggerKind === 'schedule' ? (
              <div className="border-border/60 border-t px-5 py-4">
                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-medium">반복 설정</p>
                    <p className="text-muted-foreground text-sm">
                      시작 시각 이후부터 선택한 주기로 실행합니다.
                    </p>
                  </div>
                  <WorkflowRoutineScheduleEditor
                    value={cronExpression}
                    onChange={setCronExpression}
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="border-border/60 flex shrink-0 flex-col gap-3 border-t px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-muted-foreground text-sm">
              {triggerKind === 'schedule'
                ? describeWorkflowRoutineSchedule(cronExpression)
                : `${scheduledDate} ${scheduledTime}에 한 번 실행`}
            </div>
            <Button
              onClick={handleSaveRoutine}
              disabled={!routineTitle.trim() || !selectedTemplate}
            >
              <Plus className="h-4 w-4" />
              {editingScheduleId ? '저장' : '불러오기'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function WorkflowRoutineRow({
  schedule,
  runningScheduleId,
  onRemove,
  onEdit,
  onRunNow,
  onToggleEnabled,
}: {
  schedule: WorkflowRoutineSchedule
  runningScheduleId: string | null
  onRemove: (scheduleId: string) => void
  onEdit: (schedule: WorkflowRoutineSchedule) => void
  onRunNow: (schedule: WorkflowRoutineSchedule) => void
  onToggleEnabled: (schedule: WorkflowRoutineSchedule) => void
}) {
  const enabled = schedule.enabled
  const isRunning = runningScheduleId === schedule.id
  const status = getScheduleStatus(schedule)
  return (
    <div className="border-border hover:bg-accent/50 flex flex-col gap-3 border-b px-3 py-3 transition-colors last:border-b-0 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">{schedule.templateName}</span>
          {status !== 'active' ? (
            <span className="text-muted-foreground text-xs">{getScheduleStatusLabel(status)}</span>
          ) : null}
        </div>
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm bg-slate-500" />
            <span>{schedule.triggerKind === 'schedule' ? '반복' : '한 번'}</span>
          </span>
          <span>
            {schedule.triggerKind === 'schedule'
              ? describeWorkflowRoutineSchedule(schedule.cronExpression ?? '')
              : formatWorkflowRoutineScheduleLabel(schedule.scheduledAt)}
          </span>
          <span>시작 {formatWorkflowRoutineScheduleLabel(schedule.scheduledAt)}</span>
          <span>마지막 실행 {formatWorkflowRoutineLastRunLabel(schedule.lastRunAt)}</span>
        </div>
      </div>

      <div
        className="flex items-center gap-3"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
        }}
      >
        <Button variant="outline" size="sm" onClick={() => onRunNow(schedule)} disabled={isRunning}>
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          {isRunning ? '실행 중' : '지금 실행'}
        </Button>

        <div className="flex items-center gap-3">
          <Switch
            checked={enabled}
            onCheckedChange={() => onToggleEnabled(schedule)}
            aria-label={enabled ? `${schedule.templateName} 끄기` : `${schedule.templateName} 켜기`}
          />
          <span className="text-muted-foreground w-8 text-xs">{enabled ? 'On' : 'Off'}</span>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`${schedule.templateName} 더보기`}>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onEdit(schedule)}>
              <Pencil className="h-4 w-4" />
              편집
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onToggleEnabled(schedule)}>
              {enabled ? '끄기' : '켜기'}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => onRemove(schedule.id)}>
              <Trash2 className="h-4 w-4" />
              삭제
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}

function EmptyRoutineState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 text-center">
      <div className="bg-muted text-muted-foreground flex h-12 w-12 items-center justify-center rounded-lg">
        <Repeat className="h-6 w-6" />
      </div>
      <p className="text-muted-foreground text-sm">
        아직 루틴이 없습니다. 워크플로우 불러오기로 첫 예약을 추가하세요.
      </p>
    </div>
  )
}

function buildRoutineGroups(schedules: WorkflowRoutineSchedule[], groupBy: RoutineGroupBy) {
  if (groupBy === 'none') return [{ key: '__all', label: null, items: schedules }]
  const groups = new Map<string, WorkflowRoutineSchedule[]>()
  schedules.forEach((schedule) => {
    const key =
      groupBy === 'workflow'
        ? schedule.templateName
        : getScheduleStatusLabel(getScheduleStatus(schedule))
    groups.set(key, [...(groups.get(key) ?? []), schedule])
  })
  return [...groups.entries()].map(([key, items]) => ({ key, label: key, items }))
}

function sortSchedules(
  schedules: WorkflowRoutineSchedule[],
  sortField: RoutineSortField,
  sortDir: RoutineSortDir,
) {
  const direction = sortDir === 'asc' ? 1 : -1
  return [...schedules].sort((left, right) => {
    let result = 0
    if (sortField === 'title') {
      result = left.templateName.localeCompare(right.templateName)
    } else if (sortField === 'created') {
      result = timestampValue(left.createdAt) - timestampValue(right.createdAt)
    } else if (sortField === 'lastRun') {
      result = timestampValue(left.lastRunAt) - timestampValue(right.lastRunAt)
    } else {
      result = left.scheduledAt.localeCompare(right.scheduledAt)
    }
    return result === 0 ? left.templateName.localeCompare(right.templateName) : result * direction
  })
}

function getScheduleStatus(schedule: WorkflowRoutineSchedule) {
  if (schedule.triggerKind === 'once' && schedule.lastRunAt !== null) return 'completed'
  return schedule.enabled ? 'active' : 'paused'
}

function getScheduleStatusLabel(status: string) {
  if (status === 'completed') return '완료'
  if (status === 'paused') return '일시정지'
  return '활성'
}

function timestampValue(value: string | null | undefined) {
  if (!value) return Number.NEGATIVE_INFINITY
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY
}

function getDefaultScheduledDate() {
  const date = new Date()
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-')
}

function getDefaultScheduledTime() {
  const date = new Date()
  date.setMinutes(date.getMinutes() + 10)
  return [
    String(date.getHours()).padStart(2, '0'),
    String(date.getMinutes()).padStart(2, '0'),
  ].join(':')
}

function autoResizeTextarea(element: HTMLTextAreaElement | null) {
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${element.scrollHeight}px`
}
