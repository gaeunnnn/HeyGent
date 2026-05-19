import { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, Clock, FileText, Loader2, MoreHorizontal, Trash2 } from 'lucide-react'
import { PageTabBar } from '@/components/PageTabBar'
import {
  AgentConfigurationPanel,
  AgentDashboardPanel,
  AgentDetailHeader,
  AgentRunActivityChart,
  AgentRunStatusChart,
  AgentRunSuccessRateChart,
  AgentUsageActivityChart,
  AgentInstructionsBundlePanel,
  AgentInstructionsPanel,
  AgentSkillsLibraryPanel,
  AgentSkillsPanel,
} from '@/components/sessionWorkspace/AgentDetailPanels'
import { AgentRunsPanel } from '@/components/sessionWorkspace/agentRuns/AgentRunsPanel'
import {
  buildAgentRunUsageMap,
  buildAgentUsageSummaryItems,
  buildAgentUsageRows,
  buildUsageSummaryFromRecords,
  filterUsageRecordsByTaskRunIds,
  formatAgentRunCostUsage,
  formatAgentRunTokenUsage,
} from '@/components/sessionWorkspace/agentUsageDisplay'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tabs } from '@/components/ui/tabs'
import { getCommandUsage, type CommandUsageRecord } from '@/apis/aiCommandUsage'
import {
  deleteCustomSkill,
  getUserSkillDetail,
  type SkillCatalogDetail,
  type SkillCatalogItem,
} from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { listTaskRuns } from '@/apis/taskRuns'
import {
  getCachedTaskRuns,
  getCachedUsageRecords,
  setCachedTaskRuns,
  setCachedUsageRecords,
} from '@/components/sessionWorkspace/sessionWorkspaceDashboardCache'
import type { AgentPanelItem } from '@/store/useSessionStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import type { Agent } from '@/types/agent'
import type { RawTaskEventPayload } from '@/realtime/aiRealtimeTypes'
import type { RawTaskRun, TaskRunAgentRef } from '@/types/taskRuns'
import { isInternalStepAnchorEvent, toTaskRunSummaryView } from '@/utils/taskRunStatusView'
import { getTime } from '@/components/taskRuns/stepRunActivityPanel/activityPanelText'
import { AgentSkillDetailDialog } from '@/components/sessionWorkspace/AgentSkillDetailDialog'
import { SubAgentDraftForm } from './SubAgentDraftForm'
import { SubAgentProfileImage } from './SubAgentProfileImage'

type SubAgentDetailTab = 'dashboard' | 'instructions' | 'skills' | 'configuration' | 'runs'

const DETAIL_TABS: Array<{ value: SubAgentDetailTab; label: string }> = [
  { value: 'dashboard', label: '대시보드' },
  { value: 'instructions', label: '지침' },
  { value: 'skills', label: '스킬' },
  { value: 'configuration', label: '설정' },
  { value: 'runs', label: '실행 기록' },
]

