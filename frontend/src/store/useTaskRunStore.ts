import { create } from 'zustand'
import { listTaskRuns } from '@/apis/taskRuns'
import {
  type AiRealtimeRawFrame,
  type RawTaskEventPayload,
  getFramePayload,
  getStringField,
  isJsonObject,
} from '@/realtime/aiRealtimeTypes'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import type {
  RawApproval,
  RawStepRun,
  RawTaskRun,
  RawTaskRunSnapshot,
  TaskRunDisplayContext,
  TaskRunDetailSummaryView,
  TaskRunEventsReplayResultPayload,
  TaskRunsActiveListResultPayload,
  ActivityItemView,
} from '@/types/taskRuns'
import { createApprovalResponseId, createClientCommandId } from '@/utils/requestId'
import { getLastTaskRunSequence, mergeTaskRunEvents } from '@/utils/taskRunEvents'
import {
  isInternalStepAnchorEvent,
  toTaskRunDetailSummaryView,
  toTaskRunStatusText,
  toTaskRunStatusTone,
} from '@/utils/taskRunStatusView'

type TaskRunState = {
  taskRunsById: Record<string, RawTaskRun>
  stepRunsById: Record<string, RawStepRun>
  approvalsById: Record<string, RawApproval>
  eventsByTaskRunId: Record<string, RawTaskEventPayload[]>
  activityItemsByTaskRunId: Record<string, ActivityItemView[]>
  lastSequenceByTaskRunId: Record<string, number>
  replayNeededByTaskRunId: Record<string, boolean>
  recoveryAfterSequenceByTaskRunId: Record<string, number | undefined>
  recoveringByTaskRunId: Record<string, boolean>
  approvalSubmissionIdsByApprovalId: Record<string, string>
  subscribedChildTaskRunIds: Record<string, true>
  lastError: string | null
  fetchActiveTaskRuns: (sessionId?: string) => Promise<RawTaskRun[]>
  fetchSessionTaskRuns: (sessionId: string) => Promise<RawTaskRun[]>
  fetchSnapshot: (taskRunId: string) => Promise<RawTaskRunSnapshot | null>
  replayEvents: (taskRunId: string, afterSequence?: number) => Promise<RawTaskEventPayload[]>
  recoverTaskRun: (taskRunId: string) => Promise<void>
  selectTaskRunSummary: (taskRunId: string) => TaskRunDetailSummaryView
  selectTaskRunSummaries: (taskRunIds?: string[]) => TaskRunDetailSummaryView[]
  isApprovalSubmitting: (approvalId: string) => boolean
  resumeTaskRun: (input: {
    taskRunId: string
    approvalId?: string
    decision?: string
    response?: unknown
  }) => Promise<AiRealtimeRawFrame>
  cancelTaskRun: (taskRunId: string, reason?: string) => Promise<AiRealtimeRawFrame>
  handleRealtimeFrame: (frame: AiRealtimeRawFrame) => void
  mergeTaskEvent: (event: RawTaskEventPayload) => void
  clearTaskRunState: () => void
}

