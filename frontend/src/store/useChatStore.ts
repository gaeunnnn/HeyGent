import { create } from 'zustand'
import {
  type AiRealtimeRawFrame,
  type JsonObject,
  type RawSessionMessageAcceptedPayload,
  type RawSessionMessageCompletedPayload,
  type RawSessionMessageDeltaPayload,
  type RawSessionMessageFailedPayload,
  type RawSessionMessageWaitingPayload,
  type RawSessionUpdatedPayload,
  type SessionMutationResultPayload,
  type SessionDeleteResultPayload,
  type ModelOptionsRawResultPayload,
  getFramePayload,
  getStringField,
  getNumberField,
  isJsonObject,
} from '@/realtime/aiRealtimeTypes'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useAgentVisualizationStore, playAgentChime } from '@/store/useAgentVisualizationStore'
import { toast } from 'sonner'
import { useSessionStore, type AgentPanelItem } from '@/store/useSessionStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import { agentProfilesToPanelItems } from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import type {
  AiModelOption,
  AiModelProviderOption,
  AiSessionSettingsPatch,
  ChatMessageView,
  ChatMessageStatus,
  ModelOptionsResultPayload,
  RawAiMessage,
  RawAiSession,
  SessionListResultPayload,
  SessionMessagesListResultPayload,
} from '@/types/aiChat'
import { createClientCommandId, createClientMessageId } from '@/utils/requestId'
import {
  mergeLiveMessagesIntoPersistedList,
  reconcileSessionRunState,
  resolveCompletedSessionTaskStatus,
  shouldClearSessionRunFromPersistedMessages,
} from '@/utils/chatLiveState'

type ChatState = {
  sessionsById: Record<string, RawAiSession>
  messagesBySessionId: Record<string, ChatMessageView[]>
  pendingClientMessageIds: Record<string, string>
  loadingSessionIds: Record<string, boolean>
  sessionListLoading: boolean
  sessionListError: string | null
  modelOptions: ModelOptionsResultPayload | null
  modelOptionsLoading: boolean
  modelOptionsError: string | null
  lastError: string | null
  fetchSessions: () => Promise<RawAiSession[]>
  fetchMessages: (sessionId: string) => Promise<ChatMessageView[]>
  sendMessage: (input: {
    sessionId?: string
    content: string
    settings?: AiSessionSettingsPatch
    inputPayload?: JsonObject
    clientMessageId?: string
  }) => Promise<AiRealtimeRawFrame>
  updateSession: (input: {
    sessionId: string
    title?: string
    metadataPatch?: JsonObject
  }) => Promise<RawAiSession | null>
  deleteSession: (sessionId: string) => Promise<void>
  updateSessionSettings: (input: {
    sessionId: string
    settingsPatch: AiSessionSettingsPatch
  }) => Promise<RawAiSession | null>
  fetchModelOptions: (sessionId?: string) => Promise<ModelOptionsResultPayload>
  handleRealtimeFrame: (frame: AiRealtimeRawFrame) => void
  addExternalTaskPlaceholder: (sessionId: string, taskRunId: string) => void
  clearChatState: () => void
}

const SESSION_AGENT_SPRITE_SLOTS = [
  'agent01',
  'agent02',
  'agent03',
  'agent04',
  'agent05',
  'agent06',
  'agent07',
  'agent08',
  'agent09',
  'agent10',
]

function getSessionSubAgentSpriteIds(panels: AgentPanelItem[]) {
  const usedSlots = new Set<string>()
  const spriteIds: string[] = []

  for (const panel of panels) {
    if (panel.agent.spriteId) {
      spriteIds.push(panel.agent.spriteId)
      usedSlots.add(panel.agent.spriteId)
    }
  }

  for (const panel of panels) {
    if (panel.agent.spriteId) continue
    const slot = SESSION_AGENT_SPRITE_SLOTS.find((id) => !usedSlots.has(id))
    if (!slot) break
    spriteIds.push(slot)
    usedSlots.add(slot)
  }

  return [...new Set(spriteIds)]
}

function startVisualizationForSession(
  sessionId: string,
  taskRunId: string,
  panels: AgentPanelItem[],
) {
  useAgentVisualizationStore.getState().startSessionWork({
    sessionId,
    taskRunId,
    subAgentSpriteIds: getSessionSubAgentSpriteIds(panels),
  })
}