export function SubAgentDetailView({
  item,
  onDelete,
  onSave,
  onTabChange,
  reservedNames,
  requestedTab,
  sessionId,
}: {
  item: AgentPanelItem
  onDelete: () => Promise<void>
  onSave: (agent: Agent) => Agent | Promise<Agent | void> | void
  onTabChange?: (tab: SubAgentDetailTab) => void
  requestedTab?: string | null
  reservedNames: string[]
  sessionId: string
}) {
  const authenticatedReady = useAiRealtimeStore((state) => state.authenticatedReady)
  const commandClient = useAiRealtimeStore((state) => state.commandClient)
  const taskRunsById = useTaskRunStore((state) => state.taskRunsById)
  const eventsByTaskRunId = useTaskRunStore((state) => state.eventsByTaskRunId)
  const fetchActiveTaskRuns = useTaskRunStore((state) => state.fetchActiveTaskRuns)
  const [tab, setTab] = useState<SubAgentDetailTab>(getDetailTab(requestedTab))
  const [loadedTaskRuns, setLoadedTaskRuns] = useState<RawTaskRun[]>(
    () => getCachedTaskRuns(sessionId) ?? [],
  )
  const [instructionsDraft, setInstructionsDraft] = useState(item.agent.instructions ?? '')
  const [instructionsEntryFile, setInstructionsEntryFile] = useState(
    item.agent.instructionsEntryFile ?? 'AGENTS.md',
  )
  const [instructionsFiles, setInstructionsFiles] = useState(item.agent.instructionsFiles ?? {})
  const [instructionsMode, setInstructionsMode] = useState<'managed' | 'external'>(
    item.agent.instructionsMode ?? 'managed',
  )
  const [instructionsRootPath, setInstructionsRootPath] = useState(
    item.agent.instructionsRootPath ?? '',
  )
  const [skillSaving, setSkillSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [usageRecords, setUsageRecords] = useState<CommandUsageRecord[]>(
    () => getCachedUsageRecords(sessionId) ?? [],
  )
  const [usageError, setUsageError] = useState<string | null>(null)
  const [skillCatalog, setSkillCatalog] = useState<SkillCatalogItem[]>([])
  const [skillCatalogError, setSkillCatalogError] = useState<string | null>(null)
  const [skillDetail, setSkillDetail] = useState<SkillCatalogDetail | null>(null)
  const [skillDetailOpen, setSkillDetailOpen] = useState(false)
  const [skillDetailLoading, setSkillDetailLoading] = useState(false)
  const [skillDraftState, setSkillDraftState] = useState<{
    itemId: string
    skills: string[]
  }>(() => ({
    itemId: item.id,
    skills: item.agent.skills ?? [],
  }))
  const skillDraft =
    skillDraftState.itemId === item.id ? skillDraftState.skills : (item.agent.skills ?? [])
  const skillCatalogReady = skillCatalog.length > 0
  const knownSkillIds = new Set(skillCatalog.map((skill) => skill.skillId))
  const selectedKnownSkillIds = skillCatalogReady
    ? skillDraft.filter((skillId) => knownSkillIds.has(skillId))
    : skillDraft
  const missingSkillIds = skillCatalogReady
    ? skillDraft.filter((skillId) => !knownSkillIds.has(skillId))
    : []
  const orderedSkillCatalog = useMemo(
    () => orderSkillCatalogBySelectedIds(skillCatalog, selectedKnownSkillIds),
    [skillCatalog, selectedKnownSkillIds],
  )
  const profileId = item.agent.profileId ?? item.id
  const agentTaskRuns = useMemo(
    () => buildAgentTaskRuns(sessionId, profileId, loadedTaskRuns, taskRunsById),
    [loadedTaskRuns, profileId, sessionId, taskRunsById],
  )
  const runItems = useMemo(
    () => buildAgentRunItems(agentTaskRuns, eventsByTaskRunId, usageRecords),
    [agentTaskRuns, eventsByTaskRunId, usageRecords],
  )
  const latestRun = runItems[0] ?? null
  const agentUsageRecords = useMemo(
    () =>
      filterUsageRecordsByTaskRunIds(
        usageRecords,
        agentTaskRuns.map((taskRun) => taskRun.task_run_id),
      ),
    [agentTaskRuns, usageRecords],
  )
  const agentUsageSummary = useMemo(
    () => buildUsageSummaryFromRecords(agentUsageRecords),
    [agentUsageRecords],
  )
  const usageItems = useMemo(
    () => buildAgentUsageSummaryItems(agentUsageSummary, false, usageError),
    [agentUsageSummary, usageError],
  )
  const usageRows = useMemo(() => buildAgentUsageRows(agentUsageRecords), [agentUsageRecords])
  const instructionsDirty =
    instructionsDraft.trim() !== (item.agent.instructions ?? '') ||
    instructionsEntryFile.trim() !== (item.agent.instructionsEntryFile ?? 'AGENTS.md') ||
    !shallowStringRecordEqual(instructionsFiles, item.agent.instructionsFiles ?? {}) ||
    instructionsMode !== (item.agent.instructionsMode ?? 'managed') ||
    instructionsRootPath.trim() !== (item.agent.instructionsRootPath ?? '')
  const skillsDirty = !stringArraysEqual(skillDraft, item.agent.skills ?? [])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null || sessionId.startsWith('pending_session_')) {
      return
    }

    let alive = true
    void Promise.all([
      fetchActiveTaskRuns(sessionId),
      listTaskRuns({ sessionId, pageSize: 20, status: 'ALL' }),
    ])
      .then(([, taskRuns]) => {
        if (!alive) return
        setLoadedTaskRuns(taskRuns)
        setCachedTaskRuns(sessionId, taskRuns)
      })
      .catch((error) => {
        if (alive) console.error(error)
      })

    return () => {
      alive = false
    }
  }, [authenticatedReady, commandClient, fetchActiveTaskRuns, sessionId])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null || sessionId.startsWith('pending_session_')) {
      return
    }

    let alive = true
    void getCommandUsage({ sessionId })
      .then((result) => {
        if (!alive) return
        setUsageError(null)
        setUsageRecords(result.records)
        setCachedUsageRecords(sessionId, result.records)
      })
      .catch(() => {
        if (!alive) return
        setUsageError('사용량을 불러오지 못했습니다.')
      })

    return () => {
      alive = false
    }
  }, [authenticatedReady, commandClient, sessionId])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null) {
      return
    }

    let alive = true
    void useAgentCacheStore
      .getState()
      .fetchUserSkills()
      .then((items) => {
        if (!alive) return
        setSkillCatalog(items)
        setSkillCatalogError(null)
      })
      .catch(() => {
        if (alive) setSkillCatalogError('스킬 목록을 불러오지 못했습니다.')
      })

    return () => {
      alive = false
    }
  }, [authenticatedReady, commandClient])

  const selectTab = (nextTab: SubAgentDetailTab) => {
    setTab(nextTab)
    onTabChange?.(nextTab)
    setSaved(false)
  }

  const syncInstructionsDraft = (agent: Agent) => {
    setInstructionsDraft(agent.instructions ?? '')
    setInstructionsEntryFile(agent.instructionsEntryFile ?? 'AGENTS.md')
    setInstructionsFiles(agent.instructionsFiles ?? {})
    setInstructionsMode(agent.instructionsMode ?? 'managed')
    setInstructionsRootPath(agent.instructionsRootPath ?? '')
  }

  const resetInstructionsDraft = () => {
    syncInstructionsDraft(item.agent)
    setSaved(false)
  }

  const saveInstructionsDraft = () => {
    if (!instructionsDirty) return
    const result = onSave({
      ...item.agent,
      instructions: instructionsDraft.trim(),
      instructionsEntryFile: instructionsEntryFile.trim() || 'AGENTS.md',
      instructionsFiles,
      instructionsMode,
      instructionsRootPath: instructionsRootPath.trim(),
    })
    void Promise.resolve(result).then((savedAgent) => {
      if (savedAgent !== undefined) {
        syncInstructionsDraft(savedAgent)
      }
      setSaved(true)
      window.setTimeout(() => setSaved(false), 1400)
    })
  }

  const toggleSkill = (skillId: string, checked: boolean) => {
    const catalogItem = skillCatalog.find((skill) => skill.skillId === skillId)
    if (catalogItem && !catalogItem.enabled) return
    const nextSkills = checked
      ? Array.from(new Set([...skillDraft, skillId]))
      : skillDraft.filter((id) => id !== skillId)
    setSkillDraftState({ itemId: item.id, skills: nextSkills })
    setSaved(false)
  }

  const saveSkillDraft = () => {
    if (!skillsDirty) return
    setSkillSaving(true)
    onSave({ ...item.agent, skills: selectedKnownSkillIds })
    setSaved(true)
    window.setTimeout(() => {
      setSkillSaving(false)
      setSaved(false)
    }, 800)
  }

  const resetSkillDraft = () => {
    setSkillDraftState({ itemId: item.id, skills: item.agent.skills ?? [] })
    setSaved(false)
  }

  const openSkillDetail = (skillId: string) => {
    setSkillDetailOpen(true)
    setSkillDetailLoading(true)
    void getUserSkillDetail(skillId)
      .then((detail) => {
        setSkillDetail(detail)
      })
      .catch(() => {
        setSkillCatalogError('스킬 상세를 불러오지 못했습니다.')
      })
      .finally(() => setSkillDetailLoading(false))
  }

  const handleSkillDeleted = async (detail: SkillCatalogDetail) => {
    await deleteCustomSkill(detail.skillId)
    setSkillCatalog((current) => current.filter((skill) => skill.skillId !== detail.skillId))
    setSkillDraftState({
      itemId: item.id,
      skills: skillDraft.filter((skillId) => skillId !== detail.skillId),
    })
    setSkillDetail(null)
    useAgentCacheStore.getState().invalidateUserSkills()
    setSaved(false)
  }

  const handleDelete = async () => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDelete()
      setDeleteDialogOpen(false)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : '에이전트를 삭제하지 못했습니다.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className={`space-y-6 ${instructionsDirty || skillsDirty ? 'pb-24 sm:pb-0' : ''}`}>
      <AgentDetailHeader
        actionsMenu={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-xs" aria-label="에이전트 메뉴">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                variant="destructive"
                onSelect={(event) => {
                  event.preventDefault()
                  setDeleteDialogOpen(true)
                }}
              >
                <Trash2 className="h-4 w-4" />
                삭제
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        }
        name={item.agent.name}
        status="초안"
        subtitle={
          <>
            {item.agent.role ?? 'general'}
            {item.agent.title ? ` · ${item.agent.title}` : ''}
          </>
        }
        profile={
          <button
            type="button"
            onClick={() => selectTab('configuration')}
            className="rounded-lg transition-opacity hover:opacity-80"
            aria-label="서브 에이전트 프로필 설정 열기"
          >
            <SubAgentProfileImage
              accent={item.agent.accent}
              profileImage={item.agent.profileImage}
              spriteId={item.agent.spriteId}
              size="large"
            />
          </button>
        }
        savedIndicator={
          saved ? <span className="text-xs font-medium text-emerald-600">저장됨</span> : undefined
        }
      />

      <Tabs value={tab} onValueChange={(next) => selectTab(next as SubAgentDetailTab)}>
        <PageTabBar
          align="start"
          items={DETAIL_TABS}
          value={tab}
          onValueChange={(next) => selectTab(next as SubAgentDetailTab)}
        />
      </Tabs>

      {tab === 'dashboard' && (
        <AgentDashboardPanel
          costs={usageItems}
          latestRun={latestRun}
          metrics={[
            {
              icon: Activity,
              label: '실행 활동',
              value: `${runItems.length}회`,
              description: '최근 14일',
              chart: <AgentRunActivityChart runs={runItems} />,
            },
            {
              icon: FileText,
              label: '담당 작업',
              value: `${agentTaskRuns.length}개`,
              description: '최근 14일',
              chart: <AgentRunStatusChart runs={runItems} />,
            },
            {
              icon: BarChart3,
              label: '토큰 사용',
              value: agentUsageSummary.totalTokens.toLocaleString('ko-KR'),
              description: '최근 14일',
              chart: <AgentUsageActivityChart records={agentUsageRecords} />,
            },
            {
              icon: Clock,
              label: '성공률',
              value: getRunSuccessRateLabel(runItems),
              description: '최근 14일',
              chart: <AgentRunSuccessRateChart runs={runItems} />,
            },
          ]}
          recentTitle="최근 작업"
          recentEmptyText="최근 작업이 없습니다."
          recentItems={runItems.map((run) => ({
            label: run.summary ?? run.id,
            onSelect: () => selectTab('runs'),
            value: `${formatRunStatus(run.status)}${run.createdAt ? ` · ${run.createdAt}` : ''}`,
          }))}
          onLatestRunOpen={() => selectTab('runs')}
          onRecentOpen={() => selectTab('runs')}
          usageRows={usageRows}
        />
      )}

      <div className={tab === 'configuration' ? '' : 'hidden'}>
        <AgentConfigurationPanel>
          <SubAgentDraftForm
            key={item.id}
            initialAgent={item.agent}
            onCancel={() => selectTab('dashboard')}
            onSave={onSave}
            reservedNames={reservedNames}
          />
        </AgentConfigurationPanel>
      </div>

      <div className={tab === 'instructions' ? '' : 'hidden'}>
        <AgentInstructionsPanel>
          <AgentInstructionsBundlePanel
            content={instructionsDraft}
            entryFile={instructionsEntryFile}
            files={instructionsFiles}
            mode={instructionsMode}
            rootPath={instructionsRootPath}
            onContentChange={(value) => {
              setInstructionsDraft(value)
              setSaved(false)
            }}
            onEntryFileChange={(value) => {
              setInstructionsEntryFile(value)
              setSaved(false)
            }}
            onFilesChange={(value) => {
              setInstructionsFiles(value)
              setSaved(false)
            }}
            onModeChange={(value) => {
              setInstructionsMode(value)
              setSaved(false)
            }}
            onRootPathChange={(value) => {
              setInstructionsRootPath(value)
              setSaved(false)
            }}
          />
        </AgentInstructionsPanel>
      </div>

      {tab === 'skills' && (
        <AgentSkillsPanel>
          <AgentSkillsLibraryPanel
            adapterLabel={item.agent.adapterType ?? 'local'}
            applicationLabel="에이전트 실행 시 적용"
            rows={orderedSkillCatalog.map((skill) => ({
              key: skill.skillId,
              name: skill.displayName,
              description: skill.description,
              checked: skillDraft.includes(skill.skillId),
              disabled: !skill.enabled,
              detail: skill.enabled
                ? undefined
                : '사용자 설정에서 꺼져 있어 이 에이전트에 적용할 수 없습니다.',
            }))}
            missingSkills={missingSkillIds}
            selectedCount={selectedKnownSkillIds.length}
            saving={skillSaving}
            onSkillCreated={(skill) => {
              setSkillCatalog((current) =>
                current.some((item) => item.skillId === skill.skillId)
                  ? current
                  : [...current, skill],
              )
              setSkillDraftState({
                itemId: item.id,
                skills: Array.from(new Set([...skillDraft, skill.skillId])),
              })
              useAgentCacheStore.getState().invalidateUserSkills()
              setSaved(false)
            }}
            onSkillReorder={(orderedSkillIds) => {
              setSkillDraftState({
                itemId: item.id,
                skills: [...orderedSkillIds, ...missingSkillIds],
              })
              setSaved(false)
            }}
            onSkillToggle={toggleSkill}
            onSkillOpen={openSkillDetail}
            warnings={skillCatalogError ? [skillCatalogError] : []}
          />
        </AgentSkillsPanel>
      )}

      {tab === 'runs' && <AgentRunsPanel emptyText="아직 실행 기록이 없습니다." items={runItems} />}

      {tab === 'skills' && skillsDirty && (
        <div className="border-border bg-background/95 fixed inset-x-0 bottom-0 z-30 border-t backdrop-blur-sm sm:hidden">
          <div className="flex items-center justify-end gap-2 px-3 py-2 pb-[max(env(safe-area-inset-bottom),0.5rem)]">
            <Button size="sm" onClick={saveSkillDraft} disabled={skillSaving}>
              {skillSaving ? '저장 중' : '저장'}
            </Button>
            <Button variant="ghost" size="sm" onClick={resetSkillDraft} disabled={skillSaving}>
              취소
            </Button>
          </div>
        </div>
      )}
      {tab === 'skills' && skillsDirty && (
        <div className="fixed right-6 bottom-6 z-30 hidden sm:block">
          <div className="bg-background/90 border-border flex items-center gap-2 rounded-lg border px-3 py-1.5 shadow-lg backdrop-blur-sm">
            <Button size="sm" onClick={saveSkillDraft} disabled={skillSaving}>
              {skillSaving ? '저장 중' : '저장'}
            </Button>
            <Button variant="ghost" size="sm" onClick={resetSkillDraft} disabled={skillSaving}>
              취소
            </Button>
          </div>
        </div>
      )}
      {tab === 'instructions' && instructionsDirty && (
        <div className="border-border bg-background/95 fixed inset-x-0 bottom-0 z-30 border-t backdrop-blur-sm sm:hidden">
          <div className="flex items-center justify-end gap-2 px-3 py-2 pb-[max(env(safe-area-inset-bottom),0.5rem)]">
            <Button size="sm" onClick={saveInstructionsDraft}>
              저장
            </Button>
            <Button variant="ghost" size="sm" onClick={resetInstructionsDraft}>
              취소
            </Button>
          </div>
        </div>
      )}
      {tab === 'instructions' && instructionsDirty && (
        <div className="fixed right-6 bottom-6 z-30 hidden sm:block">
          <div className="bg-background/90 border-border flex items-center gap-2 rounded-lg border px-3 py-1.5 shadow-lg backdrop-blur-sm">
            <Button size="sm" onClick={saveInstructionsDraft}>
              저장
            </Button>
            <Button variant="ghost" size="sm" onClick={resetInstructionsDraft}>
              취소
            </Button>
          </div>
        </div>
      )}
      <AlertDialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteError(null)
          setDeleteDialogOpen(open)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>에이전트를 삭제할까요?</AlertDialogTitle>
            <AlertDialogDescription>
              `{item.agent.name}` 에이전트와 저장된 지침 문서가 삭제됩니다. 팀장 에이전트는 삭제되지
              않습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
          <AlertDialogFooter>
            <Button variant="destructive" onClick={() => void handleDelete()} disabled={deleting}>
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  삭제 중
                </>
              ) : (
                '삭제'
              )}
            </Button>
            <AlertDialogCancel disabled={deleting}>취소</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AgentSkillDetailDialog
        detail={skillDetail}
        loading={skillDetailLoading}
        open={skillDetailOpen}
        onDelete={handleSkillDeleted}
        onOpenChange={setSkillDetailOpen}
      />
    </div>
  )
}