export const useTaskRunStore = create<TaskRunState>((set, get) => ({
  taskRunsById: {},
  stepRunsById: {},
  approvalsById: {},
  eventsByTaskRunId: {},
  activityItemsByTaskRunId: {},
  lastSequenceByTaskRunId: {},
  replayNeededByTaskRunId: {},
  recoveryAfterSequenceByTaskRunId: {},
  recoveringByTaskRunId: {},
  approvalSubmissionIdsByApprovalId: {},
  subscribedChildTaskRunIds: {},
  lastError: null,
  fetchActiveTaskRuns: async (sessionId) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('taskRuns.active.list', { sessionId })
    const taskRuns = getRawTaskRunList(getFramePayload(frame))
    mergeTaskRuns(taskRuns, set)
    return taskRuns
  },
  fetchSessionTaskRuns: async (sessionId) => {
    const taskRuns = await listTaskRuns({ sessionId, pageSize: 20, status: 'ALL' })
    const normalizedTaskRuns = taskRuns.map(normalizeTaskRun).filter((taskRun) => taskRun !== null)
    mergeTaskRuns(normalizedTaskRuns, set)
    return normalizedTaskRuns
  },
  fetchSnapshot: async (taskRunId) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('taskRun.snapshot.get', { taskRunId })
    const snapshot = getFramePayload(frame) as RawTaskRunSnapshot | undefined
    if (!isJsonObject(snapshot)) {
      return null
    }

    mergeSnapshot(snapshot, set)

    // 스냅샷 이벤트에서 child TaskRun을 발견하면 자동 구독한다 (재접속 복구용).
    const snapshotEvents = Array.isArray(snapshot.events)
      ? snapshot.events.filter(isRawTaskEventPayload)
      : []
    subscribeChildTaskRunsFromEvents(snapshotEvents, get, set)

    return snapshot
  },
  replayEvents: async (taskRunId, afterSequence) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('taskRun.events.replay', { taskRunId, afterSequence })
    const payload = getFramePayload(frame) as TaskRunEventsReplayResultPayload
    const events = getRawTaskEventList(payload)

    mergeReplayResult(taskRunId, events, payload, set)
    subscribeChildTaskRunsFromEvents(events, get, set)

    return events
  },
  recoverTaskRun: async (taskRunId) => {
    const state = get()
    if (state.recoveringByTaskRunId[taskRunId] === true) {
      return
    }

    const afterSequence =
      state.recoveryAfterSequenceByTaskRunId[taskRunId] ?? state.lastSequenceByTaskRunId[taskRunId]

    set((current) => ({
      recoveringByTaskRunId: { ...current.recoveringByTaskRunId, [taskRunId]: true },
      lastError: null,
    }))

    try {
      const frame = await useAiRealtimeStore
        .getState()
        .sendCommand<AiRealtimeRawFrame>('taskRun.events.replay', { taskRunId, afterSequence })
      const payload = getFramePayload(frame) as TaskRunEventsReplayResultPayload
      const events = getRawTaskEventList(payload)
      const retentionExceeded = getBooleanField(payload, 'retention_exceeded', 'retentionExceeded')

      mergeReplayResult(taskRunId, events, payload, set)
      subscribeChildTaskRunsFromEvents(events, get, set)

      if (retentionExceeded) {
        // replay 보관 구간을 벗어난 경우에는 event 전체 복구가 불가능하므로 snapshot으로 현재 상태를 맞춘다.
        await get().fetchSnapshot(taskRunId)
      }
    } catch (error) {
      set({
        lastError: error instanceof Error ? error.message : 'TaskRun 이벤트 복구에 실패했습니다.',
      })
      throw error
    } finally {
      set((current) => ({
        recoveringByTaskRunId: { ...current.recoveringByTaskRunId, [taskRunId]: false },
      }))
    }
  },
  selectTaskRunSummary: (taskRunId) => selectTaskRunSummary(get(), taskRunId),
  isApprovalSubmitting: (approvalId) =>
    get().approvalSubmissionIdsByApprovalId[approvalId] !== undefined,
  selectTaskRunSummaries: (taskRunIds) => {
    const state = get()
    const ids = taskRunIds ?? Object.keys(state.taskRunsById)
    return ids.map((taskRunId) => selectTaskRunSummary(state, taskRunId))
  },
  resumeTaskRun: async (input) => {
    if (
      input.approvalId !== undefined &&
      get().approvalSubmissionIdsByApprovalId[input.approvalId] !== undefined
    ) {
      throw new Error('이미 approval 응답을 전송 중입니다.')
    }

    const approvalResponseId = getApprovalResponseId(input.approvalId, get, set)

    try {
      // approvalResponseId는 같은 확인 요청을 여러 번 눌러도 서버가 중복 처리하지 않게 하는 키다.
      return await useAiRealtimeStore.getState().sendCommand<AiRealtimeRawFrame>('taskRun.resume', {
        taskRunId: input.taskRunId,
        approvalId: input.approvalId,
        approvalResponseId,
        // 서버 resume 계약은 실제 승인 본문을 payload 필드에서 읽는다.
        payload: {
          decision: input.decision,
          response: input.response,
        },
      })
    } catch (error) {
      if (input.approvalId !== undefined) {
        clearApprovalSubmission(input.approvalId, set)
      }
      throw error
    }
  },
  cancelTaskRun: (taskRunId, reason) =>
    useAiRealtimeStore.getState().sendCommand<AiRealtimeRawFrame>('taskRun.cancel', {
      taskRunId,
      clientCommandId: createClientCommandId(),
      reason,
    }),
  handleRealtimeFrame: (frame) => {
    switch (frame.type) {
      case 'task.event': {
        const payload = getFramePayload(frame)
        if (isRawTaskEventPayload(payload)) {
          get().mergeTaskEvent(payload)
        }
        return
      }
      case 'session.message.accepted':
        mergeSessionMessageTaskRun(frame, set, 'RUNNING')
        return
      case 'session.message.waiting':
        mergeSessionMessageTaskRun(frame, set, 'WAITING')
        return
      case 'session.message.failed':
        mergeSessionMessageTaskRun(frame, set, 'FAILED')
        return
      case 'taskRuns.active.list.result':
      case 'taskRuns.active.result':
        mergeTaskRuns(getRawTaskRunList(getFramePayload(frame)), set)
        return
      case 'taskRun.snapshot.result': {
        const snapshot = getFramePayload(frame)
        if (isJsonObject(snapshot)) {
          mergeSnapshot(snapshot, set)
        }
        return
      }
      case 'taskRun.events.replay.result': {
        const payload = getFramePayload(frame)
        if (isJsonObject(payload)) {
          const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
          const events = getRawTaskEventList(payload)
          if (taskRunId !== undefined) {
            mergeReplayResult(taskRunId, events, payload, set)
          }
        }
        return
      }
      case 'session.message.completed':
        mergeSessionMessageTaskRun(frame, set, 'COMPLETED')
        return
      default:
        return
    }
  },
  mergeTaskEvent: (event) => {
    // step.updated 이벤트의 payload에서 childTaskRunId를 추출한다 — live event 기준.
    const childTaskRunId = getChildTaskRunId(event)
    const shouldSubscribeChild =
      childTaskRunId !== null && get().subscribedChildTaskRunIds[childTaskRunId] === undefined

    set((state) => {
      const currentEvents = state.eventsByTaskRunId[event.task_run_id] ?? []
      const mergeResult = mergeTaskRunEvents(currentEvents, [event])
      const stepRunId = typeof event.step_run_id === 'string' ? event.step_run_id : undefined
      const placeholderStepRun = buildRealtimeStepRunPlaceholder(
        event,
        stepRunId === undefined ? undefined : state.stepRunsById[stepRunId],
      )
      const nextTaskRun = buildRealtimeTaskRunPlaceholder(
        event,
        state.taskRunsById[event.task_run_id],
      )

      // raw event는 화면 표시와 디버깅의 기준이므로 서버 필드명을 유지한 채 저장한다.
      // sequence gap이 보이면 replayNeeded를 세워 provider가 복구를 시도하게 한다.
      // snapshot 전 step_run_id만 먼저 온 경우에는 가벼운 StepRun을 만들어 실시간 도착을 보여준다.
      return {
        taskRunsById:
          nextTaskRun === null
            ? state.taskRunsById
            : {
                ...state.taskRunsById,
                [nextTaskRun.task_run_id]: nextTaskRun,
              },
        eventsByTaskRunId: {
          ...state.eventsByTaskRunId,
          [event.task_run_id]: mergeResult.events,
        },
        activityItemsByTaskRunId: withoutTaskRunActivityProjection(
          state.activityItemsByTaskRunId,
          event.task_run_id,
        ),
        stepRunsById:
          placeholderStepRun === null
            ? state.stepRunsById
            : {
                ...state.stepRunsById,
                [placeholderStepRun.step_run_id]: placeholderStepRun,
              },
        lastSequenceByTaskRunId:
          mergeResult.lastSequence === undefined
            ? state.lastSequenceByTaskRunId
            : {
                ...state.lastSequenceByTaskRunId,
                [event.task_run_id]: mergeResult.lastSequence,
              },
        replayNeededByTaskRunId: {
          ...state.replayNeededByTaskRunId,
          [event.task_run_id]:
            state.replayNeededByTaskRunId[event.task_run_id] === true || mergeResult.hasGap,
        },
        recoveryAfterSequenceByTaskRunId:
          mergeResult.hasGap && mergeResult.expectedSequence !== undefined
            ? {
                ...state.recoveryAfterSequenceByTaskRunId,
                [event.task_run_id]: mergeResult.expectedSequence - 1,
              }
            : state.recoveryAfterSequenceByTaskRunId,
        subscribedChildTaskRunIds: shouldSubscribeChild
          ? { ...state.subscribedChildTaskRunIds, [childTaskRunId!]: true }
          : state.subscribedChildTaskRunIds,
      }
    })

    // set() 이후 비동기 구독 — WebSocket이 준비되지 않으면 무시하고 재접속 시 복구한다.
    if (shouldSubscribeChild && childTaskRunId !== null) {
      try {
        useAiRealtimeStore.getState().subscribeTask(childTaskRunId)
      } catch {
        // 소켓 미준비 상태 — 재접속 후 snapshot/replay로 복구됨
      }
      void get()
        .fetchSnapshot(childTaskRunId)
        .catch(() => {})
    }
  },
  clearTaskRunState: () =>
    set({
      taskRunsById: {},
      stepRunsById: {},
      approvalsById: {},
      eventsByTaskRunId: {},
      activityItemsByTaskRunId: {},
      lastSequenceByTaskRunId: {},
      replayNeededByTaskRunId: {},
      recoveryAfterSequenceByTaskRunId: {},
      recoveringByTaskRunId: {},
      approvalSubmissionIdsByApprovalId: {},
      subscribedChildTaskRunIds: {},
      lastError: null,
    }),
}))

