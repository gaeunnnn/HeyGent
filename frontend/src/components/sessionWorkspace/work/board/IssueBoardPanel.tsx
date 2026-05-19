import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  ArrowUpDown,
  Bot,
  Check,
  ChevronDown,
  Circle,
  CircleCheck,
  Clock3,
  Columns3,
  Filter,
  FileText,
  FolderKanban,
  List,
  ListTree,
  Loader2,
  MessageSquare,
  PauseCircle,
  PlayCircle,
  Plus,
  RotateCcw,
  Search,
  Send,
  Tag,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { addWorkRelation, createChildWork, removeWorkRelation, updateWorkParent } from '@/apis/work'
import { cn } from '@/components/ui/utils'
import { useSessionStore } from '@/store/useSessionStore'
import { useWorkStore } from '@/store/useWorkStore'
import type { WorkItem, WorkLabel } from '@/types/work'
import { getApiErrorMessage } from '@/utils/apiErrorMessage'
import {
  ISSUE_BOARD_STATUSES,
  createIssueBoardIdentifier,
  groupIssuesByStatus,
  issueBoardStatusLabel,
  moveIssueToStatus,
  type IssueBoardIssue,
  type IssueBoardLabel,
  type IssueBoardStatus,
} from '../model/issueBoardModel'
import type { BoardAssignee, DetailTab, SortField, ViewMode } from './issueBoardPanelTypes'
import { IssueRelatedPanel, RelatedIssuePill } from './IssueRelatedPanel'
import {
  WorkDocumentsPanel,
  WorkInteractionsPanel,
  WorkProductsPanel,
  WorkRecoveryPanel,
} from './WorkCollaborationPanels'
import {
  arraysEqual,
  assigneeLabel,
  commentAuthorLabel,
  createLabelIdentifier,
  filterTodos,
  formatRelativeTime,
  isHexColor,
  loadTodoBoardState,
  nextSortField,
  resolveIssueLabels,
  runStatusLabel,
  saveTodoBoardState,
  sortFieldLabel,
  sortTodos,
  toIssueBoardComment,
  toIssueBoardIssue,
  toIssueBoardLabel,
  toggleValue,
} from './issueBoardPanelUtils'

const MAIN_AGENT_ASSIGNEE = {
  id: 'CEO',
  name: '팀장 에이전트',
  icon: UserRound,
  imageUrl: '/assets/agents/ceo/ceo_profile_img.png' as string | null,
} as const
const EMPTY_WORK_ITEMS: WorkItem[] = []
const EMPTY_WORK_LABELS: WorkLabel[] = []
const EMPTY_AGENT_PANELS: ReturnType<
  typeof useSessionStore.getState
>['agentPanelsBySessionId'][string] = []

const QUICK_FILTERS = [
  { id: 'all', label: '전체', statuses: [] },
  { id: 'active', label: '진행 항목', statuses: ['todo', 'in_progress', 'in_review', 'blocked'] },
  { id: 'blocked', label: '차단됨', statuses: ['blocked'] },
  { id: 'done', label: '완료', statuses: ['done'] },
] as const

function hasUnresolvedBlockers(issue: IssueBoardIssue) {
  return issue.blockedBy.some((item) => item.status !== 'done')
}

function shouldResumeWorkFromComment(issue: IssueBoardIssue) {
  if (issue.status === 'done') return true
  if (issue.status === 'blocked') return !hasUnresolvedBlockers(issue)
  return false
}

function commentSubmitHint(issue: IssueBoardIssue) {
  if (issue.live) return '실행 중인 작업이라 댓글 반영을 대기열에 올립니다.'
  if (issue.status === 'done') return '댓글 전송 후 완료된 작업을 다시 실행합니다.'
  if (issue.status === 'blocked' && hasUnresolvedBlockers(issue)) {
    return '선행 작업이 남아 있어 댓글만 기록합니다.'
  }
  if (issue.status === 'blocked') return '댓글 전송 후 차단을 풀고 작업을 다시 실행합니다.'
  if (issue.assigneeAgentId) return '댓글 전송 후 담당 에이전트가 내용을 반영합니다.'
  return '댓글은 작업 기록에 남습니다.'
}

function collectDescendantIssueIds(issues: IssueBoardIssue[], issueId: string) {
  const childIdsByParent = new Map<string, string[]>()
  for (const issue of issues) {
    if (!issue.parentId) continue
    childIdsByParent.set(issue.parentId, [
      ...(childIdsByParent.get(issue.parentId) ?? []),
      issue.id,
    ])
  }
  const descendantIds: string[] = []
  const queue = [...(childIdsByParent.get(issueId) ?? [])]
  while (queue.length > 0) {
    const childId = queue.shift()
    if (!childId || descendantIds.includes(childId)) continue
    descendantIds.push(childId)
    queue.push(...(childIdsByParent.get(childId) ?? []))
  }
  return descendantIds
}