function refreshVisualizationSessionAgents(sessionId: string, taskRunId: string) {
  // 새 에이전트 spawn 또는 작업 시작 흐름 — 캐시를 무효화한 뒤 다시 받아 최신 panel 로 갱신한다.
  useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
  void useAgentCacheStore
    .getState()
    .fetchSessionAgents(sessionId)
    .then((profiles) => {
      const panels = agentProfilesToPanelItems(profiles)
      useSessionStore.getState().setAgentPanelsForSession(sessionId, panels)
      startVisualizationForSession(sessionId, taskRunId, panels)
    })
    .catch(() => {
      // 시각화 보강 조회 실패 시 채팅 전송 흐름은 유지한다.
    })
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionsById: {},
  messagesBySessionId: {},
  pendingClientMessageIds: {},
  loadingSessionIds: {},
  sessionListLoading: false,
  sessionListError: null,
  modelOptions: null,
  modelOptionsLoading: false,
  modelOptionsError: null,
  lastError: null,
  fetchSessions: async () => {
    set({ sessionListLoading: true, sessionListError: null })

    try {
      const frame = await useAiRealtimeStore
        .getState()
        .sendCommand<AiRealtimeRawFrame>('session.list', { includeArchived: true })
      const payload = getFramePayload(frame) as SessionListResultPayload
      const sessions = getRawSessionList(payload).filter((session) => !isRemovedSession(session))

      set((state) => ({
        sessionsById: reconcileVisibleSessions(state.sessionsById, sessions),
        sessionListLoading: false,
        sessionListError: null,
        lastError: null,
      }))

      return sessions
    } catch (error) {
      const message = error instanceof Error ? error.message : '세션 목록 조회에 실패했습니다.'
      set({
        sessionListLoading: false,
        sessionListError: message,
        lastError: message,
      })
      throw error
    }
  },
  fetchMessages: async (sessionId) => {
    set((state) => ({
      loadingSessionIds: { ...state.loadingSessionIds, [sessionId]: true },
    }))

    try {
      const frame = await useAiRealtimeStore
        .getState()
        .sendCommand<AiRealtimeRawFrame>('session.messages.list', { sessionId })
      const payload = getFramePayload(frame) as SessionMessagesListResultPayload
      const messages = getRawMessageList(payload).map(toChatMessageView)
      let mergedMessages = messages

      set((state) => {
        mergedMessages = mergeLiveMessagesIntoPersistedList(
          messages,
          state.messagesBySessionId[sessionId] ?? [],
          sessionId,
        )
        return {
          messagesBySessionId: { ...state.messagesBySessionId, [sessionId]: mergedMessages },
          loadingSessionIds: { ...state.loadingSessionIds, [sessionId]: false },
          lastError: null,
        }
      })

      return mergedMessages
    } catch (error) {
      set((state) => ({
        loadingSessionIds: { ...state.loadingSessionIds, [sessionId]: false },
        lastError: error instanceof Error ? error.message : '메시지 조회에 실패했습니다.',
      }))
      throw error
    }
  },
  sendMessage: async ({
    sessionId,
    content,
    settings,
    inputPayload,
    clientMessageId: inputClientMessageId,
  }) => {
    const trimmedContent = content.trim()
    if (trimmedContent === '') {
      throw new Error('전송할 메시지를 입력해 주세요.')
    }

    const clientMessageId = inputClientMessageId ?? createClientMessageId()
    const optimisticSessionId = sessionId ?? `pending_session_${clientMessageId}`
    const optimisticWork = getWorkContextFromInputPayload(inputPayload)
    // 서버 accepted가 오기 전에도 사용자가 보낸 문장을 즉시 보여 주기 위한 임시 메시지다.
    // accepted를 받으면 서버/DB message id와 실제 session id로 치환한다.
    const optimisticMessage: ChatMessageView = {
      id: `pending_message_${clientMessageId}`,
      sessionId: optimisticSessionId,
      role: 'user',
      content: trimmedContent,
      status: 'optimistic',
      clientMessageId,
      createdAt: new Date().toISOString(),
      work: optimisticWork,
    }
    // accepted 왕복을 기다리면 첫 입력에서 DB append/TaskRun 생성 시간이 그대로 비어 보인다.
    // 텍스트는 서버 이벤트가 올 때 채우고, 즉시 보이는 상태는 스피너 전용 placeholder로만 둔다.
    const optimisticAssistantMessage: ChatMessageView = {
      id: `pending_assistant_${clientMessageId}`,
      sessionId: optimisticSessionId,
      role: 'assistant',
      content: '',
      status: 'streaming',
      clientMessageId,
      createdAt: new Date().toISOString(),
    }

    set((state) => ({
      messagesBySessionId: {
        ...state.messagesBySessionId,
        [optimisticSessionId]: [
          ...(state.messagesBySessionId[optimisticSessionId] ?? []),
          optimisticMessage,
          optimisticAssistantMessage,
        ],
      },
      pendingClientMessageIds: {
        ...state.pendingClientMessageIds,
        [clientMessageId]: optimisticSessionId,
      },
    }))
    playAgentChime()
    const visualizationSessionId = sessionId ?? optimisticSessionId
    const sessionPanels =
      useSessionStore.getState().agentPanelsBySessionId[visualizationSessionId] ?? []
    startVisualizationForSession(visualizationSessionId, clientMessageId, sessionPanels)
    if (
      sessionId !== undefined &&
      !sessionId.startsWith('pending_session_') &&
      sessionPanels.length === 0
    ) {
      refreshVisualizationSessionAgents(sessionId, clientMessageId)
    }

    try {
      const frame = await useAiRealtimeStore
        .getState()
        .sendCommand<AiRealtimeRawFrame>('session.message.create', {
          sessionId,
          content: trimmedContent,
          clientMessageId,
          settings,
          inputPayload,
        })

      get().handleRealtimeFrame(frame)
      const acceptedTaskRunId = getStringField(getFramePayload(frame), 'task_run_id', 'taskRunId')
      if (acceptedTaskRunId !== undefined) {
        // 빠른 agent 작업은 화면 effect가 돌기 전에 끝날 수 있다.
        // accepted 응답을 받는 즉시 구독해서 step/task 완료 이벤트 유실 구간을 줄인다.
        try {
          useAiRealtimeStore.getState().subscribeTask(acceptedTaskRunId)
        } catch (subscribeError) {
          console.error(subscribeError)
        }
        scheduleAcceptedTaskReplay(acceptedTaskRunId, set, get)
      }
      return frame
    } catch (error) {
      useAgentVisualizationStore.getState().settleCeoAtDesk(clientMessageId)
      markOptimisticMessageFailed(clientMessageId, set)
      throw error
    }
  },
  updateSession: async ({ sessionId, title, metadataPatch }) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('session.update', {
        sessionId,
        title,
        metadataPatch,
        clientCommandId: createClientCommandId(),
      })

    const updatedSession = getSessionFromMutationFrame(frame, sessionId)
    set((state) => ({
      sessionsById:
        updatedSession === null
          ? state.sessionsById
          : { ...state.sessionsById, [updatedSession.session_id]: updatedSession },
      lastError: null,
    }))
    get().handleRealtimeFrame(frame)
    return updatedSession
  },
  deleteSession: async (sessionId) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('session.delete', {
        sessionId,
        clientCommandId: createClientCommandId(),
      })

    get().handleRealtimeFrame(frame)
    set((state) => removeSessionFromState(state, sessionId))
  },
  updateSessionSettings: async ({ sessionId, settingsPatch }) => {
    const frame = await useAiRealtimeStore
      .getState()
      .sendCommand<AiRealtimeRawFrame>('session.settings.update', {
        sessionId,
        settings: settingsPatch,
        clientCommandId: createClientCommandId(),
      })

    const updatedSession = getSessionFromMutationFrame(frame, sessionId)
    set((state) => ({
      sessionsById:
        updatedSession === null
          ? state.sessionsById
          : { ...state.sessionsById, [updatedSession.session_id]: updatedSession },
      lastError: null,
    }))
    get().handleRealtimeFrame(frame)
    return updatedSession
  },
  fetchModelOptions: async (sessionId) => {
    set({ modelOptionsLoading: true, modelOptionsError: null })

    try {
      const frame = await useAiRealtimeStore
        .getState()
        .sendCommand<AiRealtimeRawFrame>('model.options', { sessionId })
      const options = normalizeModelOptions(getFramePayload(frame))
      set({ modelOptions: options, modelOptionsLoading: false, modelOptionsError: null })
      return options
    } catch (error) {
      const message = error instanceof Error ? error.message : '모델 목록 조회에 실패했습니다.'
      set({ modelOptionsLoading: false, modelOptionsError: message })
      throw error
    }
  },
  handleRealtimeFrame: (frame) => {
    switch (frame.type) {
      case 'session.list.result':
        mergeSessionList(frame, set)
        return
      case 'session.messages.list.result':
      case 'session.messages.result':
        mergeMessageList(frame, set)
        return
      case 'session.message.accepted':
        mergeAcceptedMessage(frame, set, get)
        return
      case 'session.message.delta':
        mergeAssistantDelta(frame, set)
        return
      case 'session.message.completed':
        mergeAssistantCompleted(frame, set)
        return
      case 'session.message.waiting':
        mergeAssistantWaiting(frame, set)
        return
      case 'session.message.failed':
        mergeAssistantFailed(frame, set)
        return
      case 'session.updated':
        mergeSessionUpdated(frame, set)
        return
      case 'session.deleted':
      case 'session.delete.result':
        mergeSessionDeleteResult(frame, set)
        return
      case 'session.settings.updated':
      case 'session.settings.update.result':
        mergeSessionMutationResult(frame, set)
        return
      case 'task.event':
        mergeTaskEventCompletionPayload(getFramePayload(frame), set)
        return
      default:
        return
    }
  },
  addExternalTaskPlaceholder: (sessionId, taskRunId) => {
    set((state) => {
      const existingMessages = state.messagesBySessionId[sessionId] ?? []
      const hasAssistantTask = existingMessages.some(
        (message) => message.role === 'assistant' && message.taskRunId === taskRunId,
      )
      if (hasAssistantTask) return {}

      return {
        messagesBySessionId: {
          ...state.messagesBySessionId,
          [sessionId]: [
            ...existingMessages,
            {
              id: `assistant_${taskRunId}`,
              sessionId,
              role: 'assistant' as const,
              content: '',
              status: 'streaming' as const,
              taskRunId,
              createdAt: new Date().toISOString(),
            },
          ],
        },
        sessionsById: upsertSessionPreview(state, {
          sessionId,
          activeTaskRunId: taskRunId,
          lastTaskRunStatus: 'RUNNING',
        }),
      }
    })
    const sessionPanels = useSessionStore.getState().agentPanelsBySessionId[sessionId] ?? []
    startVisualizationForSession(sessionId, taskRunId, sessionPanels)
    refreshVisualizationSessionAgents(sessionId, taskRunId)
  },
  clearChatState: () =>
    set({
      sessionsById: {},
      messagesBySessionId: {},
      pendingClientMessageIds: {},
      loadingSessionIds: {},
      sessionListLoading: false,
      sessionListError: null,
      modelOptions: null,
      modelOptionsLoading: false,
      modelOptionsError: null,
      lastError: null,
    }),
}))