const getApprovalResponseId = (
  approvalId: string | undefined,
  get: () => TaskRunState,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  if (approvalId === undefined) {
    return createApprovalResponseId()
  }

  const existingResponseId = get().approvalSubmissionIdsByApprovalId[approvalId]
  if (existingResponseId !== undefined) {
    return existingResponseId
  }

  const approvalResponseId = createApprovalResponseId()
  set((state) => ({
    approvalSubmissionIdsByApprovalId: {
      ...state.approvalSubmissionIdsByApprovalId,
      [approvalId]: approvalResponseId,
    },
  }))
  return approvalResponseId
}

const clearApprovalSubmission = (
  approvalId: string,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  set((state) => {
    if (state.approvalSubmissionIdsByApprovalId[approvalId] === undefined) {
      return { approvalSubmissionIdsByApprovalId: state.approvalSubmissionIdsByApprovalId }
    }

    const approvalSubmissionIdsByApprovalId = { ...state.approvalSubmissionIdsByApprovalId }
    delete approvalSubmissionIdsByApprovalId[approvalId]
    return { approvalSubmissionIdsByApprovalId }
  })
}

const getRawTaskRunList = (payload: TaskRunsActiveListResultPayload | unknown): RawTaskRun[] => {
  if (!isJsonObject(payload)) {
    return []
  }

  const list = Array.isArray(payload.task_runs)
    ? payload.task_runs
    : Array.isArray(payload.taskRuns)
      ? payload.taskRuns
      : Array.isArray(payload.items)
        ? payload.items
        : []

  return list.map(normalizeTaskRun).filter((taskRun) => taskRun !== null)
}

const getRawTaskEventList = (payload: TaskRunEventsReplayResultPayload | unknown) => {
  if (!isJsonObject(payload) || !Array.isArray(payload.events)) {
    return []
  }
  return payload.events.filter(isRawTaskEventPayload)
}

const mergeTaskRuns = (
  taskRuns: RawTaskRun[],
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  const stepRuns = taskRuns.flatMap(getTaskRunEmbeddedStepRuns)
  const approvals = taskRuns.flatMap(getTaskRunEmbeddedApprovals)

  set((state) => ({
    taskRunsById: {
      ...state.taskRunsById,
      ...Object.fromEntries(taskRuns.map((taskRun) => [taskRun.task_run_id, taskRun])),
    },
    lastSequenceByTaskRunId: {
      ...state.lastSequenceByTaskRunId,
      ...Object.fromEntries(
        taskRuns
          .map((taskRun) => [taskRun.task_run_id, getTaskRunLastSequence(taskRun)] as const)
          .filter((entry): entry is readonly [string, number] => entry[1] !== undefined),
      ),
    },
    stepRunsById: {
      ...state.stepRunsById,
      ...Object.fromEntries(stepRuns.map((stepRun) => [stepRun.step_run_id, stepRun])),
    },
    approvalsById: {
      ...state.approvalsById,
      ...Object.fromEntries(approvals.map((approval) => [approval.approval_id, approval])),
    },
    approvalSubmissionIdsByApprovalId: clearResolvedApprovalSubmissions(
      state.approvalSubmissionIdsByApprovalId,
      approvals,
    ),
  }))
}