export function IssueBoardPanel({ sessionId }: { sessionId: string }) {
  const storageKey = `heygent-task-board:v4:${sessionId}`
  const isPendingSession = sessionId.startsWith('pending_session_')
  const workItems = useWorkStore((state) => state.itemsBySessionId[sessionId] ?? EMPTY_WORK_ITEMS)
  const commentsByWorkId = useWorkStore((state) => state.commentsByWorkId)
  const isWorkLoading = useWorkStore((state) => state.loadingBySessionId[sessionId] === true)
  const workError = useWorkStore((state) => state.lastError)
  const fetchSessionWork = useWorkStore((state) => state.fetchSessionWork)
  const fetchWorkComments = useWorkStore((state) => state.fetchComments)
  const fetchWorkLabels = useWorkStore((state) => state.fetchLabels)
  const serverLabels = useWorkStore(
    (state) => state.labelsBySessionId[sessionId] ?? EMPTY_WORK_LABELS,
  )
  const moveWorkItemStatus = useWorkStore((state) => state.moveStatus)
  const updateWorkItemFields = useWorkStore((state) => state.updateFields)
  const updateWorkItemAssignee = useWorkStore((state) => state.updateAssignee)
  const addWorkItemComment = useWorkStore((state) => state.addComment)
  const createWorkItemLabel = useWorkStore((state) => state.createLabel)
  const createWorkItem = useWorkStore((state) => state.createWork)
  const createWorkItemRun = useWorkStore((state) => state.createRun)
  const setWorkItemLabels = useWorkStore((state) => state.setLabels)
  const deleteWorkItem = useWorkStore((state) => state.deleteWorkItem)
  const agentPanelsBySessionId = useSessionStore((state) => state.agentPanelsBySessionId)
  const assignees = useMemo<BoardAssignee[]>(() => {
    const agentPanels = agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS
    return [
      MAIN_AGENT_ASSIGNEE,
      ...agentPanels.map((panel) => ({
        id: panel.id,
        name: panel.agent.name,
        icon: Bot,
        templateKey: panel.agent.templateKey,
        imageUrl: panel.agent.profileImage ?? null,
      })),
    ]
  }, [agentPanelsBySessionId, sessionId])
  const [initialState] = useState(() => loadTodoBoardState(storageKey))
  const [issues, setIssues] = useState(initialState.issues)
  const [labels, setLabels] = useState<IssueBoardLabel[]>(initialState.labels)
  const [query, setQuery] = useState(initialState.query)
  const [viewMode, setViewMode] = useState<ViewMode>(initialState.viewMode)
  const [sortField, setSortField] = useState<SortField>(initialState.sortField)
  const [selectedStatuses, setSelectedStatuses] = useState<IssueBoardStatus[]>(
    initialState.selectedStatuses,
  )
  const [selectedAssignees, setSelectedAssignees] = useState<string[]>(
    initialState.selectedAssignees,
  )
  const [selectedLabels, setSelectedLabels] = useState<string[]>(initialState.selectedLabels)
  const [liveOnly, setLiveOnly] = useState(initialState.liveOnly)
  const [draggedIssueId, setDraggedIssueId] = useState<string | null>(null)
  const [dragOverStatus, setDragOverStatus] = useState<IssueBoardStatus | null>(null)
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null)
  const [workNotice, setWorkNotice] = useState<string | null>(null)
  const visibleWorkError = workError && workError !== workNotice ? workError : null
  const [runningIssueIds, setRunningIssueIds] = useState<Set<string>>(() => new Set())
  const [commentSubmittingIssueIds, setCommentSubmittingIssueIds] = useState<Set<string>>(
    () => new Set(),
  )

  useEffect(() => {
    if (isPendingSession) return
    void Promise.all([fetchSessionWork(sessionId), fetchWorkLabels(sessionId)]).catch((error) => {
      console.error(error)
    })
  }, [fetchSessionWork, fetchWorkLabels, isPendingSession, sessionId])

  useEffect(() => {
    saveTodoBoardState(storageKey, {
      issues,
      labels,
      query,
      viewMode,
      sortField,
      selectedStatuses,
      selectedAssignees,
      selectedLabels,
      liveOnly,
    })
  }, [
    issues,
    labels,
    liveOnly,
    query,
    selectedAssignees,
    selectedLabels,
    selectedStatuses,
    sortField,
    storageKey,
    viewMode,
  ])

  const boardIssues = useMemo(
    () => (isPendingSession ? issues : workItems.map((item) => toIssueBoardIssue(item, workItems))),
    [isPendingSession, issues, workItems],
  )
  const boardLabels = useMemo(
    () => (isPendingSession ? labels : serverLabels.map(toIssueBoardLabel)),
    [isPendingSession, labels, serverLabels],
  )
  const filteredIssues = useMemo(
    () =>
      sortTodos(
        filterTodos(
          boardIssues,
          {
            query,
            statuses: selectedStatuses,
            assignees: selectedAssignees,
            labels: selectedLabels,
            liveOnly,
          },
          assignees,
          boardLabels,
        ),
        sortField,
      ),
    [
      assignees,
      boardIssues,
      boardLabels,
      liveOnly,
      query,
      selectedAssignees,
      selectedLabels,
      selectedStatuses,
      sortField,
    ],
  )
  const grouped = useMemo(() => groupIssuesByStatus(filteredIssues), [filteredIssues])
  const selectedIssueBase = selectedIssueId
    ? (boardIssues.find((issue) => issue.id === selectedIssueId) ?? null)
    : null
  const selectedIssue =
    selectedIssueBase && commentsByWorkId[selectedIssueBase.id]
      ? {
          ...selectedIssueBase,
          comments: commentsByWorkId[selectedIssueBase.id].map(toIssueBoardComment),
        }
      : selectedIssueBase
  const activeFilterCount =
    Number(selectedStatuses.length > 0) +
    Number(selectedAssignees.length > 0) +
    Number(selectedLabels.length > 0) +
    Number(liveOnly)

  useEffect(() => {
    if (!selectedIssueId) return
    const serverWork = workItems.find((item) => item.workId === selectedIssueId)
    if (!serverWork) return
    void fetchWorkComments(selectedIssueId).catch((error) => {
      console.error(error)
    })
  }, [fetchWorkComments, selectedIssueId, workItems])

  const moveIssue = (issueId: string, status: IssueBoardStatus) => {
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (serverWork) {
      void moveWorkItemStatus(issueId, status).catch((error) => {
        console.error(error)
      })
      return
    }
    setIssues((current) => moveIssueToStatus(current, issueId, status))
  }

  const assignIssue = (issueId: string, assigneeAgentId: string | null) => {
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (serverWork) {
      void updateWorkItemAssignee(issueId, assigneeAgentId).catch((error) => {
        console.error(error)
      })
      return
    }
    const now = new Date().toISOString()
    setIssues((current) =>
      current.map((issue) =>
        issue.id === issueId ? { ...issue, assigneeAgentId, updatedAt: now } : issue,
      ),
    )
  }

  const updateIssue = (issueId: string, patch: Partial<IssueBoardIssue>) => {
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (serverWork && patch.labels !== undefined) {
      void setWorkItemLabels(issueId, patch.labels).catch((error) => {
        console.error(error)
      })
      return
    }
    const fieldPatch: { title?: string; description?: string } = {}
    if (patch.title !== undefined) fieldPatch.title = patch.title
    if (patch.description !== undefined) fieldPatch.description = patch.description
    if (serverWork && Object.keys(fieldPatch).length > 0) {
      void updateWorkItemFields(issueId, fieldPatch).catch((error) => {
        console.error(error)
      })
      return
    }
    const now = new Date().toISOString()
    setIssues((current) =>
      current.map((issue) =>
        issue.id === issueId
          ? {
              ...issue,
              ...patch,
              id: issue.id,
              identifier: issue.identifier,
              updatedAt: now,
            }
          : issue,
      ),
    )
  }

  const addIssueComment = async (issueId: string, body: string) => {
    const trimmed = body.trim()
    if (!trimmed) return
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (serverWork) {
      const issue = boardIssues.find((item) => item.id === issueId)
      const resume = issue ? shouldResumeWorkFromComment(issue) : false
      setCommentSubmittingIssueIds((current) => new Set(current).add(issueId))
      try {
        await addWorkItemComment(issueId, trimmed, resume)
        await Promise.all([fetchSessionWork(sessionId), fetchWorkComments(issueId)])
      } catch (error) {
        const message = getApiErrorMessage(error, { fallback: '댓글을 전송하지 못했습니다.' })
        setWorkNotice(message)
        console.error(error)
        throw error
      } finally {
        setCommentSubmittingIssueIds((current) => {
          const next = new Set(current)
          next.delete(issueId)
          return next
        })
      }
      return
    }
    const now = new Date().toISOString()
    setIssues((current) =>
      current.map((issue) =>
        issue.id === issueId
          ? {
              ...issue,
              comments: [
                ...issue.comments,
                {
                  id: `${issue.id}:comment:${Date.now()}`,
                  authorType: 'user',
                  authorName: '사용자',
                  body: trimmed,
                  createdAt: now,
                },
              ],
              updatedAt: now,
            }
          : issue,
      ),
    )
  }

  const createLabel = (label: IssueBoardLabel) => {
    if (!isPendingSession) {
      void createWorkItemLabel(sessionId, { name: label.name, color: label.color }).catch(
        (error) => {
          console.error(error)
        },
      )
      return
    }
    setLabels((current) => {
      if (current.some((item) => item.id === label.id)) return current
      return [...current, label]
    })
  }

  const runIssue = (issueId: string) => {
    const issue = boardIssues.find((item) => item.id === issueId)
    if (!issue) return
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (!serverWork) {
      setWorkNotice('서버에 저장된 작업만 실행할 수 있습니다.')
      return
    }
    const unresolvedBlockers = issue.blockedBy.filter((item) => item.status !== 'done')
    if (unresolvedBlockers.length > 0) {
      setWorkNotice(
        `먼저 완료해야 하는 작업이 있습니다: ${unresolvedBlockers
          .map((item) => item.identifier)
          .join(', ')}`,
      )
      return
    }
    setWorkNotice(null)
    const message =
      issue.status === 'blocked'
        ? '차단 해제 정보를 반영해서 이 작업을 이어서 진행해.'
        : issue.status === 'done'
          ? '이 작업을 다시 검토하고 필요한 후속 실행을 진행해.'
          : '이 작업을 이어서 진행해.'
    setRunningIssueIds((current) => new Set(current).add(issueId))
    void createWorkItemRun(issueId, message)
      .then((response) => {
        setSelectedIssueId(response.work.workId)
        setWorkNotice(`${response.work.identifier} 작업 실행을 시작했습니다.`)
        return fetchSessionWork(sessionId)
      })
      .catch((error) => {
        setWorkNotice(getApiErrorMessage(error, { fallback: '작업 실행에 실패했습니다.' }))
      })
      .finally(() => {
        setRunningIssueIds((current) => {
          const next = new Set(current)
          next.delete(issueId)
          return next
        })
      })
  }

  const deleteIssue = async (issueId: string, cascadeChildren = false) => {
    const serverWork = workItems.find((item) => item.workId === issueId)
    if (serverWork) {
      try {
        const item = await deleteWorkItem(issueId, cascadeChildren)
        await fetchSessionWork(sessionId)
        setSelectedIssueId(null)
        setWorkNotice(
          cascadeChildren
            ? `${item.identifier} 작업과 하위 작업을 삭제했습니다.`
            : `${item.identifier} 작업을 삭제했습니다.`,
        )
      } catch (error) {
        console.error(error)
        setWorkNotice(getApiErrorMessage(error, { fallback: '작업 삭제에 실패했습니다.' }))
        throw error
      }
      return
    }
    setIssues((current) => {
      if (!cascadeChildren) {
        return current
          .filter((issue) => issue.id !== issueId)
          .map((issue) => (issue.parentId === issueId ? { ...issue, parentId: null } : issue))
      }
      const deletedIds = new Set(collectDescendantIssueIds(current, issueId))
      deletedIds.add(issueId)
      return current.filter((issue) => !deletedIds.has(issue.id))
    })
    setSelectedIssueId(null)
  }

  const resetFilters = () => {
    setQuery('')
    setSelectedStatuses([])
    setSelectedAssignees([])
    setSelectedLabels([])
    setLiveOnly(false)
  }

  const createNewTodo = () => {
    if (!isPendingSession) {
      void createWorkItem(sessionId, {
        clientRequestId: `manual:${sessionId}:${Date.now()}`,
        title: '새 작업',
        description: '담당 에이전트 한 명에게 맡길 작업입니다.',
        assigneeAgentId: null,
        rawUserInput: '새 작업',
        executionInstruction: '작업 내용을 확인하고 필요한 실행을 진행합니다.',
        startExecution: false,
        acceptanceCriteria: [],
        constraints: [],
        labelNames: [],
        initialComment: '새 작업이 생성되었습니다.',
        metadata: { createdFrom: 'work_board' },
        flowOrder: boardIssues.length,
      })
        .then((response) => {
          setSelectedIssueId(response.work.workId)
          setWorkNotice(`${response.work.identifier} 작업을 만들었습니다.`)
          return fetchSessionWork(sessionId)
        })
        .catch((error) => {
          console.error(error)
          setWorkNotice(getApiErrorMessage(error, { fallback: '작업 생성에 실패했습니다.' }))
        })
      return
    }
    const now = new Date().toISOString()
    const sequence = issues.length + 1
    const todoId = `${sessionId}:todo:${String(sequence).padStart(3, '0')}`
    setIssues((current) => [
      {
        id: todoId,
        identifier: createIssueBoardIdentifier(sequence),
        title: '새 작업',
        description: '담당 에이전트 한 명에게 맡길 작업입니다.',
        status: 'todo',
        assigneeAgentId: null,
        parentId: null,
        flowOrder: null,
        labels: [],
        comments: [
          {
            id: `${todoId}:comment:001`,
            authorType: 'system',
            authorName: '시스템',
            body: '새 작업이 생성되었습니다.',
            createdAt: now,
          },
        ],
        runs: [],
        documents: [],
        childItems: [],
        relatedItems: [],
        blockedBy: [],
        createdAt: now,
        updatedAt: now,
        startedAt: null,
        completedAt: null,
        live: false,
      },
      ...current,
    ])
  }

  return (
    <section className="bg-background flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden">
      <header className="border-border/70 flex shrink-0 flex-col gap-3 border-b px-6 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-muted-foreground flex items-center gap-2 text-[11px] font-semibold tracking-widest uppercase">
              <FolderKanban className="h-3.5 w-3.5" />
              작업 보드
            </div>
            <h1 className="text-foreground mt-1 truncate text-xl font-semibold">작업</h1>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="border-border bg-muted/20 rounded-full border px-2 py-1 text-[11px] font-medium">
              작업 {boardIssues.length}개
            </span>
            {isWorkLoading && (
              <span className="border-border bg-muted/20 text-muted-foreground rounded-full border px-2 py-1 text-[11px] font-medium">
                동기화 중
              </span>
            )}
            <span className="border-border bg-muted/20 rounded-full border px-2 py-1 text-[11px] font-medium">
              작업당 에이전트 1명
            </span>
            <span className="border-border bg-muted/20 rounded-full border px-2 py-1 text-[11px] font-medium">
              동시 실행 1개
            </span>
          </div>
        </div>
        {visibleWorkError && (
          <p className="text-destructive text-xs" aria-live="polite">
            {visibleWorkError}
          </p>
        )}
        {workNotice && (
          <p className="text-xs text-amber-600" aria-live="polite">
            {workNotice}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 gap-2"
            onClick={createNewTodo}
          >
            <Plus className="h-4 w-4" />새 작업
          </Button>
          <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="작업 검색..."
              aria-label="작업 검색"
              className="h-9 pl-9"
            />
          </div>
          <div className="ml-auto flex items-center gap-1">
            <div className="border-border bg-muted/20 flex items-center gap-1 rounded-md border p-1">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(viewMode === 'list' && 'bg-accent text-foreground')}
                title="목록"
                onClick={() => setViewMode('list')}
              >
                <List className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={cn(viewMode === 'board' && 'bg-accent text-foreground')}
                title="보드"
                onClick={() => setViewMode('board')}
              >
                <Columns3 className="h-4 w-4" />
              </Button>
            </div>
            <FilterPopover
              activeFilterCount={activeFilterCount}
              assignees={assignees}
              labels={boardLabels}
              liveOnly={liveOnly}
              selectedAssignees={selectedAssignees}
              selectedLabels={selectedLabels}
              selectedStatuses={selectedStatuses}
              onAssigneesChange={setSelectedAssignees}
              onClear={resetFilters}
              onLabelsChange={setSelectedLabels}
              onLiveOnlyChange={setLiveOnly}
              onStatusesChange={setSelectedStatuses}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-9 gap-1.5 px-2.5"
              title="정렬"
              onClick={() => setSortField(nextSortField(sortField))}
            >
              <ArrowUpDown className="h-4 w-4" />
              {sortFieldLabel(sortField)}
            </Button>
          </div>
        </div>
      </header>

      {viewMode === 'board' ? (
        <TodoKanbanBoard
          draggedIssueId={draggedIssueId}
          dragOverStatus={dragOverStatus}
          grouped={grouped}
          onDragEnd={(issueId, status) => {
            moveIssue(issueId, status)
            setDraggedIssueId(null)
            setDragOverStatus(null)
          }}
          onDragLeave={() => setDragOverStatus(null)}
          onDragOverStatus={setDragOverStatus}
          onDragReset={() => {
            setDraggedIssueId(null)
            setDragOverStatus(null)
          }}
          onDragStart={setDraggedIssueId}
          onOpenIssue={setSelectedIssueId}
          assignees={assignees}
          labels={boardLabels}
        />
      ) : (
        <TodoListView
          issues={filteredIssues}
          onOpenIssue={setSelectedIssueId}
          assignees={assignees}
          labels={boardLabels}
        />
      )}

      <TodoDetailPanel
        assignees={assignees}
        allIssues={boardIssues}
        issue={selectedIssue}
        isCommentSubmitting={
          selectedIssue ? commentSubmittingIssueIds.has(selectedIssue.id) : false
        }
        isRunning={selectedIssue ? runningIssueIds.has(selectedIssue.id) : false}
        labels={boardLabels}
        onAssignIssue={assignIssue}
        onAddComment={addIssueComment}
        onCreateLabel={createLabel}
        onDeleteIssue={deleteIssue}
        onMoveStatus={(issueId, status) => moveIssue(issueId, status)}
        onOpenChange={(open) => !open && setSelectedIssueId(null)}
        onRunIssue={runIssue}
        onAddRelation={(sourceId, targetId, relationType) => {
          void addWorkRelation(sourceId, targetId, relationType)
            .then(() => fetchSessionWork(sessionId))
            .catch((error) => {
              console.error(error)
            })
        }}
        onChangeParent={(issueId, parentId) => {
          void updateWorkParent(issueId, parentId)
            .then(() => fetchSessionWork(sessionId))
            .catch((error) => {
              console.error(error)
            })
        }}
        onCreateChild={(parentId, title, description) => {
          void createChildWork(parentId, {
            clientRequestId: `child:${parentId}:${Date.now()}`,
            title,
            description,
            blockParentUntilDone: false,
          })
            .then(() => fetchSessionWork(sessionId))
            .catch((error) => {
              console.error(error)
            })
        }}
        onRemoveRelation={(sourceId, targetId, relationType) => {
          void removeWorkRelation(sourceId, targetId, relationType)
            .then(() => fetchSessionWork(sessionId))
            .catch((error) => {
              console.error(error)
            })
        }}
        onUpdateIssue={updateIssue}
      />
    </section>
  )
}