function getDetailTab(value: string | null | undefined): SubAgentDetailTab {
  return DETAIL_TABS.some((tab) => tab.value === value) ? (value as SubAgentDetailTab) : 'dashboard'
}

function buildAgentTaskRuns(
  sessionId: string,
  profileId: string,
  loadedTaskRuns: RawTaskRun[],
  taskRunsById: Record<string, RawTaskRun>,
) {
  const byId = new Map<string, RawTaskRun>()
  for (const taskRun of loadedTaskRuns) {
    if (taskRunBelongsToSession(taskRun, sessionId)) byId.set(taskRun.task_run_id, taskRun)
  }
  for (const taskRun of Object.values(taskRunsById)) {
    if (taskRunBelongsToSession(taskRun, sessionId)) byId.set(taskRun.task_run_id, taskRun)
  }
  return [...byId.values()].filter((taskRun) => taskRunMatchesProfile(taskRun, profileId))
}

function buildAgentRunItems(
  taskRuns: RawTaskRun[],
  eventsByTaskRunId: Record<string, RawTaskEventPayload[]>,
  usageRecords: CommandUsageRecord[],
) {
  const usageByTaskRunId = buildAgentRunUsageMap(usageRecords)
  return taskRuns
    .map((taskRun) => buildAgentRunItem(taskRun, eventsByTaskRunId[taskRun.task_run_id] ?? []))
    .sort((first, second) => second.sortTime - first.sortTime)
    .map((item) => ({
      id: item.id,
      status: item.status,
      source: item.source,
      createdAt: item.createdAt,
      summary: item.summary,
      tokens: formatAgentRunTokenUsage(usageByTaskRunId.get(item.id)),
      cost: formatAgentRunCostUsage(usageByTaskRunId.get(item.id)),
      adapter: item.adapter,
      model: item.model,
      request: item.request,
      delegationInput: item.delegationInput,
      result: item.result,
      transcriptSessionId: item.transcriptSessionId,
      parentTranscriptSessionId: item.parentTranscriptSessionId,
      agentName: item.agentName,
      timeline: item.timeline,
      sortTime: item.sortTime,
    }))
}