const getRawSessionList = (payload: SessionListResultPayload | unknown): RawAiSession[] => {
  if (!isJsonObject(payload)) {
    return []
  }

  const list = Array.isArray(payload.sessions)
    ? payload.sessions
    : Array.isArray(payload.items)
      ? payload.items
      : []

  return list.filter(isRawAiSession)
}

const reconcileVisibleSessions = (
  previousSessionsById: Record<string, RawAiSession>,
  visibleSessions: RawAiSession[],
) => {
  const nextSessionsById: Record<string, RawAiSession> = {}

  Object.values(previousSessionsById).forEach((session) => {
    if (isPendingSession(session)) {
      nextSessionsById[session.session_id] = session
    }
  })

  visibleSessions.forEach((session) => {
    nextSessionsById[session.session_id] = reconcileSessionRunState(
      previousSessionsById[session.session_id],
      session,
    )
  })

  return nextSessionsById
}

const removeSessionFromState = (state: ChatState, sessionId: string): Partial<ChatState> => {
  const sessionsById = { ...state.sessionsById }
  const messagesBySessionId = { ...state.messagesBySessionId }
  delete sessionsById[sessionId]
  delete messagesBySessionId[sessionId]
  return { sessionsById, messagesBySessionId, lastError: null }
}

const isPendingSession = (session: RawAiSession) =>
  session.session_id.startsWith('pending_session_') || session.source === 'pending'

