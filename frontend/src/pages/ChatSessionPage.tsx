import { AlertCircle, ListTodo, Loader2, RefreshCw, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router'
import { ChatComposer, type ChatAttachmentPayload } from '@/components/chat/ChatComposer'
import { ChatEmptyState } from '@/components/chat/ChatEmptyState'
import { ChatMessageList } from '@/components/chat/ChatMessageList'
import type { ChatConnectionState } from '@/components/chat/chatTypes'
import { PrototypePanel } from '@/components/prototype/PrototypePanel'
import { StepRunActivityPanel } from '@/components/taskRuns/StepRunActivityPanel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { issueBoardStatusLabel } from '@/components/sessionWorkspace/work/model'
import type {
  AiRealtimeAuthStatus,
  AiRealtimeConnectionStatus,
  JsonObject,
} from '@/realtime/aiRealtimeTypes'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useAuthStore } from '@/store/useAuthStore'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import { useUIStore } from '@/store/useUIStore'
import { useWorkStore } from '@/store/useWorkStore'
import {
  getString as getJsonString,
  toJsonObject,
} from '@/components/sessionWorkspace/sessionWorkspaceUtils'
import type { WorkItem, WorkStatus } from '@/types/work'
import {
  isInternalStepAnchorEvent,
  isInternalStepAnchorStepRun,
  isLiveTaskRunStatus,
  toActivityItemView,
  toTaskRunSummaryView,
} from '@/utils/taskRunStatusView'
import { shouldHydrateTaskRunOnSessionOpen } from '@/utils/taskRunHydration'

type LoadState = 'loading' | 'ready' | 'error'

const EMPTY_MESSAGES: never[] = []