function getRunSuccessRateLabel(runs: Array<{ status: string }>) {
  const finished = runs.filter(
    (run) => isRunSuccessStatus(run.status) || isRunFailureStatus(run.status),
  )
  if (finished.length === 0) return '0%'
  const succeeded = finished.filter((run) => isRunSuccessStatus(run.status)).length
  return `${Math.round((succeeded / finished.length) * 100)}%`
}

function isRunSuccessStatus(status?: string | null) {
  return status === 'succeeded' || status === 'completed'
}

function isRunFailureStatus(status?: string | null) {
  return (
    status === 'failed' || status === 'blocked' || status === 'cancelled' || status === 'canceled'
  )
}

function buildAgentRunItem(taskRun: RawTaskRun, rawEvents: RawTaskEventPayload[]) {
  const events = rawEvents.filter((event) => !isInternalStepAnchorEvent(event))
  const summary = toTaskRunSummaryView(taskRun, events)
  const inputSummary = typeof taskRun.input_summary === 'string' ? taskRun.input_summary : undefined
  const progressSummary =
    typeof taskRun.progress_summary === 'string' ? taskRun.progress_summary : undefined
  const inputPayload = toRecord(taskRun.input_payload)
  const resultPayload = toRecord(taskRun.result_payload)
  const resultMetadata = toRecord(resultPayload?.metadata)
  const model =
    getStringValue(inputPayload, 'model', 'provider_model', 'providerModel') ??
    getStringValue(resultPayload, 'model') ??
    getStringValue(resultMetadata, 'model') ??
    undefined
  const provider =
    getStringValue(inputPayload, 'provider_name', 'providerName', 'provider') ??
    getStringValue(resultPayload, 'provider_name', 'providerName', 'provider') ??
    undefined
  const sortTime = getRunSortTime(taskRun, events)

  return {
    id: taskRun.task_run_id,
    status: normalizeRunStatus(taskRun.status),
    source: agentDisplayName(taskRun) ?? 'subagent',
    createdAt: formatRunTimestamp(sortTime),
    summary:
      compactText(inputSummary) ??
      compactText(progressSummary) ??
      compactText(summary.title) ??
      '아직 요약이 없습니다.',
    adapter: getRunAdapterLabel(provider, model),
    model,
    request:
      getStringValue(inputPayload, 'prompt', 'content', 'rawUserInput', 'raw_user_input') ??
      inputSummary,
    delegationInput: buildDelegationInput(inputPayload, taskRun.displayContext),
    result:
      getStringValue(resultPayload, 'answer', 'content', 'finalAnswer', 'final_answer') ??
      undefined,
    transcriptSessionId:
      getStringValue(
        inputPayload,
        'transcript_session_id',
        'transcriptSessionId',
        'agentSessionId',
        'agent_session_id',
      ) ?? undefined,
    parentTranscriptSessionId:
      getStringValue(inputPayload, 'parentTranscriptSessionId', 'parent_transcript_session_id') ??
      undefined,
    agentName: agentDisplayName(taskRun),
    timeline: buildRunTimelineItems(events),
    sortTime,
  }
}