const isRemovedSession = (session: RawAiSession) =>
  session.deleted_at != null || session.status === 'DELETED'

const getRawMessageList = (payload: SessionMessagesListResultPayload | unknown): RawAiMessage[] => {
  if (!isJsonObject(payload)) {
    return []
  }

  const list = Array.isArray(payload.messages)
    ? payload.messages
    : Array.isArray(payload.items)
      ? payload.items
      : []

  return list.map(normalizeRawAiMessage).filter((message) => message !== null)
}

const toChatMessageView = (message: RawAiMessage): ChatMessageView => ({
  id: message.message_id,
  sessionId: message.session_id,
  role: message.role,
  content: message.content,
  status: message.role === 'assistant' ? 'completed' : 'accepted',
  taskRunId: typeof message.task_run_id === 'string' ? message.task_run_id : undefined,
  clientMessageId:
    typeof message.client_message_id === 'string' ? message.client_message_id : undefined,
  createdAt: typeof message.created_at === 'string' ? message.created_at : undefined,
  work: getWorkContextFromMetadata(message.metadata),
  raw: message,
})

const mergeSessionList = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const sessions = getRawSessionList(getFramePayload(frame)).filter(
    (session) => !isRemovedSession(session),
  )
  set((state) => ({
    sessionsById: reconcileVisibleSessions(state.sessionsById, sessions),
    sessionListLoading: false,
    sessionListError: null,
  }))
}

const upsertSessionPreview = (
  state: ChatState,
  input: {
    sessionId: string
    title?: string
    lastMessage?: string
    activeTaskRunId?: string | null
    lastTaskRunStatus?: string
  },
) => {
  const previous = state.sessionsById[input.sessionId]
  const now = new Date().toISOString()
  const hasActiveTaskRunId = Object.prototype.hasOwnProperty.call(input, 'activeTaskRunId')

  return {
    ...state.sessionsById,
    [input.sessionId]: {
      ...(previous ?? {
        session_id: input.sessionId,
        status: 'ACTIVE',
        source: 'api.session',
        created_at: now,
      }),
      title: previous?.title ?? input.title,
      last_message: input.lastMessage ?? previous?.last_message,
      last_message_at: now,
      active_task_run_id: hasActiveTaskRunId ? input.activeTaskRunId : previous?.active_task_run_id,
      last_task_run_status: input.lastTaskRunStatus ?? previous?.last_task_run_status,
      updated_at: now,
      message_count:
        typeof previous?.message_count === 'number' ? previous.message_count : undefined,
    },
  }
}

const mergeMessageList = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame)
  const messages = getRawMessageList(payload).map(toChatMessageView)
  const sessionId = getStringField(payload, 'session_id', 'sessionId') ?? messages[0]?.sessionId

  if (sessionId === undefined) {
    return
  }

  set((state) => {
    const mergedMessages = mergeLiveMessagesIntoPersistedList(
      messages,
      state.messagesBySessionId[sessionId] ?? [],
      sessionId,
    )
    const shouldClearSessionRun = shouldClearSessionRunFromPersistedMessages(
      state.sessionsById[sessionId],
      messages,
    )

    return {
      messagesBySessionId: {
        ...state.messagesBySessionId,
        [sessionId]: mergedMessages,
      },
      sessionsById: shouldClearSessionRun
        ? upsertSessionPreview(state, {
            sessionId,
            activeTaskRunId: null,
            lastTaskRunStatus: 'COMPLETED',
          })
        : state.sessionsById,
    }
  })
}