export const WorkBoardPanel = IssueBoardPanel

function TodoKanbanBoard({
  draggedIssueId,
  dragOverStatus,
  grouped,
  labels,
  onDragEnd,
  onDragLeave,
  onDragOverStatus,
  onDragReset,
  onDragStart,
  onOpenIssue,
  assignees,
}: {
  draggedIssueId: string | null
  dragOverStatus: IssueBoardStatus | null
  grouped: Record<IssueBoardStatus, IssueBoardIssue[]>
  assignees: BoardAssignee[]
  labels: IssueBoardLabel[]
  onDragEnd: (issueId: string, status: IssueBoardStatus) => void
  onDragLeave: () => void
  onDragOverStatus: (status: IssueBoardStatus) => void
  onDragReset: () => void
  onDragStart: (issueId: string) => void
  onOpenIssue: (issueId: string) => void
}) {
  return (
    <div className="min-h-0 flex-1 overflow-x-auto py-5 pr-16 pl-6">
      <div className="flex min-h-full gap-3 pb-3">
        {ISSUE_BOARD_STATUSES.map((status) => {
          const issues = grouped[status]
          const isOver = dragOverStatus === status
          if (issues.length === 0 && !isOver) {
            return (
              <section
                key={status}
                onDragOver={(event) => {
                  event.preventDefault()
                  onDragOverStatus(status)
                }}
                className="flex w-14 min-w-14 shrink-0 flex-col"
              >
                <div className="bg-muted/20 border-border/70 flex min-h-[220px] flex-1 flex-col items-center gap-2 rounded-md border border-dashed py-3">
                  <StatusIcon status={status} />
                  <span className="text-muted-foreground text-xs font-semibold tracking-wide [writing-mode:vertical-rl]">
                    {issueBoardStatusLabel(status)}
                  </span>
                  <span className="text-muted-foreground/60 mt-auto text-xs tabular-nums">0</span>
                </div>
              </section>
            )
          }
          return (
            <section
              key={status}
              onDragOver={(event) => {
                event.preventDefault()
                onDragOverStatus(status)
              }}
              onDragLeave={onDragLeave}
              onDrop={(event) => {
                event.preventDefault()
                const issueId = event.dataTransfer.getData('text/plain') || draggedIssueId
                if (issueId) onDragEnd(issueId, status)
              }}
              className="flex w-[280px] min-w-[280px] shrink-0 flex-col"
            >
              <div className="mb-1 flex items-center gap-2 px-2 py-2">
                <StatusIcon status={status} />
                <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                  {issueBoardStatusLabel(status)}
                </span>
                <span className="text-muted-foreground/60 ml-auto text-xs tabular-nums">
                  {issues.length}
                </span>
              </div>
              <div
                className={cn(
                  'min-h-[120px] flex-1 space-y-1 rounded-md p-1 transition-colors',
                  isOver ? 'bg-accent/40' : 'bg-muted/20',
                )}
              >
                {issues.map((issue) => (
                  <TodoCard
                    key={issue.id}
                    issue={issue}
                    assignees={assignees}
                    labels={labels}
                    dragging={draggedIssueId === issue.id}
                    onDragReset={onDragReset}
                    onDragStart={onDragStart}
                    onOpenIssue={onOpenIssue}
                  />
                ))}
              </div>
            </section>
          )
        })}
        <div className="w-12 shrink-0" aria-hidden="true" />
      </div>
    </div>
  )
}