function taskRunBelongsToSession(taskRun: RawTaskRun, sessionId: string) {
  const taskSessionId =
    typeof taskRun.session_id === 'string'
      ? taskRun.session_id
      : typeof taskRun.session_key === 'string'
        ? taskRun.session_key
        : taskRun.displayContext?.sessionId
  return taskSessionId === sessionId
}

function taskRunMatchesProfile(taskRun: RawTaskRun, profileId: string) {
  const context = taskRun.displayContext
  if (matchesAgentRef(context?.assigneeAgent, profileId)) return true
  if (matchesAgentRef(context?.actorAgent, profileId)) return true
  if (context?.delegatedAgents?.some((agent) => matchesAgentRef(agent, profileId))) return true
  return typeof taskRun.agent_profile_id === 'string' && taskRun.agent_profile_id === profileId
}

function matchesAgentRef(agent: TaskRunAgentRef | undefined, profileId: string) {
  return agent?.profileId === profileId || agent?.id === profileId
}

function agentDisplayName(taskRun: RawTaskRun) {
  return (
    taskRun.displayContext?.actorAgent.displayName ??
    taskRun.displayContext?.assigneeAgent.displayName
  )
}

function getRunSortTime(taskRun: RawTaskRun, events: RawTaskEventPayload[]) {
  return Math.max(
    getTime(taskRun.completed_at),
    getTime(taskRun.updated_at),
    getTime(taskRun.created_at),
    ...events.map((event) => getTime(event.occurred_at)),
    0,
  )
}