const mergeAcceptedMessage = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
  get: () => ChatState,
) => {
  const payload = getFramePayload(frame) as RawSessionMessageAcceptedPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const clientMessageId = getStringField(payload, 'client_message_id', 'clientMessageId')
  const userMessageId = getStringField(payload, 'user_message_id', 'userMessageId')
  const assistantMessageId = getStringField(payload, 'assistant_message_id', 'assistantMessageId')
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')

  if (sessionId === undefined) {
    return
  }
  if (taskRunId !== undefined) {
    const sessionPanels = useSessionStore.getState().agentPanelsBySessionId[sessionId] ?? []
    startVisualizationForSession(sessionId, taskRunId, sessionPanels)
    if (sessionPanels.length === 0) {
      refreshVisualizationSessionAgents(sessionId, taskRunId)
    }
  }

  const previousSessionId =
    clientMessageId !== undefined ? get().pendingClientMessageIds[clientMessageId] : undefined

  set((state) => {
    const sourceSessionId = previousSessionId ?? sessionId
    const previousMessages = state.messagesBySessionId[sourceSessionId] ?? []
    const placeholderId =
      assistantMessageId ?? (taskRunId === undefined ? undefined : `assistant_${taskRunId}`)
    const acceptedMessages = previousMessages.map((message) => {
      if (
        clientMessageId !== undefined &&
        message.role === 'assistant' &&
        message.clientMessageId === clientMessageId &&
        message.status === 'streaming'
      ) {
        // 전송 직후 만든 스피너 placeholder를 accepted 응답의 실제 TaskRun에 연결한다.
        // 새 assistant 메시지를 추가하지 않아야 말풍선이 두 번 깜빡이지 않는다.
        return {
          ...message,
          id: assistantMessageId ?? placeholderId ?? message.id,
          sessionId,
          taskRunId,
        }
      }
      if (message.clientMessageId !== clientMessageId) {
        return { ...message, sessionId }
      }
      return {
        ...message,
        id: userMessageId ?? message.id,
        sessionId,
        status: 'accepted' as const,
        taskRunId,
      }
    })

    const hasAssistantPlaceholder = acceptedMessages.some(
      (message) =>
        (assistantMessageId !== undefined && message.id === assistantMessageId) ||
        (taskRunId !== undefined &&
          message.role === 'assistant' &&
          message.taskRunId === taskRunId),
    )
    // accepted는 "작업을 시작했다"는 응답이고 자연어 답변은 뒤이어 온다.
    // 그래서 completed/delta가 오기 전까지 빈 assistant placeholder를 만들어 진행 중 상태를 보여 준다.
    const assistantPlaceholder =
      placeholderId === undefined || hasAssistantPlaceholder
        ? []
        : [
            {
              id: placeholderId,
              sessionId,
              role: 'assistant',
              content: '',
              status: 'streaming' as const,
              taskRunId,
            },
          ]

    const pendingClientMessageIds = { ...state.pendingClientMessageIds }
    if (clientMessageId !== undefined) {
      delete pendingClientMessageIds[clientMessageId]
    }

    const messagesBySessionId = { ...state.messagesBySessionId }
    if (sourceSessionId !== sessionId) {
      delete messagesBySessionId[sourceSessionId]
    }
    messagesBySessionId[sessionId] = [...acceptedMessages, ...assistantPlaceholder]

    return {
      messagesBySessionId,
      pendingClientMessageIds,
      sessionsById: upsertSessionPreview(state, {
        sessionId,
        title: acceptedMessages[0]?.content,
        lastMessage:
          acceptedMessages.find((message) => message.clientMessageId === clientMessageId)
            ?.content ?? acceptedMessages.find((message) => message.role === 'user')?.content,
        activeTaskRunId: taskRunId,
        lastTaskRunStatus: 'RUNNING',
      }),
    }
  })
}

const mergeAssistantDelta = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as RawSessionMessageDeltaPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const messageId = getStringField(payload, 'message_id', 'messageId')
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  const delta =
    typeof payload.delta === 'string'
      ? payload.delta
      : typeof payload.content_delta === 'string'
        ? payload.content_delta
        : ''

  if (sessionId === undefined || messageId === undefined || delta === '') {
    return
  }

  set((state) => ({
    messagesBySessionId: {
      ...state.messagesBySessionId,
      [sessionId]: upsertAssistantMessage(state.messagesBySessionId[sessionId] ?? [], {
        id: messageId,
        sessionId,
        contentDelta: delta,
        status: 'streaming',
        taskRunId,
      }),
    },
  }))
}

const mergeAssistantCompleted = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as RawSessionMessageCompletedPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const messageId = getStringField(payload, 'message_id', 'messageId')
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  const content = typeof payload.content === 'string' ? payload.content : undefined
  const status = getStringField(payload, 'status')
  const shouldClearRunningState = isTerminalSessionMessageCompletion(status, taskRunId)

  if (sessionId === undefined || messageId === undefined) {
    return
  }

  useAgentVisualizationStore.getState().settleCeoAtDesk(taskRunId)
  playAgentChime()
  toast.success('답변이 완료되었습니다', { position: 'bottom-right' })

  set((state) => {
    const nextMessages = upsertAssistantMessage(state.messagesBySessionId[sessionId] ?? [], {
      id: messageId,
      sessionId,
      content,
      status: 'completed',
      taskRunId,
    })

    return {
      messagesBySessionId: {
        ...state.messagesBySessionId,
        [sessionId]: nextMessages,
      },
      sessionsById: upsertSessionPreview(state, {
        sessionId,
        lastMessage: content,
        activeTaskRunId: shouldClearRunningState ? null : taskRunId,
        lastTaskRunStatus: shouldClearRunningState
          ? resolveCompletedSessionTaskStatus(status)
          : status,
      }),
    }
  })
}

const mergeAssistantWaiting = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as RawSessionMessageWaitingPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  const messageId =
    getStringField(payload, 'message_id', 'messageId') ??
    (taskRunId === undefined ? undefined : `assistant_${taskRunId}`)

  if (sessionId === undefined || messageId === undefined) {
    return
  }

  set((state) => ({
    messagesBySessionId: {
      ...state.messagesBySessionId,
      [sessionId]: upsertAssistantMessage(state.messagesBySessionId[sessionId] ?? [], {
        id: messageId,
        sessionId,
        content: '',
        status: 'waiting',
        taskRunId,
      }),
    },
    sessionsById: upsertSessionPreview(state, {
      sessionId,
      activeTaskRunId: taskRunId,
      lastTaskRunStatus: 'WAITING',
    }),
  }))
}