const mergeSnapshot = (
  snapshot: RawTaskRunSnapshot,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  const taskRun = normalizeTaskRun(snapshot.task ?? snapshot.task_run ?? snapshot.taskRun)
  const taskRunId = taskRun?.task_run_id ?? getStringField(snapshot, 'task_run_id', 'taskRunId')
  const stepCandidates = snapshot.steps ?? snapshot.step_runs ?? snapshot.stepRuns ?? []
  const approvalCandidates = [
    ...(snapshot.approvals ?? []),
    snapshot.pending_approval,
    snapshot.pendingApproval,
  ]
  const stepRuns = stepCandidates
    .map((stepRun) => normalizeStepRun(stepRun, taskRunId))
    .filter((stepRun) => stepRun !== null)
  const approvals = approvalCandidates
    .map((approval) => normalizeApproval(approval, taskRunId))
    .filter((approval) => approval !== null)
  const events = (snapshot.events ?? []).filter(isRawTaskEventPayload)
  const projectedActivities = getProjectedActivityItems(snapshot, taskRunId)

  set((state) => {
    const nextEventsByTaskRunId = { ...state.eventsByTaskRunId }
    const nextLastSequenceByTaskRunId = { ...state.lastSequenceByTaskRunId }
    const nextReplayNeededByTaskRunId = { ...state.replayNeededByTaskRunId }
    const nextRecoveryAfterSequenceByTaskRunId = { ...state.recoveryAfterSequenceByTaskRunId }

    events.forEach((event) => {
      const mergeResult = mergeTaskRunEvents(nextEventsByTaskRunId[event.task_run_id] ?? [], [
        event,
      ])
      nextEventsByTaskRunId[event.task_run_id] = mergeResult.events
      const lastSequence = getLastTaskRunSequence(mergeResult.events)
      if (lastSequence !== undefined) {
        nextLastSequenceByTaskRunId[event.task_run_id] = lastSequence
      }
      nextReplayNeededByTaskRunId[event.task_run_id] = false
      delete nextRecoveryAfterSequenceByTaskRunId[event.task_run_id]
    })

    if (taskRunId !== undefined) {
      nextReplayNeededByTaskRunId[taskRunId] = false
      delete nextRecoveryAfterSequenceByTaskRunId[taskRunId]
    }

    const taskRunLastSequence = taskRun === null ? undefined : getTaskRunLastSequence(taskRun)
    if (taskRunId !== undefined && taskRunLastSequence !== undefined) {
      nextLastSequenceByTaskRunId[taskRunId] = taskRunLastSequence
    }
    const eventStepRuns = buildRealtimeStepRunPlaceholders(events, state.stepRunsById)

    return {
      taskRunsById:
        taskRun === null
          ? state.taskRunsById
          : { ...state.taskRunsById, [taskRun.task_run_id]: taskRun },
      stepRunsById: {
        ...state.stepRunsById,
        ...eventStepRuns,
        ...Object.fromEntries(stepRuns.map((stepRun) => [stepRun.step_run_id, stepRun])),
      },
      approvalsById: {
        ...state.approvalsById,
        ...Object.fromEntries(approvals.map((approval) => [approval.approval_id, approval])),
      },
      approvalSubmissionIdsByApprovalId: clearResolvedApprovalSubmissions(
        state.approvalSubmissionIdsByApprovalId,
        approvals,
      ),
      eventsByTaskRunId: nextEventsByTaskRunId,
      activityItemsByTaskRunId:
        taskRunId === undefined || projectedActivities.length === 0
          ? state.activityItemsByTaskRunId
          : {
              ...state.activityItemsByTaskRunId,
              [taskRunId]: projectedActivities,
            },
      lastSequenceByTaskRunId: nextLastSequenceByTaskRunId,
      replayNeededByTaskRunId: nextReplayNeededByTaskRunId,
      recoveryAfterSequenceByTaskRunId: nextRecoveryAfterSequenceByTaskRunId,
    }
  })
}

const mergeReplayResult = (
  taskRunId: string,
  events: RawTaskEventPayload[],
  payload: Record<string, unknown>,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  set((state) => {
    const mergeResult = mergeTaskRunEvents(state.eventsByTaskRunId[taskRunId] ?? [], events)
    const projectedActivities = getProjectedActivityItems(payload, taskRunId)
    const retentionExceeded = getBooleanField(payload, 'retention_exceeded', 'retentionExceeded')
    const replayNeeded = retentionExceeded || mergeResult.hasGap
    const recoveryAfterSequenceByTaskRunId = { ...state.recoveryAfterSequenceByTaskRunId }
    if (replayNeeded && mergeResult.expectedSequence !== undefined) {
      recoveryAfterSequenceByTaskRunId[taskRunId] = mergeResult.expectedSequence - 1
    }
    if (!replayNeeded) {
      delete recoveryAfterSequenceByTaskRunId[taskRunId]
    }
    const eventStepRuns = buildRealtimeStepRunPlaceholders(mergeResult.events, state.stepRunsById)

    return {
      stepRunsById: {
        ...state.stepRunsById,
        ...eventStepRuns,
      },
      eventsByTaskRunId: {
        ...state.eventsByTaskRunId,
        [taskRunId]: mergeResult.events,
      },
      activityItemsByTaskRunId: mergeProjectedActivityItems(
        state.activityItemsByTaskRunId,
        taskRunId,
        projectedActivities,
      ),
      lastSequenceByTaskRunId:
        mergeResult.lastSequence === undefined
          ? state.lastSequenceByTaskRunId
          : {
              ...state.lastSequenceByTaskRunId,
              [taskRunId]: mergeResult.lastSequence,
            },
      replayNeededByTaskRunId: {
        ...state.replayNeededByTaskRunId,
        [taskRunId]: replayNeeded,
      },
      recoveryAfterSequenceByTaskRunId,
    }
  })
}