export function ChatSessionPage() {
  const { sessionId = '' } = useParams()
  const location = useLocation()
  const [selectedTaskRunId, setSelectedTaskRunId] = useState<string | undefined>()
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [selectedWorkId, setSelectedWorkId] = useState<string | null>(null)
  const [composerDraft, setComposerDraft] = useState<string | null>(null)
  const [workPickerOpen, setWorkPickerOpen] = useState(false)
  const [workSearch, setWorkSearch] = useState('')
  const [workStatusMessage, setWorkStatusMessage] = useState<string | null>(null)
  const [focusedTaskRunTarget, setFocusedTaskRunTarget] = useState<
    { taskRunId: string; requestId: number } | undefined
  >()
  const focusRequestIdRef = useRef(0)
  const consumedWorkRouteRef = useRef<string | null>(null)
  const hydratedTaskRunIdsRef = useRef<Set<string>>(new Set())
  const hydratingTaskRunIdsRef = useRef<Set<string>>(new Set())
  const hydrationGenerationRef = useRef(0)
  const loadGenerationRef = useRef(0)

  const commandClient = useAiRealtimeStore((state) => state.commandClient)
  const socketClient = useAiRealtimeStore((state) => state.socketClient)
  const connectionStatus = useAiRealtimeStore((state) => state.connectionStatus)
  const authStatus = useAiRealtimeStore((state) => state.authStatus)
  const authenticatedReady = useAiRealtimeStore((state) => state.authenticatedReady)
  const realtimeError = useAiRealtimeStore((state) => state.lastError)
  const subscribeTask = useAiRealtimeStore((state) => state.subscribeTask)
  const accessToken = useAuthStore((state) => state.accessToken)
  const activityOpen = useUIStore((state) => state.taskActivityPanelOpen)
  const setActivityOpen = useUIStore((state) => state.setTaskActivityPanelOpen)
  const setSessionWorkspaceCollapsed = useUIStore((state) => state.setSessionWorkspaceCollapsed)
  const prototypePanelSessionId = useUIStore((state) => state.prototypePanelSessionId)
  const prototypePanelOpenRequest = useUIStore((state) => state.prototypePanelOpenRequest)
  const requestPrototypePanel = useUIStore((state) => state.requestPrototypePanel)
  const prototypeAutoCollapsedSessionIdsRef = useRef<Set<string>>(new Set())

  const storeMessages = useChatStore((state) =>
    sessionId === '' ? EMPTY_MESSAGES : (state.messagesBySessionId[sessionId] ?? EMPTY_MESSAGES),
  )
  const isLoadingMessages = useChatStore((state) =>
    sessionId === '' ? false : state.loadingSessionIds[sessionId] === true,
  )
  const chatError = useChatStore((state) => state.lastError)
  const currentSession = useChatStore((state) =>
    sessionId === '' ? undefined : state.sessionsById[sessionId],
  )
  const sessionMainAgentDraft = useSessionStore((state) =>
    sessionId === '' ? undefined : state.mainAgentNameDraftBySessionId[sessionId],
  )
  // 어시스턴트 메시지에 표시할 이름 — 세션별 인라인 편집 draft → metadata.ui.agentName → 기본값
  const mainAgentName = useMemo(() => {
    const draft = sessionMainAgentDraft?.trim()
    if (draft) return draft
    if (currentSession) {
      const metadata = toJsonObject(currentSession.metadata)
      const uiMetadata = toJsonObject(metadata.ui)
      const stored = getJsonString(uiMetadata, 'agentName')
      if (stored && stored.trim() !== '') return stored
    }
    return '팀장 에이전트'
  }, [currentSession, sessionMainAgentDraft])
  const fetchMessages = useChatStore((state) => state.fetchMessages)
  const addExternalTaskPlaceholder = useChatStore((state) => state.addExternalTaskPlaceholder)
  const sendMessage = useChatStore((state) => state.sendMessage)
  const fetchSessionWork = useWorkStore((state) => state.fetchSessionWork)
  const workItems = useWorkStore((state) =>
    sessionId === '' ? EMPTY_WORK_ITEMS : (state.itemsBySessionId[sessionId] ?? EMPTY_WORK_ITEMS),
  )
  const workLoading = useWorkStore((state) =>
    sessionId === '' ? false : state.loadingBySessionId[sessionId] === true,
  )

  const taskRunsById = useTaskRunStore((state) => state.taskRunsById)
  const stepRunsById = useTaskRunStore((state) => state.stepRunsById)
  const eventsByTaskRunId = useTaskRunStore((state) => state.eventsByTaskRunId)
  const activityItemsByTaskRunId = useTaskRunStore((state) => state.activityItemsByTaskRunId)
  const lastSequenceByTaskRunId = useTaskRunStore((state) => state.lastSequenceByTaskRunId)
  const taskRunError = useTaskRunStore((state) => state.lastError)
  const fetchActiveTaskRuns = useTaskRunStore((state) => state.fetchActiveTaskRuns)
  const fetchSnapshot = useTaskRunStore((state) => state.fetchSnapshot)
  const replayEvents = useTaskRunStore((state) => state.replayEvents)

  const connectionState = useMemo(
    () => toChatConnectionState(connectionStatus, authStatus),
    [authStatus, connectionStatus],
  )
  const messages = useMemo(
    () =>
      storeMessages.filter((message) => message.role === 'user' || message.role === 'assistant'),
    [storeMessages],
  )
  const taskRunIds = useMemo(() => {
    const ids = new Set<string>()

    messages.forEach((message) => {
      if (message.taskRunId !== undefined) {
        ids.add(message.taskRunId)
      }
    })

    Object.values(taskRunsById).forEach((taskRun) => {
      if (taskRun.session_id === sessionId) {
        ids.add(taskRun.task_run_id)
      }
    })

    return [...ids]
  }, [messages, sessionId, taskRunsById])
  const latestMessageTaskRunId = useMemo(
    () => [...messages].reverse().find((message) => message.taskRunId)?.taskRunId,
    [messages],
  )
  const taskRunIdKey = taskRunIds.join('|')
  const activitiesByTaskRunId = useMemo(
    () =>
      Object.fromEntries(
        taskRunIds.map((taskRunId) => [
          taskRunId,
          activityItemsByTaskRunId[taskRunId] ??
            (eventsByTaskRunId[taskRunId] ?? [])
              .filter((event) => !isInternalStepAnchorEvent(event))
              .map(toActivityItemView),
        ]),
      ),
    [activityItemsByTaskRunId, eventsByTaskRunId, taskRunIds],
  )
  const stepRunsByTaskRunId = useMemo(
    () =>
      Object.fromEntries(
        taskRunIds.map((taskRunId) => [
          taskRunId,
          Object.values(stepRunsById)
            .filter((stepRun) => stepRun.task_run_id === taskRunId)
            .filter((stepRun) => !isInternalStepAnchorStepRun(stepRun))
            .sort(compareChatStepRuns),
        ]),
      ),
    [stepRunsById, taskRunIds],
  )
  const taskRunSummariesById = useMemo(
    () =>
      Object.fromEntries(
        taskRunIds.map((taskRunId) => [
          taskRunId,
          toTaskRunSummaryView(taskRunsById[taskRunId], eventsByTaskRunId[taskRunId] ?? []),
        ]),
      ),
    [eventsByTaskRunId, taskRunIds, taskRunsById],
  )
  const isPendingSession = sessionId.startsWith('pending_session_')

  const loadSessionData = useCallback(async () => {
    if (!sessionId) return
    if (isPendingSession) {
      // 첫 메시지 전송 직후에는 서버 세션 id가 아직 없어서 조회 명령을 보내지 않는다.
      // optimistic 메시지가 들어간 pending 세션을 그대로 렌더링하고 accepted 후 실제 세션으로 교체한다.
      setLoadState('ready')
      setErrorMessage(null)
      return
    }

    if (!authenticatedReady || commandClient === null) {
      setLoadState(
        shouldWaitForRealtime(connectionStatus, authStatus, realtimeError, accessToken)
          ? 'loading'
          : 'error',
      )
      setErrorMessage(
        getRealtimeUnavailableMessage(connectionStatus, authStatus, realtimeError, accessToken),
      )
      return
    }

    const loadGeneration = ++loadGenerationRef.current
    const requestedSessionId = sessionId

    setLoadState('loading')
    setErrorMessage(null)
    setActivityOpen(false)

    try {
      await Promise.all([
        fetchMessages(requestedSessionId),
        fetchActiveTaskRuns(requestedSessionId),
        fetchSessionWork(requestedSessionId).catch(() => []),
      ])
      if (loadGeneration !== loadGenerationRef.current || requestedSessionId !== sessionId) {
        return
      }
      setLoadState('ready')
    } catch (error) {
      if (loadGeneration !== loadGenerationRef.current || requestedSessionId !== sessionId) {
        return
      }
      setLoadState('error')
      setErrorMessage(error instanceof Error ? error.message : '세션 메시지를 불러오지 못했습니다.')
    }
  }, [
    authStatus,
    authenticatedReady,
    commandClient,
    connectionStatus,
    accessToken,
    fetchActiveTaskRuns,
    fetchSessionWork,
    fetchMessages,
    isPendingSession,
    realtimeError,
    setActivityOpen,
    sessionId,
  ])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadSessionData()
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [loadSessionData])

  useEffect(() => {
    loadGenerationRef.current += 1
    hydrationGenerationRef.current += 1
    hydratedTaskRunIdsRef.current.clear()
    hydratingTaskRunIdsRef.current.clear()
  }, [sessionId])

  useEffect(() => {
    if (
      !authenticatedReady ||
      commandClient === null ||
      socketClient === null ||
      taskRunIds.length === 0
    ) {
      return
    }

    const hydrationGeneration = hydrationGenerationRef.current
    let cancelled = false

    taskRunIds.forEach((taskRunId) => {
      if (
        hydratedTaskRunIdsRef.current.has(taskRunId) ||
        hydratingTaskRunIdsRef.current.has(taskRunId)
      ) {
        return
      }

      const taskRun = taskRunsById[taskRunId]
      const taskRunEvents = eventsByTaskRunId[taskRunId] ?? []
      const latestTaskRunEvent = taskRunEvents.at(-1)
      const latestTaskRunStatus =
        latestTaskRunEvent?.status ?? latestTaskRunEvent?.event_type ?? taskRun?.status
      const hasStreamingMessage = messages.some(
        (message) =>
          message.taskRunId === taskRunId &&
          message.role === 'assistant' &&
          message.status === 'streaming',
      )
      const hasRuntimeState =
        taskRun !== undefined || taskRunEvents.length > 0 || hasStreamingMessage

      if (
        !shouldHydrateTaskRunOnSessionOpen({
          hasRuntimeState,
          isLatestMessageTaskRun: taskRunId === latestMessageTaskRunId,
        })
      ) {
        // 과거 완료 메시지까지 모두 snapshot/replay 하면 WebSocket command가 폭주해서
        // 현재 답변의 step event가 뒤로 밀린다. 다만 최신 답변은 페이지 복귀 직후
        // 채팅 아래 진행 상태를 복원해야 하므로 snapshot/replay 대상에 포함한다.
        return
      }

      if (hasStreamingMessage || isLiveTaskRunStatus(latestTaskRunStatus)) {
        try {
          // 실행 중인 답변은 snapshot command로 UI를 막지 않고 live event 구독만 유지한다.
          subscribeTask(taskRunId, lastSequenceByTaskRunId[taskRunId])
        } catch (error) {
          console.error(error)
        }
        return
      }

      hydratingTaskRunIdsRef.current.add(taskRunId)
      // snapshot/replay merge는 store를 갱신해서 이 effect를 다시 실행시킬 수 있다.
      // 그래서 요청 성공 뒤가 아니라 시작 시점에 먼저 표시해 같은 taskRunId 중복 조회를 막는다.
      hydratedTaskRunIdsRef.current.add(taskRunId)
      void (async () => {
        try {
          const snapshot = await fetchSnapshot(taskRunId)
          const hydratedTaskRun = useTaskRunStore.getState().taskRunsById[taskRunId]
          if (
            cancelled ||
            hydrationGeneration !== hydrationGenerationRef.current ||
            (hydratedTaskRun?.session_id !== undefined && hydratedTaskRun.session_id !== sessionId)
          ) {
            return
          }
          const snapshotHasEvents = Array.isArray(snapshot?.events) && snapshot.events.length > 0
          if (!snapshotHasEvents) {
            // snapshot이 event 목록을 함께 주는 경우에는 replay를 한 번 더 호출하지 않는다.
            // 완료 직후 agent loop가 아직 정리 중이면 replay command 응답이 늦어져 콘솔 timeout이 생길 수 있다.
            await replayEvents(taskRunId, lastSequenceByTaskRunId[taskRunId])
          }
          if (
            cancelled ||
            hydrationGeneration !== hydrationGenerationRef.current ||
            !useAiRealtimeStore.getState().authenticatedReady
          ) {
            return
          }
          // replay/snapshot merge가 끝난 뒤 store의 최신 sequence를 다시 읽어야
          // 구독 기준점이 오래된 closure 값에 묶이지 않는다.
          const latestSequence = useTaskRunStore.getState().lastSequenceByTaskRunId[taskRunId]
          subscribeTask(taskRunId, latestSequence)
          hydratedTaskRunIdsRef.current.add(taskRunId)
        } catch (error) {
          if (cancelled || hydrationGeneration !== hydrationGenerationRef.current) {
            return
          }
          console.error(error)
          hydratedTaskRunIdsRef.current.delete(taskRunId)
          setErrorMessage('답변 진행 상태를 불러오지 못했습니다.')
        } finally {
          hydratingTaskRunIdsRef.current.delete(taskRunId)
        }
      })()
    })

    return () => {
      cancelled = true
    }
  }, [
    authenticatedReady,
    commandClient,
    eventsByTaskRunId,
    fetchSnapshot,
    lastSequenceByTaskRunId,
    messages,
    replayEvents,
    sessionId,
    socketClient,
    subscribeTask,
    latestMessageTaskRunId,
    taskRunIdKey,
    taskRunIds,
    taskRunsById,
  ])

  const handleSend = async (content: string, attachments: ChatAttachmentPayload[] = []) => {
    if (!sessionId || isSending) return
    setComposerDraft(null)

    if (!authenticatedReady || commandClient === null) {
      setLoadState(
        shouldWaitForRealtime(connectionStatus, authStatus, realtimeError, accessToken)
          ? 'loading'
          : 'error',
      )
      setErrorMessage(
        getRealtimeUnavailableMessage(connectionStatus, authStatus, realtimeError, accessToken),
      )
      return
    }

    setIsSending(true)
    setErrorMessage(null)
    try {
      let selectedWork = selectedWorkId
        ? workItems.find((work) => work.workId === selectedWorkId)
        : undefined
      if (!selectedWork) {
        const requestedIdentifier = extractWorkIdentifier(content)
        if (requestedIdentifier) {
          const latestItems = await fetchSessionWork(sessionId)
          selectedWork = latestItems.find(
            (work) => normalizeWorkIdentifier(work.identifier) === requestedIdentifier,
          )
          if (!selectedWork) {
            const message = `${requestedIdentifier} 작업을 찾지 못했습니다. 작업 보드에서 번호를 확인해 주세요.`
            setErrorMessage(message)
            setWorkStatusMessage(message)
            return
          }
          setSelectedWorkId(selectedWork.workId)
        }
      }
      const workPayload: JsonObject | undefined = selectedWork
        ? {
            workId: selectedWork.workId,
            workIdentifier: selectedWork.identifier,
            workTitle: selectedWork.title,
            workAssigneeAgentId: selectedWork.assigneeAgentId ?? 'CEO',
          }
        : undefined
      const attachmentPayload = buildAttachmentInputPayload(attachments)

      await sendMessage({
        sessionId,
        content: formatMessageWithAttachmentSummary(content, attachments),
        inputPayload:
          workPayload || attachmentPayload
            ? {
                ...(workPayload ?? {}),
                ...(attachmentPayload ?? {}),
              }
            : undefined,
      })
      setLoadState('ready')
      if (selectedWork) {
        setWorkStatusMessage(`${selectedWork.identifier} 작업으로 실행을 시작했습니다.`)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '메시지 전송에 실패했습니다.')
    } finally {
      setIsSending(false)
    }
  }

  const openWorkPicker = () => {
    if (!sessionId) return
    setWorkPickerOpen(true)
    void fetchSessionWork(sessionId).catch((error) => {
      setWorkStatusMessage(
        error instanceof Error ? error.message : '작업 목록을 불러오지 못했습니다.',
      )
    })
  }

  const selectedWork = selectedWorkId
    ? workItems.find((work) => work.workId === selectedWorkId)
    : undefined
  const selectedWorkLabel = selectedWork
    ? `${selectedWork.identifier} · ${selectedWork.title}`
    : null
  const latestLinkedWorkEvent = useMemo(
    () => findLatestLinkedWorkEvent(eventsByTaskRunId, taskRunIds),
    [eventsByTaskRunId, taskRunIds],
  )

  useEffect(() => {
    if (!sessionId || latestLinkedWorkEvent === undefined) return
    void fetchSessionWork(sessionId).catch(() => undefined)
  }, [fetchSessionWork, latestLinkedWorkEvent, sessionId])

  useEffect(() => {
    if (!sessionId) return
    const params = new URLSearchParams(location.search)
    const workId = params.get('workId')
    if (!workId) return
    const draft = params.get('draft') || '이 작업을 이어서 진행해.'
    const routeKey = `${sessionId}:${workId}:${draft}`
    if (consumedWorkRouteRef.current === routeKey) return
    consumedWorkRouteRef.current = routeKey
    const work = workItems.find((item) => item.workId === workId)
    setSelectedWorkId(workId)
    setComposerDraft(draft)
    setWorkStatusMessage(
      work
        ? `${work.identifier} 작업을 이번 메시지에 연결합니다.`
        : '작업을 이번 메시지에 연결합니다.',
    )
  }, [location.search, sessionId, workItems])

  const handleOpenTaskRun = (taskRunId: string) => {
    setSelectedTaskRunId(taskRunId)
    setActivityOpen(true)
  }

  const handleFocusTaskRunMessage = (taskRunId: string) => {
    focusRequestIdRef.current += 1
    setFocusedTaskRunTarget({ taskRunId, requestId: focusRequestIdRef.current })
  }

  const activeSessionTaskRunId =
    typeof currentSession?.active_task_run_id === 'string'
      ? currentSession.active_task_run_id
      : undefined
  const visibleTaskRunId =
    latestLinkedWorkEvent?.taskRunId ??
    selectedWork?.activeRunId ??
    selectedWork?.latestRunId ??
    activeSessionTaskRunId ??
    latestMessageTaskRunId
  const visibleWork =
    selectedWork ?? findWorkByTaskRunId(workItems, visibleTaskRunId) ?? latestLinkedWorkEvent?.work
  const visibleTaskRunSummary =
    visibleTaskRunId === undefined ? undefined : taskRunSummariesById[visibleTaskRunId]
  const visibleTaskRunStatus =
    visibleTaskRunId === undefined ? undefined : taskRunsById[visibleTaskRunId]?.status
  const hasActiveChatTurn =
    activeSessionTaskRunId !== undefined ||
    (visibleTaskRunStatus !== undefined && isLiveTaskRunStatus(visibleTaskRunStatus)) ||
    messages.some(
      (message) =>
        message.status === 'optimistic' ||
        message.status === 'streaming' ||
        message.status === 'waiting',
    )
  const prototypePanelRequested = prototypePanelSessionId === sessionId

  const handlePrototypeArtifactVisible = useCallback(() => {
    requestPrototypePanel(sessionId)
    if (!prototypeAutoCollapsedSessionIdsRef.current.has(sessionId)) {
      prototypeAutoCollapsedSessionIdsRef.current.add(sessionId)
      setSessionWorkspaceCollapsed(true)
    }
  }, [requestPrototypePanel, sessionId, setSessionWorkspaceCollapsed])

  useEffect(() => {
    if (
      !sessionId ||
      visibleTaskRunId === undefined ||
      visibleTaskRunStatus === undefined ||
      !isLiveTaskRunStatus(visibleTaskRunStatus)
    ) {
      return
    }
    const hasAssistantForTask = messages.some(
      (message) => message.role === 'assistant' && message.taskRunId === visibleTaskRunId,
    )
    if (hasAssistantForTask) {
      return
    }
    addExternalTaskPlaceholder(sessionId, visibleTaskRunId)
  }, [addExternalTaskPlaceholder, messages, sessionId, visibleTaskRunId, visibleTaskRunStatus])

  const isStreaming = messages.some(
    (message) => message.role === 'assistant' && message.status === 'streaming',
  )
  const isComposerDisabled =
    connectionState === 'auth-expired' ||
    !authenticatedReady ||
    commandClient === null ||
    hasActiveChatTurn
  const loading = (loadState === 'loading' || isLoadingMessages) && messages.length === 0
  const displayErrorMessage =
    errorMessage ?? (loadState === 'error' ? null : (chatError ?? taskRunError))

  return (
    <main className="bg-background flex min-w-0 flex-1 overflow-hidden">
      <section className="flex min-w-0 flex-1 flex-col">
        {displayErrorMessage && loadState !== 'error' && (
          <button
            type="button"
            onClick={() => setActivityOpen(true)}
            aria-label="오류 상세를 활동 패널에서 확인"
            className="border-border bg-muted/40 text-muted-foreground hover:text-foreground flex items-center justify-center gap-2 border-b px-4 py-2 text-xs transition-colors"
          >
            <AlertCircle className="h-3.5 w-3.5" />
            <span>{displayErrorMessage}</span>
          </button>
        )}
        {visibleWork && (
          <ChatWorkStatusBar
            work={visibleWork}
            taskRunId={visibleTaskRunId}
            taskRunStatusText={visibleTaskRunSummary?.statusText}
            onOpenTaskRun={visibleTaskRunId ? () => handleOpenTaskRun(visibleTaskRunId) : undefined}
          />
        )}
        {loading ? (
          <div className="text-muted-foreground flex min-h-0 flex-1 items-center justify-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            메시지를 불러오는 중입니다.
          </div>
        ) : loadState === 'error' && messages.length === 0 ? (
          <div className="flex min-h-0 flex-1 items-center justify-center px-6">
            <div className="border-border bg-card max-w-md rounded-lg border p-5 text-center shadow-sm">
              <AlertCircle className="text-destructive mx-auto h-6 w-6" />
              <h2 className="text-foreground mt-3 text-sm font-semibold">
                대화를 불러오지 못했습니다
              </h2>
              <p className="text-muted-foreground mt-2 text-sm leading-6">{errorMessage}</p>
              <button
                type="button"
                onClick={() => void loadSessionData()}
                aria-label="대화 메시지 다시 불러오기"
                className="bg-primary text-primary-foreground hover:bg-primary/90 mt-4 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
              >
                <RefreshCw className="h-4 w-4" />
                다시 시도
              </button>
            </div>
          </div>
        ) : messages.length === 0 ? (
          <ChatEmptyState />
        ) : (
          <ChatMessageList
            messages={messages}
            activitiesByTaskRunId={activitiesByTaskRunId}
            stepRunsByTaskRunId={stepRunsByTaskRunId}
            taskRunSummariesById={taskRunSummariesById}
            onOpenTaskRun={handleOpenTaskRun}
            focusedTaskRunTarget={focusedTaskRunTarget}
            assistantName={mainAgentName}
          />
        )}
        <ChatComposer
          key={composerDraft ? `${selectedWorkId ?? 'work'}:${composerDraft}` : 'chat-composer'}
          draftValue={composerDraft}
          disabled={isComposerDisabled}
          isSending={isSending || isStreaming}
          onSend={handleSend}
          onClearSelectedWork={() => {
            setSelectedWorkId(null)
            setWorkStatusMessage(null)
          }}
          onSelectWorkClick={openWorkPicker}
          selectedWorkLabel={selectedWorkLabel}
          statusMessage={workStatusMessage}
          sessionId={sessionId}
        />
      </section>
      {workPickerOpen && (
        <WorkPickerDialog
          items={workItems}
          loading={workLoading}
          query={workSearch}
          selectedWorkId={selectedWorkId}
          onClose={() => setWorkPickerOpen(false)}
          onQueryChange={setWorkSearch}
          onSelect={(work) => {
            setSelectedWorkId(work.workId)
            setWorkStatusMessage(`${work.identifier} 작업을 이번 메시지에 연결합니다.`)
            setWorkPickerOpen(false)
          }}
        />
      )}
      <StepRunActivityPanel
        open={activityOpen}
        onOpenChange={setActivityOpen}
        sessionId={sessionId}
        selectedTaskRunId={selectedTaskRunId}
        onSelectTaskRun={setSelectedTaskRunId}
        onFocusTaskRunMessage={handleFocusTaskRunMessage}
      />
      {!isPendingSession && (
        <PrototypePanel
          sessionId={sessionId}
          openHint={prototypePanelRequested}
          pollForArtifact={hasActiveChatTurn}
          reopenSignal={prototypePanelOpenRequest}
          onArtifactVisible={handlePrototypeArtifactVisible}
        />
      )}
    </main>
  )
}