const mergeAssistantFailed = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as RawSessionMessageFailedPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const messageId =
    getStringField(payload, 'message_id', 'messageId') ??
    getStringField(payload, 'user_message_id', 'userMessageId')
  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  const errorPayload = isJsonObject(payload.error) ? payload.error : undefined
  const content = getStringField(errorPayload, 'message') ?? 'AI 응답 생성 중 오류가 발생했습니다.'

  if (sessionId === undefined || (messageId === undefined && taskRunId === undefined)) {
    return
  }

  set((state) => ({
    messagesBySessionId: {
      ...state.messagesBySessionId,
      [sessionId]: upsertAssistantMessage(state.messagesBySessionId[sessionId] ?? [], {
        id: messageId ?? `failed:${taskRunId}`,
        sessionId,
        content,
        status: 'failed',
        taskRunId,
      }),
    },
    sessionsById: upsertSessionPreview(state, {
      sessionId,
      lastMessage: content,
      activeTaskRunId: null,
      lastTaskRunStatus: 'FAILED',
    }),
  }))
}

const mergeSessionUpdated = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as RawSessionUpdatedPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const rawSession = isJsonObject(payload.session)
    ? normalizeRawSession(payload.session)
    : undefined
  const rawMessages = Array.isArray(payload.messages)
    ? payload.messages
    : Array.isArray(payload.items)
      ? payload.items
      : undefined
  const messages = rawMessages
    ?.map(normalizeRawAiMessage)
    .filter((message) => message !== null)
    .map(toChatMessageView)

  if (sessionId === undefined && rawSession === undefined) {
    return
  }

  const resolvedSessionId = sessionId ?? rawSession?.session_id
  if (resolvedSessionId === undefined) {
    return
  }

  if (rawSession !== undefined && isRemovedSession(rawSession)) {
    set((state) => removeSessionFromState(state, resolvedSessionId))
    return
  }

  set((state) => ({
    sessionsById:
      rawSession === undefined
        ? state.sessionsById
        : { ...state.sessionsById, [rawSession.session_id]: rawSession },
    messagesBySessionId:
      messages === undefined
        ? state.messagesBySessionId
        : { ...state.messagesBySessionId, [resolvedSessionId]: messages },
  }))
}

const mergeSessionMutationResult = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as SessionMutationResultPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  const session = getSessionFromMutationFrame(frame, sessionId)

  if (session === null) {
    return
  }

  if (isRemovedSession(session)) {
    set((state) => removeSessionFromState(state, session.session_id))
    return
  }

  set((state) => ({
    sessionsById: { ...state.sessionsById, [session.session_id]: session },
    lastError: null,
  }))
}

const mergeSessionDeleteResult = (
  frame: AiRealtimeRawFrame,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  const payload = getFramePayload(frame) as SessionDeleteResultPayload
  const sessionId = getStringField(payload, 'session_id', 'sessionId')
  if (sessionId === undefined) {
    return
  }

  set((state) => removeSessionFromState(state, sessionId))
}

const getSessionFromMutationFrame = (
  frame: AiRealtimeRawFrame,
  fallbackSessionId?: string,
): RawAiSession | null => {
  const payload = getFramePayload(frame)
  if (isJsonObject(payload) && isJsonObject(payload.session)) {
    const session = normalizeRawSession(payload.session)
    return session ?? null
  }

  if (!isJsonObject(payload)) {
    return null
  }

  const sessionId = getStringField(payload, 'session_id', 'sessionId') ?? fallbackSessionId
  if (sessionId === undefined) {
    return null
  }

  return normalizeRawSession({ ...payload, session_id: sessionId }) ?? null
}

const mergeTaskEventCompletionPayload = (
  payload: unknown,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  if (!isJsonObject(payload)) {
    return
  }

  const eventType = getStringField(payload, 'event_type', 'eventType')
  if (!isTerminalTaskEvent(eventType)) {
    return
  }

  const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
  if (taskRunId === undefined) {
    return
  }

  const content = getTaskEventCompletionContent(payload)
  const nextStatus: ChatMessageStatus = eventType === 'task.completed' ? 'completed' : 'failed'
  if (eventType === 'task.completed') {
    useAgentVisualizationStore.getState().settleCeoAtDesk(taskRunId)
  }

  set((state) => {
    const messagesBySessionId = { ...state.messagesBySessionId }
    let updatedSessionId: string | undefined

    for (const [sessionId, messages] of Object.entries(state.messagesBySessionId)) {
      const assistantIndex = messages.findIndex(
        (message) => message.role === 'assistant' && message.taskRunId === taskRunId,
      )
      const taskMessageIndex = messages.findIndex((message) => message.taskRunId === taskRunId)
      if (assistantIndex === -1 && taskMessageIndex === -1) {
        continue
      }

      updatedSessionId = sessionId
      if (assistantIndex === -1) {
        messagesBySessionId[sessionId] = [
          ...messages,
          {
            id: `assistant_${taskRunId}`,
            sessionId,
            role: 'assistant',
            content: content ?? '',
            status: nextStatus,
            taskRunId,
          },
        ]
        continue
      }

      // 일부 agent.loop 경로는 session.message.completed 없이 task.completed만 먼저 온다.
      // 이 경우 진행 placeholder를 최종 답변으로 닫아 채팅창이 계속 "작성 중"에 머물지 않게 한다.
      messagesBySessionId[sessionId] = messages.map((message, index) =>
        index === assistantIndex
          ? {
              ...message,
              content: content ?? message.content,
              status: nextStatus,
            }
          : message,
      )
    }

    if (updatedSessionId === undefined) {
      return { messagesBySessionId }
    }

    return {
      messagesBySessionId,
      sessionsById: upsertSessionPreview(state, {
        sessionId: updatedSessionId,
        lastMessage: content,
        activeTaskRunId: null,
        lastTaskRunStatus: eventType === 'task.completed' ? 'COMPLETED' : 'FAILED',
      }),
    }
  })
}