const mergeSessionMessageTaskRun = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
  fallbackStatus: RawTaskRun['status'],
) => {
  const payload = getFramePayload(frame)
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const payloadStatus = getStringField(payload, 'status')
  const status = shouldForceSessionMessageStatus(fallbackStatus)
    ? fallbackStatus
    : (payloadStatus ?? fallbackStatus)

  if (taskRunId === undefined) {
    return
  }

  set((state) => {
    const currentTaskRun = state.taskRunsById[taskRunId]
    const now = new Date().toISOString()

    return {
      taskRunsById: {
        ...state.taskRunsById,
        [taskRunId]: {
          ...(currentTaskRun ?? {
            task_run_id: taskRunId,
            displayContext: createMainAgentDisplayContext(taskRunId, sessionId),
            created_at: now,
          }),
          status,
          session_id: currentTaskRun?.session_id ?? sessionId,
          updated_at: now,
          completed_at:
            status === 'COMPLETED'
              ? (currentTaskRun?.completed_at ?? now)
              : currentTaskRun?.completed_at,
        },
      },
    }
  })
}

const shouldForceSessionMessageStatus = (status?: RawTaskRun['status'] | null) =>
  status === 'COMPLETED' ||
  status === 'FAILED' ||
  status === 'CANCELED' ||
  status === 'CANCELLED' ||
  status === 'WAITING'

const createMainAgentDisplayContext = (
  taskRunId: string,
  sessionId?: string,
): TaskRunDisplayContext => {
  const mainAgent = {
    id: 'ceo',
    kind: 'main' as const,
    profileKey: 'ceo',
    displayName: '팀장 에이전트',
  }

  return {
    sessionId,
    taskRunId,
    assigneeAgent: mainAgent,
    actorAgent: mainAgent,
    delegatedAgents: [],
  }
}

const buildRealtimeTaskRunPlaceholder = (
  event: RawTaskEventPayload,
  existingTaskRun?: RawTaskRun,
): RawTaskRun | null => {
  const nextStatus = inferTaskRunStatusFromEvent(event, existingTaskRun?.status)
  if (nextStatus === undefined && existingTaskRun !== undefined) {
    return null
  }

  const occurredAt = typeof event.occurred_at === 'string' ? event.occurred_at : undefined

  return {
    ...(existingTaskRun ?? {
      task_run_id: event.task_run_id,
      displayContext: pickTaskEventDisplayContext(event.payload),
      created_at: occurredAt,
    }),
    task_run_id: event.task_run_id,
    status: nextStatus ?? existingTaskRun?.status,
    updated_at: occurredAt ?? existingTaskRun?.updated_at,
    completed_at:
      nextStatus !== undefined && isTerminalTaskRunStatus(nextStatus)
        ? (existingTaskRun?.completed_at ?? occurredAt)
        : existingTaskRun?.completed_at,
    displayContext: existingTaskRun?.displayContext ?? pickTaskEventDisplayContext(event.payload),
  }
}

const inferTaskRunStatusFromEvent = (
  event: RawTaskEventPayload,
  existingStatus?: RawTaskRun['status'] | null,
): RawTaskRun['status'] | undefined => {
  if (existingStatus !== undefined && isTerminalTaskRunStatus(existingStatus)) {
    return existingStatus
  }

  switch (event.event_type) {
    case 'task.completed':
    case 'session.message.completed':
      return 'COMPLETED'
    case 'task.failed':
    case 'session.message.failed':
      return 'FAILED'
    case 'task.canceled':
    case 'task.cancelled':
      return 'CANCELED'
    case 'task.started':
    case 'step.started':
    case 'tool.started':
    case 'search.started':
      return 'RUNNING'
    case 'step.waiting':
      return 'WAITING'
    case 'step.completed':
    case 'step.failed':
    case 'step.canceled':
    case 'step.cancelled':
    case 'tool.completed':
    case 'search.completed':
      return existingStatus ?? 'RUNNING'
    default:
      break
  }

  const eventStatus = normalizeRealtimeStepRunStatus(event.status)
  if (eventStatus !== undefined && !isChildTerminalEvent(event.event_type)) {
    return eventStatus
  }

  return undefined
}

const isChildTerminalEvent = (eventType: string) =>
  eventType === 'step.completed' ||
  eventType === 'step.failed' ||
  eventType === 'step.canceled' ||
  eventType === 'step.cancelled' ||
  eventType === 'tool.completed' ||
  eventType === 'search.completed'