function formatRunTimestamp(time: number) {
  if (time <= 0) return undefined
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(time))
}

function compactText(value?: string | null) {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''
  if (!text) return undefined
  return text.length > 120 ? `${text.slice(0, 117)}...` : text
}

function toRecord(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function getStringValue(source: unknown, ...keys: string[]) {
  const record = toRecord(source)
  if (record === undefined) return undefined
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim() !== '') return value.trim()
  }
  return undefined
}

function getRunAdapterLabel(provider?: string | null, model?: string | null) {
  const providerText = (provider ?? '').trim().toLowerCase()
  const modelText = (model ?? '').trim().toLowerCase()
  if (providerText.includes('gemini') || modelText.startsWith('gemini-')) return 'gemini'
  if (providerText.includes('openai') || modelText.startsWith('gpt-')) return 'openai'
  return providerText || undefined
}

function buildDelegationInput(
  inputPayload: Record<string, unknown> | undefined,
  displayContext: RawTaskRun['displayContext'] | undefined | null,
) {
  const parts: string[] = []
  const agentName = displayContext?.assigneeAgent?.displayName
  if (agentName) parts.push(`담당 에이전트: ${agentName}`)
  const workIdentifier = getStringValue(inputPayload, 'workIdentifier', 'work_identifier')
  if (workIdentifier) parts.push(`작업: ${workIdentifier}`)
  const workContext = toRecord(inputPayload?.workContext)
  const workTitle = getStringValue(workContext, 'title')
  if (workTitle) parts.push(`작업 제목: ${workTitle}`)
  const expectedDeliverable = getStringValue(
    workContext,
    'expectedDeliverable',
    'expected_deliverable',
  )
  if (expectedDeliverable) parts.push(`기대 산출물: ${expectedDeliverable}`)
  return parts.length > 0 ? parts.join('\n') : undefined
}