const scheduleAcceptedTaskReplay = (
  taskRunId: string,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
  get: () => ChatState,
) => {
  const replayIfStillStreaming = async () => {
    if (!hasStreamingAssistantForTask(get(), taskRunId)) {
      return
    }

    try {
      const events = await useTaskRunStore.getState().replayEvents(taskRunId)
      const terminalEvent = [...events]
        .reverse()
        .find((event) => isTerminalTaskEvent(event.event_type))
      if (terminalEvent !== undefined) {
        mergeTaskEventCompletionPayload(terminalEvent, set)
      }
    } catch (error) {
      console.error(error)
    }
  }

  window.setTimeout(() => void replayIfStillStreaming(), 2500)
  window.setTimeout(() => void replayIfStillStreaming(), 8000)
}

const hasStreamingAssistantForTask = (state: ChatState, taskRunId: string) =>
  Object.values(state.messagesBySessionId).some((messages) =>
    messages.some(
      (message) =>
        message.role === 'assistant' &&
        message.taskRunId === taskRunId &&
        message.status === 'streaming',
    ),
  )

const isTerminalTaskEvent = (eventType?: string) =>
  eventType === 'task.completed' || eventType === 'task.failed' || eventType === 'task.canceled'

const getTaskEventCompletionContent = (payload: Record<string, unknown>) => {
  const eventPayload = isJsonObject(payload.payload) ? payload.payload : undefined
  const content =
    getStringField(eventPayload, 'text', 'content') ??
    getStringField(eventPayload, 'result_text', 'resultText') ??
    getStringField(payload, 'summary_message', 'summaryMessage')

  return content?.trim() === '' ? undefined : content
}

const isTerminalSessionMessageCompletion = (status: string | undefined, taskRunId?: string) => {
  if (
    status === 'COMPLETED' ||
    status === 'FAILED' ||
    status === 'CANCELED' ||
    status === 'CANCELLED'
  ) {
    return true
  }

  return status === undefined && taskRunId !== undefined
}

const markOptimisticMessageFailed = (
  clientMessageId: string,
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
) => {
  set((state) => {
    const pendingSessionId = state.pendingClientMessageIds[clientMessageId]
    if (pendingSessionId === undefined) {
      return { pendingClientMessageIds: state.pendingClientMessageIds }
    }

    const pendingClientMessageIds = { ...state.pendingClientMessageIds }
    delete pendingClientMessageIds[clientMessageId]

    return {
      pendingClientMessageIds,
      messagesBySessionId: {
        ...state.messagesBySessionId,
        [pendingSessionId]: updateMessageStatus(
          state.messagesBySessionId[pendingSessionId] ?? [],
          clientMessageId,
          'failed',
        ),
      },
    }
  })
}

const updateMessageStatus = (
  messages: ChatMessageView[],
  clientMessageId: string,
  status: ChatMessageStatus,
) =>
  messages.map((message) =>
    message.clientMessageId === clientMessageId ? { ...message, status } : message,
  )

const upsertAssistantMessage = (
  messages: ChatMessageView[],
  update: {
    id: string
    sessionId: string
    content?: string
    contentDelta?: string
    taskRunId?: string
    status: ChatMessageView['status']
  },
) => {
  const index = messages.findIndex(
    (message) =>
      message.id === update.id ||
      (update.taskRunId !== undefined &&
        message.role === 'assistant' &&
        message.taskRunId === update.taskRunId),
  )
  if (index === -1) {
    return [
      ...messages,
      {
        id: update.id,
        sessionId: update.sessionId,
        role: 'assistant',
        content: update.content ?? update.contentDelta ?? '',
        status: update.status,
        taskRunId: update.taskRunId,
      },
    ]
  }

  return messages.map((message, messageIndex) =>
    messageIndex === index
      ? {
          ...message,
          id: update.id,
          content: update.content ?? `${message.content}${update.contentDelta ?? ''}`,
          status: update.status,
          taskRunId: update.taskRunId ?? message.taskRunId,
        }
      : message,
  )
}

const normalizeModelOptions = (payload: unknown): ModelOptionsResultPayload => {
  if (!isJsonObject(payload)) {
    return { providers: [], models: [] }
  }

  const rawPayload = payload as ModelOptionsRawResultPayload
  const providers = Array.isArray(rawPayload.providers)
    ? rawPayload.providers.map(normalizeModelProviderOption).filter(isModelProviderOption)
    : []
  const directModels = Array.isArray(rawPayload.models)
    ? rawPayload.models.map((model) => normalizeModelOption(model)).filter(isModelOption)
    : []
  const providerModels = providers.flatMap((provider) => provider.models)
  const model =
    typeof rawPayload.model === 'string' || rawPayload.model === null ? rawPayload.model : undefined

  return {
    ...payload,
    model,
    providers,
    models: directModels.length > 0 ? directModels : providerModels,
  }
}