function TodoCard({
  dragging,
  issue,
  labels,
  onDragReset,
  onDragStart,
  onOpenIssue,
  assignees,
}: {
  dragging: boolean
  issue: IssueBoardIssue
  assignees: BoardAssignee[]
  labels: IssueBoardLabel[]
  onDragReset: () => void
  onDragStart: (issueId: string) => void
  onOpenIssue: (issueId: string) => void
}) {
  const assigneeName = assigneeLabel(issue.assigneeAgentId, assignees)
  const issueLabels = resolveIssueLabels(issue.labels, labels)

  return (
    <article
      role="button"
      tabIndex={0}
      draggable
      onClick={() => onOpenIssue(issue.id)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpenIssue(issue.id)
        }
      }}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', issue.id)
        onDragStart(issue.id)
      }}
      onDragEnd={onDragReset}
      className={cn(
        'bg-card cursor-grab rounded-md border p-2.5 text-left transition-shadow active:cursor-grabbing',
        dragging ? 'opacity-30' : 'hover:shadow-sm',
      )}
    >
      <div className="mb-1.5 flex items-start gap-1.5">
        <span className="text-muted-foreground shrink-0 font-mono text-xs">{issue.identifier}</span>
        <span className="text-muted-foreground rounded-full border px-1.5 py-0.5 text-[10px] font-medium">
          {issueBoardStatusLabel(issue.status)}
        </span>
      </div>
      <p className="mb-2 line-clamp-2 text-sm leading-snug">{issue.title}</p>
      {issueLabels.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {issueLabels.slice(0, 3).map((label) => (
            <LabelPill key={label.id} label={label} compact />
          ))}
          {issueLabels.length > 3 && (
            <span className="text-muted-foreground text-[11px]">+{issueLabels.length - 3}</span>
          )}
        </div>
      )}
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="text-muted-foreground inline-flex min-w-0 items-center gap-1 text-xs">
          <UserRound className="h-3 w-3 shrink-0" />
          <span className="truncate">{assigneeName}</span>
        </div>
        {issue.comments.length > 0 && (
          <span className="text-muted-foreground inline-flex shrink-0 items-center gap-1 text-[11px]">
            <MessageSquare className="h-3 w-3" />
            {issue.comments.length}
          </span>
        )}
      </div>
    </article>
  )
}