const buildRealtimeStepRunPlaceholder = (
  event: RawTaskEventPayload,
  existingStepRun?: RawStepRun,
): RawStepRun | null => {
  if (typeof event.step_run_id !== 'string' || event.step_run_id.trim() === '') {
    return null
  }

  const occurredAt = typeof event.occurred_at === 'string' ? event.occurred_at : undefined
  const inferredStatus = inferRealtimeStepRunStatus(event, existingStepRun?.status)
  const nextStatus =
    existingStepRun?.status !== undefined &&
    isTerminalTaskRunStatus(existingStepRun.status) &&
    !isTerminalTaskRunStatus(inferredStatus)
      ? existingStepRun.status
      : inferredStatus
  const internalStepAnchor =
    existingStepRun?.internal_step_anchor ?? isInternalStepAnchorEvent(event)

  return {
    ...(existingStepRun ?? {}),
    step_run_id: event.step_run_id,
    task_run_id: existingStepRun?.task_run_id ?? event.task_run_id,
    title: isGenericStepRunTitle(existingStepRun?.title)
      ? (inferRealtimeStepRunTitle(event) ?? existingStepRun?.title)
      : (existingStepRun?.title ?? inferRealtimeStepRunTitle(event)),
    status: nextStatus ?? existingStepRun?.status,
    step_order:
      existingStepRun?.step_order ??
      pickTaskEventNumber(event.payload, ['step_order', 'stepOrder']),
    stepOrder:
      existingStepRun?.stepOrder ?? pickTaskEventNumber(event.payload, ['stepOrder', 'step_order']),
    internal_step_anchor: internalStepAnchor ? true : undefined,
    internalStepAnchor: internalStepAnchor ? true : undefined,
    sequence: existingStepRun?.sequence ?? event.sequence,
    started_at:
      existingStepRun?.started_at ??
      (isStepRunStartEvent(event.event_type) ? occurredAt : undefined),
    completed_at:
      existingStepRun?.completed_at ??
      (isStepRunCompletionEvent(event.event_type) ? occurredAt : undefined),
    displayContext: existingStepRun?.displayContext ?? pickTaskEventDisplayContext(event.payload),
    updated_at: occurredAt ?? existingStepRun?.updated_at,
    realtime_placeholder: existingStepRun?.realtime_placeholder ?? true,
  }
}

const buildRealtimeStepRunPlaceholders = (
  events: RawTaskEventPayload[],
  existingStepRunsById: Record<string, RawStepRun>,
) =>
  events.reduce<Record<string, RawStepRun>>((stepRunsById, event) => {
    if (typeof event.step_run_id !== 'string') {
      return stepRunsById
    }

    const existingStepRun =
      stepRunsById[event.step_run_id] ?? existingStepRunsById[event.step_run_id]
    const placeholder = buildRealtimeStepRunPlaceholder(event, existingStepRun)
    if (placeholder !== null) {
      stepRunsById[placeholder.step_run_id] = placeholder
    }
    return stepRunsById
  }, {})

const inferRealtimeStepRunStatus = (
  event: RawTaskEventPayload,
  existingStatus?: RawStepRun['status'] | null,
): RawStepRun['status'] | undefined => {
  const normalizedExistingStatus = normalizeRealtimeStepRunStatus(existingStatus)
  switch (event.event_type) {
    case 'step.created':
      return normalizeRealtimeStepRunStatus(event.status) ?? 'PENDING'
    case 'step.started':
      return 'RUNNING'
    case 'step.waiting':
      return 'WAITING'
    case 'step.completed':
      return 'COMPLETED'
    case 'step.failed':
      return 'FAILED'
    case 'step.canceled':
    case 'step.cancelled':
      return 'CANCELED'
    case 'tool.started':
    case 'search.started':
      return normalizedExistingStatus ?? 'RUNNING'
    case 'tool.completed':
    case 'search.completed':
      return normalizedExistingStatus ?? 'RUNNING'
    default:
      return normalizeRealtimeStepRunStatus(event.status) ?? normalizedExistingStatus
  }
}

const normalizeRealtimeStepRunStatus = (
  status?: string | null,
): RawStepRun['status'] | undefined => {
  switch (status) {
    case 'PENDING':
    case 'RUNNING':
    case 'WAITING':
    case 'BLOCKED':
    case 'COMPLETED':
    case 'FAILED':
    case 'CANCELED':
    case 'CANCELLED':
      return status
    case 'step.started':
    case 'tool.started':
    case 'search.started':
      return 'RUNNING'
    case 'step.waiting':
      return 'WAITING'
    case 'step.completed':
      return 'COMPLETED'
    case 'step.failed':
      return 'FAILED'
    case 'step.canceled':
    case 'step.cancelled':
      return 'CANCELED'
    default:
      return undefined
  }
}

const isGenericStepRunTitle = (title?: string | null) =>
  !title || title.toLowerCase().includes('agent loop')

const inferRealtimeStepRunTitle = (event: RawTaskEventPayload) =>
  (event.event_type.startsWith('step.')
    ? getMeaningfulTaskEventSummary(event.summary_message)
    : undefined) ??
  pickTaskEventString(event.payload, ['step_title', 'stepTitle', 'goal']) ??
  pickTaskEventString(event.detail_json, ['step_title', 'stepTitle', 'goal']) ??
  getRealtimeStepRunFallbackTitle(event.event_type)

const getMeaningfulTaskEventSummary = (value?: string | null) => {
  const text = typeof value === 'string' ? value.trim() : ''
  if (
    text === '' ||
    text === '답변을 준비하는 중입니다.' ||
    text === '답변 준비 중' ||
    text === '작업 중'
  ) {
    return undefined
  }
  return text
}