function buildRunTimelineItems(events: RawTaskEventPayload[]) {
  return events.slice(-12).map((event, index) => ({
    id: `${event.task_run_id}-${event.sequence ?? index}`,
    label: event.event_type,
    message: event.summary_message ?? undefined,
    status: event.status ?? undefined,
    time: formatRunTimestamp(getTime(event.occurred_at)),
  }))
}

function normalizeRunStatus(status?: string | null) {
  switch (status) {
    case 'completed':
    case 'COMPLETED':
    case 'succeeded':
      return 'succeeded'
    case 'failed':
    case 'FAILED':
    case 'blocked':
    case 'BLOCKED':
    case 'CANCELLED':
    case 'CANCELED':
      return 'failed'
    case 'in_review':
    case 'IN_REVIEW':
      return 'in_review'
    case 'running':
    case 'RUNNING':
      return 'running'
    case 'waiting':
    case 'WAITING':
    case 'PENDING':
      return 'waiting'
    default:
      return 'pending'
  }
}

function formatRunStatus(status?: string | null) {
  switch (normalizeRunStatus(status)) {
    case 'succeeded':
      return '완료'
    case 'running':
      return '실행 중'
    case 'waiting':
      return '대기 중'
    case 'failed':
      return '차단/오류'
    case 'in_review':
      return '검토 중'
    default:
      return '준비 중'
  }
}

function shallowStringRecordEqual(left: Record<string, string>, right: Record<string, string>) {
  const leftEntries = Object.entries(left)
  const rightEntries = Object.entries(right)
  if (leftEntries.length !== rightEntries.length) return false
  return leftEntries.every(([key, value]) => right[key] === value)
}

function stringArraysEqual(left: string[], right: string[]) {
  if (left.length !== right.length) return false
  return left.every((value, index) => right[index] === value)
}

function orderSkillCatalogBySelectedIds(
  catalog: SkillCatalogItem[],
  selectedSkillIds: string[],
): SkillCatalogItem[] {
  const byId = new Map(catalog.map((skill) => [skill.skillId, skill]))
  const selected = selectedSkillIds
    .map((skillId) => byId.get(skillId))
    .filter((skill): skill is SkillCatalogItem => skill !== undefined)
  const selectedIds = new Set(selected.map((skill) => skill.skillId))
  return [...selected, ...catalog.filter((skill) => !selectedIds.has(skill.skillId))]
}