function TodoListView({
  issues,
  onOpenIssue,
  assignees,
  labels,
}: {
  issues: IssueBoardIssue[]
  onOpenIssue: (issueId: string) => void
  assignees: BoardAssignee[]
  labels: IssueBoardLabel[]
}) {
  const grouped = ISSUE_BOARD_STATUSES.map((status) => ({
    key: status,
    title: issueBoardStatusLabel(status),
    issues: issues.filter((issue) => issue.status === status),
  })).filter((group) => group.issues.length > 0)

  return (
    <div className="min-h-0 flex-1 overflow-auto py-6 pr-16 pl-6">
      <div className="bg-background/70 overflow-hidden rounded-lg border">
        <div className="text-muted-foreground grid grid-cols-[minmax(18rem,1fr)_7rem_6rem] items-center gap-3 border-b px-4 py-2 text-[11px] font-semibold tracking-widest uppercase">
          <span>작업</span>
          <span>담당자</span>
          <span className="text-right">수정</span>
        </div>
        {issues.length === 0 ? (
          <p className="text-muted-foreground px-4 py-6 text-sm">
            현재 필터나 검색어에 맞는 작업이 없습니다.
          </p>
        ) : (
          grouped.map((group) => (
            <div key={group.key}>
              <div className="text-muted-foreground flex items-center gap-2 border-b px-4 py-3 text-xs font-semibold tracking-wide uppercase">
                <StatusIcon status={group.key} />
                {group.title}
                <span className="ml-auto text-[11px] font-medium normal-case">
                  작업 {group.issues.length}개
                </span>
              </div>
              {group.issues.map((issue) => (
                <TodoListRow
                  key={issue.id}
                  assignees={assignees}
                  issue={issue}
                  labels={labels}
                  onOpenIssue={onOpenIssue}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function TodoListRow({
  assignees,
  issue,
  labels,
  onOpenIssue,
}: {
  assignees: BoardAssignee[]
  issue: IssueBoardIssue
  labels: IssueBoardLabel[]
  onOpenIssue: (issueId: string) => void
}) {
  const issueLabels = resolveIssueLabels(issue.labels, labels)

  return (
    <button
      type="button"
      onClick={() => onOpenIssue(issue.id)}
      className="hover:bg-accent/30 grid w-full grid-cols-[minmax(18rem,1fr)_7rem_6rem] items-center gap-3 border-b px-4 py-3 text-left transition-colors last:border-b-0"
    >
      <div className="flex min-w-0 items-center gap-2">
        <StatusIcon status={issue.status} />
        <span className="text-muted-foreground shrink-0 font-mono text-xs">{issue.identifier}</span>
        <span className="min-w-0 truncate text-sm font-medium">{issue.title}</span>
        {issueLabels.length > 0 && (
          <span className="hidden min-w-0 flex-wrap gap-1 lg:flex">
            {issueLabels.slice(0, 2).map((label) => (
              <LabelPill key={label.id} label={label} compact />
            ))}
            {issueLabels.length > 2 && (
              <span className="text-muted-foreground text-[11px]">+{issueLabels.length - 2}</span>
            )}
          </span>
        )}
      </div>
      <span className="text-muted-foreground truncate text-xs">
        {assigneeLabel(issue.assigneeAgentId, assignees)}
      </span>
      <span className="text-muted-foreground truncate text-right text-xs">
        {formatRelativeTime(issue.updatedAt)}
      </span>
    </button>
  )
}

function FilterPopover({
  activeFilterCount,
  assignees,
  labels,
  liveOnly,
  selectedAssignees,
  selectedLabels,
  selectedStatuses,
  onAssigneesChange,
  onClear,
  onLabelsChange,
  onLiveOnlyChange,
  onStatusesChange,
}: {
  activeFilterCount: number
  assignees: BoardAssignee[]
  labels: IssueBoardLabel[]
  liveOnly: boolean
  selectedAssignees: string[]
  selectedLabels: string[]
  selectedStatuses: IssueBoardStatus[]
  onAssigneesChange: (value: string[]) => void
  onClear: () => void
  onLabelsChange: (value: string[]) => void
  onLiveOnlyChange: (value: boolean) => void
  onStatusesChange: (value: IssueBoardStatus[]) => void
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="relative h-9 w-9"
          title="필터"
        >
          <Filter className="h-4 w-4" />
          {activeFilterCount > 0 && (
            <span className="bg-primary text-primary-foreground absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-bold">
              {activeFilterCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[min(520px,calc(100vh-6rem))] w-80 overflow-hidden p-0"
      >
        <div className="flex max-h-[min(520px,calc(100vh-6rem))] flex-col">
          <div className="border-border/70 flex items-center justify-between gap-3 border-b px-3 py-3">
            <div>
              <div className="text-muted-foreground text-[11px] font-semibold tracking-widest uppercase">
                필터
              </div>
              <div className="text-sm font-medium">표시할 작업</div>
            </div>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground text-xs font-medium"
              onClick={onClear}
            >
              초기화
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
            <div className="space-y-1.5">
              <span className="text-muted-foreground text-xs">빠른 필터</span>
              <div className="flex flex-wrap gap-1.5">
                {QUICK_FILTERS.map((filter) => {
                  const active = arraysEqual(selectedStatuses, [...filter.statuses])
                  return (
                    <button
                      key={filter.id}
                      type="button"
                      className={cn(
                        'rounded-full border px-2.5 py-1 text-xs transition-colors',
                        active
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground',
                      )}
                      onClick={() => onStatusesChange([...filter.statuses] as IssueBoardStatus[])}
                    >
                      {filter.label}
                    </button>
                  )
                })}
              </div>
            </div>
            <FilterSection title="상태">
              {ISSUE_BOARD_STATUSES.map((status) => (
                <FilterCheck
                  key={status}
                  checked={selectedStatuses.includes(status)}
                  icon={<StatusIcon status={status} />}
                  label={issueBoardStatusLabel(status)}
                  onChange={() => onStatusesChange(toggleValue(selectedStatuses, status))}
                />
              ))}
            </FilterSection>
            <FilterSection title="담당 에이전트">
              {[{ id: '__unassigned', name: '담당자 없음', icon: UserRound }, ...assignees].map(
                (assignee) => (
                  <FilterCheck
                    key={assignee.id}
                    checked={selectedAssignees.includes(assignee.id)}
                    icon={
                      assignee.id === '__unassigned' ? undefined : (
                        <assignee.icon className="h-3.5 w-3.5" />
                      )
                    }
                    label={assignee.name}
                    onChange={() => onAssigneesChange(toggleValue(selectedAssignees, assignee.id))}
                  />
                ),
              )}
            </FilterSection>
            <FilterSection title="라벨">
              <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
                {labels.map((label) => (
                  <FilterCheck
                    key={label.id}
                    checked={selectedLabels.includes(label.id)}
                    icon={
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: label.color }}
                      />
                    }
                    label={label.name}
                    onChange={() => onLabelsChange(toggleValue(selectedLabels, label.id))}
                  />
                ))}
              </div>
            </FilterSection>
            <FilterSection title="실행">
              <FilterCheck
                checked={liveOnly}
                label="실행 중인 작업만"
                onChange={() => onLiveOnlyChange(!liveOnly)}
              />
            </FilterSection>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function FilterSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div>
      <div className="text-muted-foreground mb-2 text-[11px] font-semibold tracking-widest uppercase">
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function FilterCheck({
  checked,
  icon,
  label,
  onChange,
}: {
  checked: boolean
  icon?: ReactNode
  label: string
  onChange: () => void
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      className="hover:bg-accent/50 flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm"
      onClick={onChange}
    >
      <span
        className={cn(
          'border-input flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border',
          checked && 'border-primary bg-primary text-primary-foreground',
        )}
      >
        {checked && <Check className="h-3 w-3" />}
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-2">
        {icon}
        <span className="truncate">{label}</span>
      </span>
    </button>
  )
}

function StatusIcon({ status }: { status: IssueBoardStatus }) {
  const Icon =
    status === 'done'
      ? CircleCheck
      : status === 'cancelled'
        ? X
        : status === 'blocked'
          ? PauseCircle
          : status === 'in_progress' || status === 'in_review'
            ? Clock3
            : Circle
  const color =
    status === 'backlog'
      ? 'text-muted-foreground'
      : status === 'todo'
        ? 'text-blue-500'
        : status === 'in_progress'
          ? 'text-yellow-500'
          : status === 'in_review'
            ? 'text-violet-500'
            : status === 'blocked'
              ? 'text-red-500'
              : status === 'cancelled'
                ? 'text-muted-foreground'
                : 'text-green-500'

  return <Icon className={cn('h-4 w-4 shrink-0', color)} />
}

function InlineEditableText({
  ariaLabel,
  emptyLabel,
  onCommit,
  value,
  variant,
}: {
  ariaLabel: string
  emptyLabel?: string
  onCommit: (value: string) => void
  value: string
  variant: 'title' | 'description'
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  const commit = () => {
    const nextValue = draft.trim()
    setEditing(false)
    if ((variant === 'description' || nextValue) && nextValue !== value) {
      onCommit(nextValue)
    }
  }

  if (editing) {
    if (variant === 'title') {
      return (
        <input
          autoFocus
          value={draft}
          onBlur={commit}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.currentTarget.blur()
            }
            if (event.key === 'Escape') {
              setDraft(value)
              setEditing(false)
            }
          }}
          className="border-border bg-background text-foreground focus-visible:ring-ring/40 w-full rounded-md border px-2 py-1.5 text-xl leading-tight font-semibold outline-none focus-visible:ring-2"
          aria-label={ariaLabel}
        />
      )
    }
    return (
      <Textarea
        autoFocus
        value={draft}
        onBlur={commit}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            event.currentTarget.blur()
          }
          if (event.key === 'Escape') {
            setDraft(value)
            setEditing(false)
          }
        }}
        className="border-border bg-background text-foreground focus-visible:ring-ring/40 mt-2 min-h-24 resize-y rounded-md border px-2 py-2 text-sm leading-relaxed outline-none focus-visible:ring-2"
        aria-label={ariaLabel}
        placeholder={emptyLabel}
      />
    )
  }

  const isEmpty = value.trim() === ''
  return (
    <button
      type="button"
      onClick={() => {
        setDraft(value)
        setEditing(true)
      }}
      className={cn(
        'hover:bg-muted/60 focus-visible:ring-ring/40 block w-full rounded-md px-2 py-1.5 text-left transition-colors outline-none focus-visible:ring-2',
        variant === 'title'
          ? 'text-foreground text-xl leading-tight font-semibold'
          : 'text-muted-foreground mt-2 min-h-16 text-sm leading-relaxed',
        isEmpty && 'text-muted-foreground/70',
      )}
      aria-label={ariaLabel}
    >
      {isEmpty ? emptyLabel : value}
    </button>
  )
}

function TodoDetailPanel({
  assignees,
  allIssues,
  issue,
  isCommentSubmitting,
  isRunning,
  labels,
  onAssignIssue,
  onAddComment,
  onAddRelation,
  onChangeParent,
  onCreateChild,
  onCreateLabel,
  onDeleteIssue,
  onMoveStatus,
  onOpenChange,
  onRemoveRelation,
  onRunIssue,
  onUpdateIssue,
}: {
  assignees: BoardAssignee[]
  allIssues: IssueBoardIssue[]
  issue: IssueBoardIssue | null
  isCommentSubmitting: boolean
  isRunning: boolean
  labels: IssueBoardLabel[]
  onAssignIssue: (issueId: string, assigneeAgentId: string | null) => void
  onAddComment: (issueId: string, body: string) => Promise<void> | void
  onAddRelation: (sourceId: string, targetId: string, relationType: 'blocks' | 'related') => void
  onChangeParent: (issueId: string, parentId: string | null) => void
  onCreateChild: (parentId: string, title: string, description: string) => void
  onCreateLabel: (label: IssueBoardLabel) => void
  onDeleteIssue: (issueId: string, cascadeChildren?: boolean) => Promise<void> | void
  onMoveStatus: (issueId: string, status: IssueBoardStatus) => void
  onOpenChange: (open: boolean) => void
  onRemoveRelation: (sourceId: string, targetId: string, relationType: 'blocks' | 'related') => void
  onRunIssue: (issueId: string) => void
  onUpdateIssue: (issueId: string, patch: Partial<IssueBoardIssue>) => void
}) {
  const [detailTab, setDetailTab] = useState<DetailTab>('chat')
  const [commentDraft, setCommentDraft] = useState('')
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  if (issue === null) return null

  const submitComment = () => {
    if (!commentDraft.trim() || isCommentSubmitting) return
    void Promise.resolve(onAddComment(issue.id, commentDraft))
      .then(() => {
        setCommentDraft('')
      })
      .catch(() => undefined)
  }
  const descendantCount = collectDescendantIssueIds(allIssues, issue.id).length
  const hasChildIssues = descendantCount > 0
  const requestDelete = () => {
    if (hasChildIssues) {
      setDeleteDialogOpen(true)
      return
    }
    void deleteIssue(false)
  }
  const deleteIssue = async (cascadeChildren: boolean) => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDeleteIssue(issue.id, cascadeChildren)
      setDeleteDialogOpen(false)
    } catch (error) {
      setDeleteError(getApiErrorMessage(error, { fallback: '작업을 삭제하지 못했습니다.' }))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/20"
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="작업 상세 닫기"
        onClick={() => onOpenChange(false)}
      />
      <aside className="bg-background relative flex h-full w-[min(760px,100vw)] flex-col border-l shadow-2xl">
        <header className="border-border/70 shrink-0 border-b px-5 py-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs font-medium">
              <StatusIcon status={issue.status} />
              <span className="text-muted-foreground font-mono">{issue.identifier}</span>
              <span className="rounded-full border px-2 py-0.5">
                {issueBoardStatusLabel(issue.status)}
              </span>
            </div>
            <Button
              type="button"
              aria-label="작업 실행"
              variant="outline"
              size="sm"
              className="h-8 gap-1.5"
              disabled={
                isRunning ||
                issue.live ||
                issue.status === 'backlog' ||
                issue.status === 'cancelled'
              }
              onClick={() => onRunIssue(issue.id)}
            >
              {isRunning ? (
                <Clock3 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <PlayCircle className="h-3.5 w-3.5" />
              )}
              {isRunning ? '실행 중' : '실행'}
            </Button>
            <Button
              type="button"
              aria-label="작업 삭제"
              variant="ghost"
              size="icon-sm"
              onClick={requestDelete}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              aria-label="작업 상세 닫기"
              variant="ghost"
              size="icon-sm"
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <InlineEditableText
            ariaLabel="작업 제목"
            value={issue.title}
            variant="title"
            onCommit={(title) => onUpdateIssue(issue.id, { title })}
          />
          <InlineEditableText
            ariaLabel="작업 설명"
            emptyLabel="작업 설명 추가..."
            value={issue.description}
            variant="description"
            onCommit={(description) => onUpdateIssue(issue.id, { description })}
          />
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <IssuePropertiesPanel
            assignees={assignees}
            allIssues={allIssues}
            issue={issue}
            labels={labels}
            onAssignIssue={onAssignIssue}
            onCreateLabel={onCreateLabel}
            onMoveStatus={onMoveStatus}
            onUpdateIssue={onUpdateIssue}
          />

          <div className="border-border/70 mt-5 border-t pt-4">
            <div className="mb-3 flex min-w-0 items-center gap-1 overflow-x-auto">
              <DetailTabButton
                active={detailTab === 'chat'}
                icon={<MessageSquare className="h-3.5 w-3.5" />}
                label={`댓글 ${issue.comments.length}`}
                onClick={() => setDetailTab('chat')}
              />
              <DetailTabButton
                active={detailTab === 'runs'}
                icon={<PlayCircle className="h-3.5 w-3.5" />}
                label={`실행 ${issue.runs.length}`}
                onClick={() => setDetailTab('runs')}
              />
              <DetailTabButton
                active={detailTab === 'activity'}
                icon={<Activity className="h-3.5 w-3.5" />}
                label="활동"
                onClick={() => setDetailTab('activity')}
              />
              <DetailTabButton
                active={detailTab === 'related'}
                icon={<ListTree className="h-3.5 w-3.5" />}
                label="관련"
                onClick={() => setDetailTab('related')}
              />
              <DetailTabButton
                active={detailTab === 'documents'}
                icon={<FileText className="h-3.5 w-3.5" />}
                label="문서"
                onClick={() => setDetailTab('documents')}
              />
              <DetailTabButton
                active={detailTab === 'products'}
                icon={<FolderKanban className="h-3.5 w-3.5" />}
                label="결과물"
                onClick={() => setDetailTab('products')}
              />
              <DetailTabButton
                active={detailTab === 'interactions'}
                icon={<MessageSquare className="h-3.5 w-3.5" />}
                label="확인"
                onClick={() => setDetailTab('interactions')}
              />
              <DetailTabButton
                active={detailTab === 'recovery'}
                icon={<RotateCcw className="h-3.5 w-3.5" />}
                label="복구"
                onClick={() => setDetailTab('recovery')}
              />
            </div>

            {detailTab === 'chat' && (
              <IssueChatThread
                commentDraft={commentDraft}
                comments={issue.comments}
                hint={commentSubmitHint(issue)}
                isSubmitting={isCommentSubmitting}
                onCommentDraftChange={setCommentDraft}
                onSubmit={submitComment}
                submitLabel={shouldResumeWorkFromComment(issue) ? '다시 실행' : '전송'}
              />
            )}
            {detailTab === 'runs' && <IssueRunLedger issue={issue} />}
            {detailTab === 'activity' && <IssueActivityTimeline issue={issue} />}
            {detailTab === 'related' && (
              <IssueRelatedPanel
                allIssues={allIssues}
                issue={issue}
                onAddRelation={onAddRelation}
                onChangeParent={onChangeParent}
                onCreateChild={onCreateChild}
                onRemoveRelation={onRemoveRelation}
              />
            )}
            {detailTab === 'documents' && <WorkDocumentsPanel workId={issue.id} />}
            {detailTab === 'products' && <WorkProductsPanel workId={issue.id} />}
            {detailTab === 'interactions' && <WorkInteractionsPanel workId={issue.id} />}
            {detailTab === 'recovery' && <WorkRecoveryPanel workId={issue.id} />}
          </div>
        </div>
      </aside>
      <DeleteIssueDialog
        deleteError={deleteError}
        deleting={deleting}
        descendantCount={descendantCount}
        issue={issue}
        open={deleteDialogOpen}
        onDeleteOnlyParent={() => void deleteIssue(false)}
        onDeleteWithChildren={() => void deleteIssue(true)}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteError(null)
          setDeleteDialogOpen(open)
        }}
      />
    </div>
  )
}

function DeleteIssueDialog({
  deleteError,
  deleting,
  descendantCount,
  issue,
  open,
  onDeleteOnlyParent,
  onDeleteWithChildren,
  onOpenChange,
}: {
  deleteError: string | null
  deleting: boolean
  descendantCount: number
  issue: IssueBoardIssue
  open: boolean
  onDeleteOnlyParent: () => void
  onDeleteWithChildren: () => void
  onOpenChange: (open: boolean) => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>하위 작업도 함께 삭제할까요?</AlertDialogTitle>
          <AlertDialogDescription>
            `{issue.identifier}` 작업 아래에 하위 작업 {descendantCount}개가 있습니다. 부모만
            삭제하면 하위 작업은 루트 작업으로 남고, 함께 삭제하면 하위 작업 전체가 삭제됩니다.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {deleteError ? <p className="text-destructive text-sm">{deleteError}</p> : null}
        <AlertDialogFooter>
          <Button variant="destructive" disabled={deleting} onClick={onDeleteWithChildren}>
            {deleting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                삭제 중
              </>
            ) : (
              '하위까지 삭제'
            )}
          </Button>
          <Button variant="outline" disabled={deleting} onClick={onDeleteOnlyParent}>
            부모만 삭제
          </Button>
          <AlertDialogCancel disabled={deleting}>취소</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function IssuePropertiesPanel({
  assignees,
  allIssues,
  issue,
  labels,
  onAssignIssue,
  onCreateLabel,
  onMoveStatus,
  onUpdateIssue,
}: {
  assignees: BoardAssignee[]
  allIssues: IssueBoardIssue[]
  issue: IssueBoardIssue
  labels: IssueBoardLabel[]
  onAssignIssue: (issueId: string, assigneeAgentId: string | null) => void
  onCreateLabel: (label: IssueBoardLabel) => void
  onMoveStatus: (issueId: string, status: IssueBoardStatus) => void
  onUpdateIssue: (issueId: string, patch: Partial<IssueBoardIssue>) => void
}) {
  const parent = issue.parentId ? allIssues.find((item) => item.id === issue.parentId) : null
  return (
    <section className="grid [grid-template-columns:7rem_minmax(0,1fr)] gap-x-5 gap-y-3 text-sm">
      <TodoProperty label="상태">
        <div className="flex flex-wrap gap-1.5">
          {ISSUE_BOARD_STATUSES.map((status) => (
            <Button
              key={status}
              type="button"
              variant={issue.status === status ? 'secondary' : 'outline'}
              size="sm"
              className="h-8 gap-1.5"
              onClick={() => onMoveStatus(issue.id, status)}
            >
              <StatusIcon status={status} />
              {issueBoardStatusLabel(status)}
            </Button>
          ))}
        </div>
      </TodoProperty>
      <TodoProperty label="담당">
        <AssigneePicker
          assignees={assignees}
          value={issue.assigneeAgentId}
          onChange={(assigneeAgentId) => onAssignIssue(issue.id, assigneeAgentId)}
        />
      </TodoProperty>
      <TodoProperty label="부모">
        <span className="text-muted-foreground text-sm">
          {parent ? `${parent.identifier} · ${parent.title}` : '루트 작업'}
        </span>
      </TodoProperty>
      <TodoProperty label="라벨">
        <LabelPicker
          labels={labels}
          value={issue.labels}
          onChange={(nextLabels) => onUpdateIssue(issue.id, { labels: nextLabels })}
          onCreateLabel={onCreateLabel}
        />
      </TodoProperty>
      <TodoProperty label="실행">
        <span className="inline-flex items-center gap-1.5">
          <PlayCircle className="h-3.5 w-3.5" />
          {issue.live ? '실행 중' : issue.status === 'done' ? '완료' : '대기'}
        </span>
      </TodoProperty>
      {issue.blockedBy.length > 0 && (
        <TodoProperty label="차단 원인">
          <div className="flex flex-col gap-1">
            {issue.blockedBy.map((item) => (
              <RelatedIssuePill key={item.id} item={item} />
            ))}
          </div>
        </TodoProperty>
      )}
      <TodoProperty label="시작">
        {issue.startedAt ? formatRelativeTime(issue.startedAt) : '아직 시작 전'}
      </TodoProperty>
      <TodoProperty label="완료">
        {issue.completedAt ? formatRelativeTime(issue.completedAt) : '미완료'}
      </TodoProperty>
      <TodoProperty label="생성">{formatRelativeTime(issue.createdAt)}</TodoProperty>
      <TodoProperty label="수정">{formatRelativeTime(issue.updatedAt)}</TodoProperty>
    </section>
  )
}

function DetailTabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean
  icon: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-3 text-sm transition-colors',
        active
          ? 'bg-accent text-foreground'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
      )}
      onClick={onClick}
    >
      {icon}
      {label}
    </button>
  )
}

function IssueChatThread({
  commentDraft,
  comments,
  hint,
  isSubmitting,
  onCommentDraftChange,
  onSubmit,
  submitLabel,
}: {
  commentDraft: string
  comments: IssueBoardIssue['comments']
  hint: string
  isSubmitting: boolean
  onCommentDraftChange: (value: string) => void
  onSubmit: () => void
  submitLabel: string
}) {
  return (
    <div className="space-y-3">
      <div className="max-h-[360px] space-y-3 overflow-y-auto pr-1">
        {comments.length === 0 ? (
          <div className="text-muted-foreground rounded-md border p-4 text-sm">
            이 작업에 아직 댓글이 없습니다.
          </div>
        ) : (
          comments.map((comment) => (
            <div key={comment.id} className="rounded-md border p-3">
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className="font-medium">{comment.authorName}</span>
                <span className="text-muted-foreground">
                  {commentAuthorLabel(comment.authorType)}
                </span>
                <span className="text-muted-foreground ml-auto">
                  {formatRelativeTime(comment.createdAt)}
                </span>
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{comment.body}</p>
            </div>
          ))
        )}
        {isSubmitting && commentDraft.trim().length > 0 && (
          <div className="bg-muted/20 rounded-md border border-dashed p-3 opacity-80">
            <div className="mb-1 flex items-center gap-2 text-xs">
              <span className="font-medium">사용자</span>
              <span className="text-muted-foreground">전송 중</span>
              <Loader2 className="text-muted-foreground ml-auto h-3.5 w-3.5 animate-spin" />
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{commentDraft.trim()}</p>
          </div>
        )}
      </div>
      <div className="rounded-md border p-2">
        <Textarea
          value={commentDraft}
          onChange={(event) => onCommentDraftChange(event.target.value)}
          placeholder="실행 시 참고할 작업 댓글 입력..."
          className="min-h-20 resize-none border-0 p-2 shadow-none focus-visible:ring-0"
          disabled={isSubmitting}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
              event.preventDefault()
              onSubmit()
            }
          }}
        />
        <div className="flex items-center justify-between gap-2 px-2 pb-1">
          <span className="text-muted-foreground min-w-0 text-xs">
            {isSubmitting ? '댓글 전송 중...' : hint}
          </span>
          <Button
            type="button"
            size="sm"
            className="h-8 shrink-0 gap-1.5"
            disabled={isSubmitting || commentDraft.trim().length === 0}
            onClick={onSubmit}
          >
            {isSubmitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            {isSubmitting ? '전송 중' : submitLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

function IssueRunLedger({ issue }: { issue: IssueBoardIssue }) {
  return (
    <div className="space-y-2">
      {issue.runs.length === 0 ? (
        <div className="text-muted-foreground rounded-md border p-4 text-sm">
          아직 연결된 실행이 없습니다.
        </div>
      ) : (
        issue.runs.map((run) => (
          <div key={run.id} className="rounded-md border p-3 text-sm">
            <div className="flex min-w-0 items-center gap-2">
              <RunStatusDot status={run.status} />
              <span className="min-w-0 flex-1 truncate font-medium">{run.title}</span>
              <span className="rounded-full border px-2 py-0.5 text-xs">
                {runStatusLabel(run.status)}
              </span>
            </div>
            <p className="text-muted-foreground mt-2 text-xs leading-relaxed">{run.summary}</p>
            <div className="text-muted-foreground mt-2 flex flex-wrap gap-2 text-xs">
              <span>시작 {formatRelativeTime(run.startedAt)}</span>
              <span>완료 {run.finishedAt ? formatRelativeTime(run.finishedAt) : '진행 중'}</span>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

function IssueActivityTimeline({ issue }: { issue: IssueBoardIssue }) {
  const activities = [
    {
      id: 'created',
      title: '작업 생성',
      body: `${issue.identifier} 작업이 생성되었습니다.`,
      at: issue.createdAt,
    },
    ...issue.runs.map((run) => ({
      id: run.id,
      title: `실행 ${runStatusLabel(run.status)}`,
      body: run.summary,
      at: run.finishedAt ?? run.startedAt,
    })),
    ...issue.comments.map((comment) => ({
      id: comment.id,
      title: `${comment.authorName} 메시지`,
      body: comment.body,
      at: comment.createdAt,
    })),
  ].sort((left, right) => new Date(right.at).getTime() - new Date(left.at).getTime())

  return (
    <div className="space-y-2">
      {activities.map((activity) => (
        <div key={activity.id} className="flex gap-3 rounded-md border p-3 text-sm">
          <span className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate font-medium">{activity.title}</span>
              <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                {formatRelativeTime(activity.at)}
              </span>
            </div>
            <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">{activity.body}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function TodoProperty({ children, label }: { children: ReactNode; label: string }) {
  return (
    <>
      <div className="text-muted-foreground flex min-h-9 items-center text-xs">{label}</div>
      <div className="text-foreground flex min-h-9 min-w-0 items-center gap-2">{children}</div>
    </>
  )
}

function LabelPicker({
  labels,
  value,
  onChange,
  onCreateLabel,
}: {
  labels: IssueBoardLabel[]
  value: string[]
  onChange: (labelIds: string[]) => void
  onCreateLabel: (label: IssueBoardLabel) => void
}) {
  const [search, setSearch] = useState('')
  const [newLabelName, setNewLabelName] = useState('')
  const [newLabelColor, setNewLabelColor] = useState('#14b8a6')
  const selectedLabels = resolveIssueLabels(value, labels)
  const normalizedSearch = search.trim().toLowerCase()
  const visibleLabels = labels.filter((label) =>
    normalizedSearch ? label.name.toLowerCase().includes(normalizedSearch) : true,
  )
  const toggleLabel = (labelId: string) => onChange(toggleValue(value, labelId))
  const addLabel = () => {
    const name = newLabelName.trim()
    if (!name) return
    const existing = labels.find((label) => label.name.toLowerCase() === name.toLowerCase())
    if (existing) {
      if (!value.includes(existing.id)) onChange([...value, existing.id])
      setNewLabelName('')
      setSearch('')
      return
    }
    const label = {
      id: createLabelIdentifier(name, labels),
      name: name.slice(0, 48),
      color: isHexColor(newLabelColor) ? newLabelColor : '#14b8a6',
    }
    onCreateLabel(label)
    onChange([...value, label.id])
    setNewLabelName('')
    setSearch('')
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="border-input bg-input-background hover:bg-accent/50 flex min-h-9 w-full max-w-md items-center justify-between gap-3 rounded-md border px-3 py-1.5 text-sm"
        >
          {selectedLabels.length > 0 ? (
            <span className="flex min-w-0 flex-wrap gap-1">
              {selectedLabels.slice(0, 3).map((label) => (
                <LabelPill key={label.id} label={label} />
              ))}
              {selectedLabels.length > 3 && (
                <span className="text-muted-foreground text-xs">+{selectedLabels.length - 3}</span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground inline-flex items-center gap-1.5">
              <Tag className="h-3.5 w-3.5" />
              라벨 없음
            </span>
          )}
          <ChevronDown className="text-muted-foreground h-4 w-4 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="border-border/70 border-b p-2">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="라벨 검색..."
            className="h-8"
          />
        </div>
        <div className="max-h-48 space-y-0.5 overflow-y-auto p-1">
          {visibleLabels.length === 0 ? (
            <div className="text-muted-foreground px-2 py-3 text-xs">검색 결과 없음</div>
          ) : (
            visibleLabels.map((label) => {
              const selected = value.includes(label.id)
              return (
                <button
                  key={label.id}
                  type="button"
                  className={cn(
                    'hover:bg-accent/50 flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm',
                    selected && 'bg-accent text-accent-foreground',
                  )}
                  onClick={() => toggleLabel(label.id)}
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: label.color }}
                  />
                  <span className="min-w-0 flex-1 truncate">{label.name}</span>
                  {selected && <Check className="h-3.5 w-3.5 shrink-0" />}
                </button>
              )
            })
          )}
        </div>
        <div className="border-border/70 space-y-2 border-t p-2">
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={newLabelColor}
              onChange={(event) => setNewLabelColor(event.target.value)}
              className="h-8 w-9 shrink-0 rounded border bg-transparent p-0"
              aria-label="새 라벨 색상"
            />
            <Input
              value={newLabelName}
              onChange={(event) => setNewLabelName(event.target.value)}
              placeholder="새 라벨"
              className="h-8"
              maxLength={48}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 w-full gap-1.5"
            disabled={!newLabelName.trim()}
            onClick={addLabel}
          >
            <Plus className="h-3.5 w-3.5" />
            라벨 만들기
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function LabelPill({ compact = false, label }: { compact?: boolean; label: IssueBoardLabel }) {
  return (
    <span
      className={cn(
        'border-border bg-background/70 text-muted-foreground inline-flex max-w-full shrink-0 items-center gap-1 rounded-full border font-medium',
        compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs',
      )}
      title={label.name}
    >
      <span
        className={cn('shrink-0 rounded-full', compact ? 'h-1.5 w-1.5' : 'h-2 w-2')}
        style={{ backgroundColor: label.color }}
      />
      <span className="truncate">{label.name}</span>
    </span>
  )
}

function AssigneePicker({
  assignees,
  value,
  onChange,
}: {
  assignees: BoardAssignee[]
  value: string | null
  onChange: (assigneeAgentId: string | null) => void
}) {
  const options: Array<BoardAssignee | { id: null; name: string; icon: typeof UserRound }> = [
    { id: null, name: '담당자 없음', icon: UserRound },
    ...assignees,
  ]
  const selected = options.find((option) => option.id === value) ?? options[0]
  const SelectedIcon = selected.icon

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="border-input bg-input-background hover:bg-accent/50 flex h-9 w-full items-center justify-between gap-3 rounded-md border px-3 text-sm"
        >
          <span className="flex min-w-0 items-center gap-2">
            <SelectedIcon className="h-4 w-4 shrink-0" />
            <span className="truncate">{selected.name}</span>
          </span>
          <ChevronDown className="text-muted-foreground h-4 w-4 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-1">
        <div className="max-h-60 overflow-y-auto">
          {options.map((option) => {
            const OptionIcon = option.icon
            const selectedOption = option.id === value
            return (
              <button
                key={option.id ?? '__unassigned'}
                type="button"
                className={cn(
                  'hover:bg-accent/50 flex h-9 w-full items-center gap-2 rounded-sm px-2 text-sm',
                  selectedOption && 'bg-accent text-accent-foreground',
                )}
                onClick={() => onChange(option.id)}
              >
                <OptionIcon className="h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate text-left">{option.name}</span>
                {selectedOption && <Check className="h-4 w-4 shrink-0" />}
              </button>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function RunStatusDot({ status }: { status: IssueBoardIssue['runs'][number]['status'] }) {
  const color =
    status === 'completed'
      ? 'bg-green-500'
      : status === 'failed'
        ? 'bg-red-500'
        : status === 'waiting'
          ? 'bg-amber-500'
          : status === 'running'
            ? 'bg-cyan-500'
            : 'bg-muted-foreground'

  return <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', color)} />
}