const EMPTY_WORK_ITEMS: WorkItem[] = []

type ChatWorkStatusItem = {
  workId: string
  identifier: string
  title: string
  status: WorkStatus
  assigneeAgentId?: string | null
  activeRunId?: string | null
  latestRunId?: string | null
  recentRunIds?: string[]
}

function ChatWorkStatusBar({
  onOpenTaskRun,
  taskRunId,
  taskRunStatusText,
  work,
}: {
  onOpenTaskRun?: () => void
  taskRunId?: string
  taskRunStatusText?: string
  work: ChatWorkStatusItem
}) {
  return (
    <div className="border-border bg-muted/25 flex items-center gap-3 border-b px-4 py-2 text-xs">
      <ListTodo className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-muted-foreground shrink-0">작업</span>
          <span className="text-foreground truncate font-medium">
            {work.identifier} · {work.title}
          </span>
        </div>
        <div className="text-muted-foreground mt-0.5 flex items-center gap-2">
          <span>{workStatusLabel(work.status)}</span>
          {work.assigneeAgentId && <span>담당 {work.assigneeAgentId}</span>}
          {taskRunStatusText && <span>실행 {taskRunStatusText}</span>}
        </div>
      </div>
      {taskRunId && onOpenTaskRun && (
        <button
          type="button"
          onClick={onOpenTaskRun}
          className="border-border bg-background hover:bg-muted text-foreground shrink-0 rounded-md border px-2 py-1 transition-colors"
        >
          실행 보기
        </button>
      )}
    </div>
  )
}