const normalizeModelProviderOption = (value: unknown): AiModelProviderOption | null => {
  if (!isJsonObject(value)) {
    return null
  }

  const slug =
    getStringField(value, 'slug') ??
    getStringField(value, 'provider') ??
    getStringField(value, 'id') ??
    getStringField(value, 'name')
  if (slug === undefined) {
    return null
  }

  const rawModels = Array.isArray(value.models) ? value.models : []
  return {
    slug,
    label: getStringField(value, 'label', 'name') ?? slug,
    warning:
      getStringField(value, 'warning') ??
      getStringField(value, 'warning_message', 'warningMessage') ??
      null,
    isCurrent: value.is_current === true || value.isCurrent === true,
    models: rawModels.map((model) => normalizeModelOption(model, slug)).filter(isModelOption),
    raw: value,
  }
}

const normalizeModelOption = (value: unknown, provider?: string): AiModelOption | null => {
  if (typeof value === 'string') {
    return { id: value, label: value, provider }
  }
  if (!isJsonObject(value)) {
    return null
  }

  const id =
    getStringField(value, 'id') ??
    getStringField(value, 'model') ??
    getStringField(value, 'name') ??
    getStringField(value, 'slug')
  if (id === undefined) {
    return null
  }

  const usage = getNumberField(value, 'usage')
  const limit = getNumberField(value, 'limit')
  return {
    id,
    label: getStringField(value, 'label', 'name') ?? id,
    provider: getStringField(value, 'provider') ?? provider,
    warning:
      getStringField(value, 'warning') ??
      (usage !== undefined && limit !== undefined && usage >= limit
        ? '사용 한도에 도달했습니다.'
        : null),
    isCurrent: value.is_current === true || value.isCurrent === true,
    raw: value,
  }
}

const isModelProviderOption = (
  value: AiModelProviderOption | null,
): value is AiModelProviderOption => value !== null

const isModelOption = (value: AiModelOption | null): value is AiModelOption => value !== null

const isRawAiSession = (value: unknown): value is RawAiSession =>
  isJsonObject(value) && typeof value.session_id === 'string'

const normalizeRawSession = (value: Record<string, unknown>): RawAiSession | undefined => {
  const sessionId = getStringField(value, 'session_id', 'sessionId')
  if (sessionId === undefined) {
    return undefined
  }
  return {
    ...value,
    session_id: sessionId,
    title: typeof value.title === 'string' || value.title === null ? value.title : undefined,
    archived_at:
      getStringField(value, 'archived_at', 'archivedAt') ??
      (value.archived_at === null || value.archivedAt === null ? null : undefined),
    deleted_at:
      getStringField(value, 'deleted_at', 'deletedAt') ??
      (value.deleted_at === null || value.deletedAt === null ? null : undefined),
    settings: isJsonObject(value.settings)
      ? value.settings
      : value.settings === null
        ? null
        : undefined,
    active_task_run_id:
      getStringField(value, 'active_task_run_id', 'activeTaskRunId') ??
      (value.active_task_run_id === null ? null : undefined),
    last_task_run_status:
      getStringField(value, 'last_task_run_status', 'lastTaskRunStatus') ??
      (value.last_task_run_status === null ? null : undefined),
  }
}

const normalizeRawAiMessage = (value: unknown): RawAiMessage | null => {
  if (!isJsonObject(value)) {
    return null
  }

  const messageId = getStringField(value, 'message_id', 'messageId') ?? getStringField(value, 'id')
  const sessionId = getStringField(value, 'session_id', 'sessionId')
  const role = getStringField(value, 'role')
  const content =
    typeof value.content === 'string'
      ? value.content
      : typeof value.text === 'string'
        ? value.text
        : undefined

  if (
    messageId === undefined ||
    sessionId === undefined ||
    role === undefined ||
    content === undefined
  ) {
    return null
  }

  return {
    ...value,
    message_id: messageId,
    session_id: sessionId,
    role,
    content,
    task_run_id:
      getStringField(value, 'task_run_id', 'taskRunId') ??
      (typeof value.task_run_id === 'string' ? value.task_run_id : undefined),
    client_message_id:
      getStringField(value, 'client_message_id', 'clientMessageId') ??
      (typeof value.client_message_id === 'string' ? value.client_message_id : undefined),
  }
}

const getWorkContextFromInputPayload = (payload?: JsonObject) => {
  if (!isJsonObject(payload)) {
    return undefined
  }
  const id = getStringField(payload, 'workId', 'work_id')
  if (id === undefined) {
    return undefined
  }
  return {
    id,
    identifier: getStringField(payload, 'workIdentifier', 'work_identifier'),
    title: getStringField(payload, 'workTitle', 'work_title'),
    assigneeAgentId:
      getStringField(payload, 'workAssigneeAgentId', 'work_assignee_agent_id') ?? null,
  }
}

const getWorkContextFromMetadata = (metadata?: JsonObject | null) => {
  if (!isJsonObject(metadata)) {
    return undefined
  }
  const id = getStringField(metadata, 'work_id', 'workId')
  if (id === undefined) {
    return undefined
  }
  return {
    id,
    identifier: getStringField(metadata, 'work_identifier', 'workIdentifier'),
    title: getStringField(metadata, 'work_title', 'workTitle'),
    assigneeAgentId:
      getStringField(metadata, 'work_assignee_agent_id', 'workAssigneeAgentId') ?? null,
  }
}