const pickTaskEventString = (value: unknown, keys: string[]) => {
  if (!isJsonObject(value)) {
    return undefined
  }

  for (const key of keys) {
    const candidate = value[key]
    if (typeof candidate === 'string' && candidate.trim() !== '') {
      return candidate.trim()
    }
  }

  return undefined
}

const pickTaskEventNumber = (value: unknown, keys: string[]) => {
  if (!isJsonObject(value)) {
    return undefined
  }

  for (const key of keys) {
    const candidate = value[key]
    if (typeof candidate === 'number' && Number.isFinite(candidate)) {
      return candidate
    }
  }

  return undefined
}

const pickTaskEventDisplayContext = (value: unknown): TaskRunDisplayContext | undefined => {
  if (!isJsonObject(value) || !isJsonObject(value.displayContext)) {
    return undefined
  }
  return value.displayContext as TaskRunDisplayContext
}

const getProjectedActivityItems = (
  payload: Record<string, unknown>,
  fallbackTaskRunId?: string,
): ActivityItemView[] => {
  const rawItems = payload.activity_items ?? payload.activityItems
  if (!Array.isArray(rawItems)) {
    return []
  }
  return rawItems
    .map((item) => normalizeProjectedActivityItem(item, fallbackTaskRunId))
    .filter((item) => item !== null)
}

const normalizeProjectedActivityItem = (
  item: unknown,
  fallbackTaskRunId?: string,
): ActivityItemView | null => {
  if (!isJsonObject(item)) {
    return null
  }
  const id = getStringField(item, 'activity_id', 'activityId')
  const taskRunId = getStringField(item, 'task_run_id', 'taskRunId') ?? fallbackTaskRunId
  if (id === undefined || taskRunId === undefined) {
    return null
  }
  const status = getStringField(item, 'status') ?? 'RUNNING'
  const sequence = pickTaskEventNumber(item, ['last_sequence', 'lastSequence'])
  const occurredAt = getStringField(item, 'occurred_at', 'occurredAt')
  const stepRunId = getStringField(item, 'step_run_id', 'stepRunId')
  const title = getStringField(item, 'title') ?? toTaskRunStatusText(status)
  const raw: RawTaskEventPayload = {
    event_id: id,
    event_type: status,
    task_run_id: taskRunId,
    step_run_id: stepRunId,
    sequence,
    occurred_at: occurredAt,
    status,
    summary_message: title,
    payload: item.payload,
  }
  return {
    id,
    taskRunId,
    stepRunId,
    title,
    statusText: toTaskRunStatusText(status),
    tone: toTaskRunStatusTone(status),
    sequence,
    occurredAt,
    displayContext: pickTaskEventDisplayContext(item.payload),
    raw,
  }
}

const mergeProjectedActivityItems = (
  current: Record<string, ActivityItemView[]>,
  taskRunId: string,
  projectedActivities: ActivityItemView[],
) => {
  if (projectedActivities.length === 0) {
    return current
  }
  return {
    ...current,
    [taskRunId]: projectedActivities,
  }
}

const withoutTaskRunActivityProjection = (
  current: Record<string, ActivityItemView[]>,
  taskRunId: string,
) => {
  if (current[taskRunId] === undefined) {
    return current
  }
  const next = { ...current }
  delete next[taskRunId]
  return next
}

const getRealtimeStepRunFallbackTitle = (eventType: string) => {
  if (eventType.startsWith('tool.')) {
    return '도구 실행'
  }
  if (eventType.startsWith('search.')) {
    return '자료 확인'
  }
  return '답변 진행 단계'
}

const isStepRunStartEvent = (eventType: string) =>
  eventType === 'step.started' || eventType === 'tool.started' || eventType === 'search.started'

const isStepRunCompletionEvent = (eventType: string) =>
  eventType === 'step.completed' || eventType === 'step.failed' || eventType === 'step.canceled'

const isTerminalTaskRunStatus = (status?: string | null) =>
  status === 'COMPLETED' ||
  status === 'FAILED' ||
  status === 'CANCELLED' ||
  status === 'CANCELED' ||
  status === 'step.completed' ||
  status === 'step.failed' ||
  status === 'step.canceled' ||
  status === 'step.cancelled'

const selectTaskRunSummary = (state: TaskRunState, taskRunId: string) => {
  const taskRun = state.taskRunsById[taskRunId]
  const stepRuns = Object.values(state.stepRunsById).filter(
    (stepRun) => stepRun.task_run_id === taskRunId,
  )
  const approvals = Object.values(state.approvalsById).filter(
    (approval) => approval.task_run_id === taskRunId,
  )

  return toTaskRunDetailSummaryView({
    taskRun,
    stepRuns,
    approvals,
    events: state.eventsByTaskRunId[taskRunId] ?? [],
    activityItems: state.activityItemsByTaskRunId[taskRunId],
    replayNeeded: state.replayNeededByTaskRunId[taskRunId] === true,
    recovering: state.recoveringByTaskRunId[taskRunId] === true,
    recoveryAfterSequence: state.recoveryAfterSequenceByTaskRunId[taskRunId],
  })
}

const getTaskRunEmbeddedStepRuns = (taskRun: RawTaskRun) => {
  const candidates = [
    taskRun.current_step,
    taskRun.currentStep,
    ...(Array.isArray(taskRun.steps) ? taskRun.steps : []),
    ...(Array.isArray(taskRun.step_runs) ? taskRun.step_runs : []),
    ...(Array.isArray(taskRun.stepRuns) ? taskRun.stepRuns : []),
  ]

  return candidates
    .map((stepRun) => normalizeStepRun(stepRun, taskRun.task_run_id))
    .filter((stepRun) => stepRun !== null)
}