function findWorkByTaskRunId(items: WorkItem[], taskRunId?: string): WorkItem | undefined {
  if (!taskRunId) return undefined
  return items.find(
    (work) =>
      work.activeRunId === taskRunId ||
      work.latestRunId === taskRunId ||
      work.recentRunIds.includes(taskRunId),
  )
}

function findLatestLinkedWorkEvent(
  eventsByTaskRunId: Record<
    string,
    { task_run_id: string; event_type: string; payload?: unknown; sequence?: number }[]
  >,
  taskRunIds: string[],
): { taskRunId: string; work: ChatWorkStatusItem } | undefined {
  const candidates = taskRunIds
    .flatMap((taskRunId) => eventsByTaskRunId[taskRunId] ?? [])
    .filter((event) => event.event_type === 'work.linked')
    .sort((left, right) => (right.sequence ?? 0) - (left.sequence ?? 0))

  for (const event of candidates) {
    const payload = toRecord(event.payload)
    const linkedWork = toRecord(payload.linkedWork)
    const workId = stringValue(linkedWork.workId) ?? stringValue(payload.workId)
    const identifier = stringValue(linkedWork.identifier) ?? stringValue(payload.workIdentifier)
    const title = stringValue(linkedWork.title) ?? stringValue(payload.workTitle)
    const status = stringValue(linkedWork.status) ?? stringValue(payload.workStatus)
    if (!workId || !identifier || !title || !isWorkStatus(status)) {
      continue
    }
    return {
      taskRunId: stringValue(payload.taskRunId) ?? event.task_run_id,
      work: {
        workId,
        identifier,
        title,
        status,
        assigneeAgentId:
          stringValue(linkedWork.assigneeAgentId) ?? stringValue(payload.workAssigneeAgentId),
        latestRunId: stringValue(linkedWork.latestRunId) ?? stringValue(payload.taskRunId),
        recentRunIds: [stringValue(payload.taskRunId) ?? event.task_run_id],
      },
    }
  }
  return undefined
}

function toRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function isWorkStatus(value: unknown): value is WorkStatus {
  return (
    value === 'backlog' ||
    value === 'todo' ||
    value === 'in_progress' ||
    value === 'in_review' ||
    value === 'blocked' ||
    value === 'done' ||
    value === 'cancelled'
  )
}

function WorkPickerDialog({
  items,
  loading,
  onClose,
  onQueryChange,
  onSelect,
  query,
  selectedWorkId,
}: {
  items: WorkItem[]
  loading: boolean
  onClose: () => void
  onQueryChange: (value: string) => void
  onSelect: (work: WorkItem) => void
  query: string
  selectedWorkId: string | null
}) {
  const normalizedQuery = query.trim().toLowerCase()
  const visibleItems = items
    .filter((work) => {
      if (!normalizedQuery) return true
      return [work.identifier, work.title, work.description ?? '', work.assigneeAgentId ?? '']
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery)
    })
    .sort(compareWorkForPicker)

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/20 px-4 py-6 sm:items-center">
      <div className="bg-background flex max-h-[min(680px,90vh)] w-full max-w-2xl flex-col overflow-hidden rounded-lg border shadow-2xl">
        <header className="border-border flex items-center gap-3 border-b px-4 py-3">
          <ListTodo className="text-muted-foreground h-4 w-4" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">기존 작업 선택</h2>
            <p className="text-muted-foreground text-xs">이번 메시지에 연결할 작업을 고릅니다.</p>
          </div>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="닫기" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="border-border border-b p-3">
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="작업 번호, 제목, 담당자 검색"
            aria-label="작업 검색"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {loading && (
            <div className="text-muted-foreground flex items-center gap-2 px-3 py-4 text-sm">
              <ListTodo className="h-4 w-4 animate-pulse" />
              작업 목록을 불러오는 중입니다.
            </div>
          )}
          {!loading && visibleItems.length === 0 && (
            <div className="text-muted-foreground flex items-center gap-2 px-3 py-4 text-sm">
              <AlertCircle className="h-4 w-4" />
              선택할 작업이 없습니다.
            </div>
          )}
          {visibleItems.map((work) => (
            <button
              key={work.workId}
              type="button"
              onClick={() => onSelect(work)}
              className={`hover:bg-accent/40 grid w-full grid-cols-[6rem_minmax(0,1fr)_7rem_7rem] items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${
                selectedWorkId === work.workId ? 'bg-accent text-accent-foreground' : ''
              }`}
            >
              <span className="text-muted-foreground font-mono text-xs">{work.identifier}</span>
              <span className="min-w-0">
                <span className="block truncate font-medium">{work.title}</span>
                <span className="text-muted-foreground block truncate text-xs">
                  {work.description ?? work.rawUserInput ?? ''}
                </span>
              </span>
              <span className="text-muted-foreground truncate text-xs">
                {work.assigneeAgentId ?? '팀장 에이전트'}
              </span>
              <span className="text-muted-foreground text-right text-xs">
                {workStatusLabel(work.status)}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function compareWorkForPicker(left: WorkItem, right: WorkItem) {
  const rank = (status: WorkStatus) =>
    status === 'in_progress'
      ? 0
      : status === 'blocked'
        ? 1
        : status === 'todo'
          ? 2
          : status === 'in_review'
            ? 3
            : status === 'backlog'
              ? 4
              : 5
  return (
    rank(left.status) - rank(right.status) ||
    new Date(right.updatedAt ?? right.createdAt ?? '').getTime() -
      new Date(left.updatedAt ?? left.createdAt ?? '').getTime()
  )
}

function workStatusLabel(status: WorkStatus) {
  return issueBoardStatusLabel(status)
}

function extractWorkIdentifier(content: string) {
  const match = content.match(/\btask\s*[-#]?\s*(\d+)\b/i)
  if (!match) return null
  return `TASK-${match[1]}`
}

function normalizeWorkIdentifier(identifier: string) {
  const match = identifier.match(/\btask\s*[-#]?\s*(\d+)\b/i)
  return match ? `TASK-${match[1]}` : identifier.trim().toUpperCase()
}

function buildAttachmentInputPayload(attachments: ChatAttachmentPayload[]): JsonObject | undefined {
  if (attachments.length === 0) return undefined
  return {
    sessionAttachments: attachments,
    attachmentSummary: attachments.map(({ error, name, size, type }) => ({
      name,
      type,
      size,
      error,
    })),
  }
}

function formatMessageWithAttachmentSummary(content: string, attachments: ChatAttachmentPayload[]) {
  if (attachments.length === 0) return content
  const summary = attachments
    .map((attachment) => {
      const sizeKb = Math.max(1, Math.round(attachment.size / 1024))
      const state = attachment.error ? `, ${attachment.error}` : ''
      return `- ${attachment.name} (${attachment.type || 'application/octet-stream'}, ${sizeKb}KB${state})`
    })
    .join('\n')
  return `${content.trim()}\n\n[첨부 파일]\n${summary}`.trim()
}

function toChatConnectionState(
  connectionStatus: AiRealtimeConnectionStatus,
  authStatus: AiRealtimeAuthStatus,
): ChatConnectionState {
  if (authStatus === 'failed') {
    return 'auth-expired'
  }

  switch (connectionStatus) {
    case 'authenticated':
      return 'connected'
    case 'connecting':
    case 'open':
      return 'connecting'
    case 'reconnecting':
      return 'reconnecting'
    case 'error':
    case 'closed':
      return 'error'
    case 'idle':
    default:
      return 'idle'
  }
}

function isRealtimePending(connectionStatus: AiRealtimeConnectionStatus) {
  return (
    connectionStatus === 'connecting' ||
    connectionStatus === 'open' ||
    connectionStatus === 'reconnecting'
  )
}

function getRealtimeUnavailableMessage(
  connectionStatus: AiRealtimeConnectionStatus,
  authStatus: AiRealtimeAuthStatus,
  realtimeError: string | null,
  accessToken: string | null,
) {
  if (realtimeError !== null) {
    return realtimeError
  }
  if (authStatus === 'failed') {
    return '서버 인증이 만료되었거나 실패했습니다.'
  }
  if (accessToken === null || accessToken.trim() === '') {
    return '로그인이 필요합니다.'
  }
  if (shouldWaitForRealtime(connectionStatus, authStatus, realtimeError, accessToken)) {
    return '서버와 연결 중입니다. 잠시 후 다시 시도해 주세요.'
  }
  return '서버 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

function shouldWaitForRealtime(
  connectionStatus: AiRealtimeConnectionStatus,
  authStatus: AiRealtimeAuthStatus,
  realtimeError: string | null,
  accessToken: string | null,
) {
  if (realtimeError !== null || authStatus === 'failed') {
    return false
  }
  if (accessToken === null || accessToken.trim() === '') {
    return false
  }
  return (
    isRealtimePending(connectionStatus) ||
    connectionStatus === 'idle' ||
    connectionStatus === 'closed'
  )
}

const compareChatStepRuns = (
  first: { step_order?: number | null; stepOrder?: number | null; sequence?: number | null },
  second: { step_order?: number | null; stepOrder?: number | null; sequence?: number | null },
) => {
  const firstOrder = getChatStepOrder(first)
  const secondOrder = getChatStepOrder(second)
  if (firstOrder !== undefined && secondOrder !== undefined) {
    return firstOrder - secondOrder
  }
  return (first.sequence ?? 0) - (second.sequence ?? 0)
}

const getChatStepOrder = (stepRun: { step_order?: number | null; stepOrder?: number | null }) => {
  if (typeof stepRun.step_order === 'number' && Number.isFinite(stepRun.step_order)) {
    return stepRun.step_order
  }
  if (typeof stepRun.stepOrder === 'number' && Number.isFinite(stepRun.stepOrder)) {
    return stepRun.stepOrder
  }
  return undefined
}