const getTaskRunEmbeddedApprovals = (taskRun: RawTaskRun) => {
  const candidates = [
    taskRun.pending_approval,
    taskRun.pendingApproval,
    ...(Array.isArray(taskRun.approvals) ? taskRun.approvals : []),
  ]

  return candidates
    .map((approval) => normalizeApproval(approval, taskRun.task_run_id))
    .filter((approval) => approval !== null)
}

const normalizeTaskRun = (value: unknown): RawTaskRun | null => {
  if (!isJsonObject(value)) {
    return null
  }

  const taskRunId = getStringField(value, 'task_run_id', 'taskRunId') ?? getStringField(value, 'id')
  if (taskRunId === undefined) {
    return null
  }

  const sessionId =
    getStringField(value, 'session_id', 'sessionId') ??
    getStringField(value, 'session_key', 'sessionKey')

  return {
    ...value,
    task_run_id: taskRunId,
    session_id: sessionId ?? (typeof value.session_id === 'string' ? value.session_id : undefined),
  }
}

const normalizeStepRun = (value: unknown, fallbackTaskRunId?: string): RawStepRun | null => {
  if (!isJsonObject(value)) {
    return null
  }

  const stepRunId = getStringField(value, 'step_run_id', 'stepRunId') ?? getStringField(value, 'id')
  const taskRunId = getStringField(value, 'task_run_id', 'taskRunId') ?? fallbackTaskRunId

  if (stepRunId === undefined || taskRunId === undefined) {
    return null
  }

  return {
    ...value,
    step_run_id: stepRunId,
    task_run_id: taskRunId,
  }
}

const normalizeApproval = (value: unknown, fallbackTaskRunId?: string): RawApproval | null => {
  if (!isJsonObject(value)) {
    return null
  }

  const approvalId =
    getStringField(value, 'approval_id', 'approvalId') ?? getStringField(value, 'id')
  const taskRunId = getStringField(value, 'task_run_id', 'taskRunId') ?? fallbackTaskRunId

  if (approvalId === undefined || taskRunId === undefined) {
    return null
  }

  return {
    ...value,
    approval_id: approvalId,
    task_run_id: taskRunId,
  }
}

const clearResolvedApprovalSubmissions = (
  submissionIdsByApprovalId: Record<string, string>,
  approvals: RawApproval[],
) => {
  const nextSubmissionIdsByApprovalId = { ...submissionIdsByApprovalId }
  approvals.forEach((approval) => {
    if (!isPendingApprovalStatus(approval.status)) {
      delete nextSubmissionIdsByApprovalId[approval.approval_id]
    }
  })
  return nextSubmissionIdsByApprovalId
}

const isPendingApprovalStatus = (status?: RawApproval['status'] | null) =>
  status === undefined || status === null || status === 'PENDING'

const getTaskRunLastSequence = (taskRun: RawTaskRun) => {
  if (typeof taskRun.last_sequence === 'number' && Number.isFinite(taskRun.last_sequence)) {
    return taskRun.last_sequence
  }

  return typeof taskRun.lastSequence === 'number' && Number.isFinite(taskRun.lastSequence)
    ? taskRun.lastSequence
    : undefined
}

const getBooleanField = (value: unknown, firstKey: string, secondKey?: string): boolean => {
  if (!isJsonObject(value)) {
    return false
  }

  if (typeof value[firstKey] === 'boolean') {
    return value[firstKey]
  }

  return secondKey !== undefined && typeof value[secondKey] === 'boolean' ? value[secondKey] : false
}

const isRawTaskEventPayload = (value: unknown): value is RawTaskEventPayload =>
  isJsonObject(value) &&
  typeof value.event_id === 'string' &&
  typeof value.event_type === 'string' &&
  typeof value.task_run_id === 'string'

// step.updated 이벤트의 payload에서 childTaskRunId를 추출한다.
// camelCase와 snake_case 모두 처리한다.
const getChildTaskRunId = (event: RawTaskEventPayload): string | null => {
  if (event.event_type !== 'step.updated' || !isJsonObject(event.payload)) return null
  const id = event.payload.childTaskRunId ?? event.payload.child_task_run_id
  return typeof id === 'string' && id !== '' ? id : null
}

// 이벤트 목록에서 미구독 child TaskRun을 찾아 구독하고 snapshot을 가져온다.
// fetchSnapshot이 재귀 호출될 수 있으나 subscribedChildTaskRunIds로 중복을 방지한다.
const subscribeChildTaskRunsFromEvents = (
  events: RawTaskEventPayload[],
  get: () => TaskRunState,
  set: (partial: Partial<TaskRunState> | ((state: TaskRunState) => Partial<TaskRunState>)) => void,
) => {
  const subscribedIds = get().subscribedChildTaskRunIds
  const newChildIds = [
    ...new Set(
      events
        .map(getChildTaskRunId)
        .filter((id): id is string => id !== null && subscribedIds[id] === undefined),
    ),
  ]

  if (newChildIds.length === 0) return

  set((state) => ({
    subscribedChildTaskRunIds: {
      ...state.subscribedChildTaskRunIds,
      ...Object.fromEntries(newChildIds.map((id) => [id, true as const])),
    },
  }))

  for (const childId of newChildIds) {
    try {
      useAiRealtimeStore.getState().subscribeTask(childId)
    } catch {
      // 소켓 미준비 — 재접속 후 snapshot/replay로 복구됨
    }
    void get()
      .fetchSnapshot(childId)
      .catch(() => {})
  }
}
