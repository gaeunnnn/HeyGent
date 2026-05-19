import { useEffect, useRef, type ReactNode } from 'react'
import { refreshAccessToken } from '@/apis/auth'
import { createAiCommandClient } from '@/realtime/aiCommandClient'
import type { AiCommandClient } from '@/realtime/aiCommandClient'
import { getFramePayload, getStringField, isJsonObject } from '@/realtime/aiRealtimeTypes'
import { createTaskRunSocket, type TaskRunSocketClient } from '@/realtime/taskRunSocket'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useAuthStore } from '@/store/useAuthStore'
import { useChatStore } from '@/store/useChatStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import { useWorkStore } from '@/store/useWorkStore'

type AiRealtimeProviderProps = {
  children: ReactNode
}

const PING_INTERVAL_MS = 25_000
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 30_000]

const getRecoveryLastSequence = (taskRunId: string) =>
  useTaskRunStore.getState().lastSequenceByTaskRunId[taskRunId]

export function AiRealtimeProvider({ children }: AiRealtimeProviderProps) {
  const accessToken = useAuthStore((state) => state.accessToken)
  const refreshToken = useAuthStore((state) => state.refreshToken)
  const setTokens = useAuthStore((state) => state.setTokens)
  const setSocketClient = useAiRealtimeStore((state) => state.setSocketClient)
  const setCommandClient = useAiRealtimeStore((state) => state.setCommandClient)
  const setConnectionStatus = useAiRealtimeStore((state) => state.setConnectionStatus)
  const setAuthStatus = useAiRealtimeStore((state) => state.setAuthStatus)
  const recordRawFrame = useAiRealtimeStore((state) => state.recordRawFrame)
  const setLastError = useAiRealtimeStore((state) => state.setLastError)
  const socketRef = useRef<TaskRunSocketClient | null>(null)
  const commandClientRef = useRef<AiCommandClient | null>(null)
  const pingIntervalRef = useRef<number | null>(null)
  const activeTaskPollIntervalRef = useRef<number | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const reconnectAttemptRef = useRef(0)
  const clientGenerationRef = useRef(0)
  const suppressedCloseGenerationsRef = useRef<Set<number>>(new Set())
  const refreshAttemptedRef = useRef(false)
  const activeRecoveryInFlightRef = useRef(false)
  const pendingRecoveryClientRef = useRef<TaskRunSocketClient | null>(null)
  const snapshotFetchedTaskRunsRef = useRef<Set<string>>(new Set())
  const autoSubscribedChildTaskRunsRef = useRef<Set<string>>(new Set())
  const externalTaskSessionMapRef = useRef<Map<string, string>>(new Map())

  useEffect(() => {
    const clearPingInterval = () => {
      if (pingIntervalRef.current !== null) {
        window.clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }
    }

    const clearActiveTaskPollInterval = () => {
      if (activeTaskPollIntervalRef.current !== null) {
        window.clearInterval(activeTaskPollIntervalRef.current)
        activeTaskPollIntervalRef.current = null
      }
    }

    const clearReconnectTimeout = () => {
      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }

    const clearExposedClient = (
      socketClient: TaskRunSocketClient | null,
      commandClient: AiCommandClient | null,
    ) => {
      const realtimeState = useAiRealtimeStore.getState()

      if (realtimeState.socketClient === socketClient) {
        setSocketClient(null)
      }
      if (realtimeState.commandClient === commandClient) {
        setCommandClient(null)
      }
    }

    const cleanupClient = (closeSocket: boolean) => {
      const socketClient = socketRef.current
      const commandClient = commandClientRef.current
      const generation = clientGenerationRef.current

      clearPingInterval()
      clearActiveTaskPollInterval()
      commandClient?.destroy()

      if (commandClientRef.current === commandClient) {
        commandClientRef.current = null
      }

      if (closeSocket && socketClient !== null) {
        suppressedCloseGenerationsRef.current.add(generation)
        socketClient.close(1000, 'AI realtime provider cleanup')
      }
      if (socketRef.current === socketClient) {
        socketRef.current = null
      }
      clearExposedClient(socketClient, commandClient)
    }

    const connect = (token: string) => {
      cleanupClient(true)
      const generation = clientGenerationRef.current + 1
      clientGenerationRef.current = generation
      setConnectionStatus(reconnectAttemptRef.current > 0 ? 'reconnecting' : 'connecting')
      setAuthStatus('authenticating')
      setLastError(null)

      const socketClient = createTaskRunSocket({ accessToken: token })
      const commandClient = createAiCommandClient(socketClient)
      socketRef.current = socketClient
      commandClientRef.current = commandClient

      socketClient.onOpen(() => {
        if (generation !== clientGenerationRef.current) {
          return
        }
        setConnectionStatus('open')
        clearPingInterval()
        pingIntervalRef.current = window.setInterval(() => {
          try {
            socketClient.ping()
          } catch (error) {
            setLastError(error instanceof Error ? error.message : 'AI WebSocket ping 실패')
          }
        }, PING_INTERVAL_MS)
      })

      socketClient.onRawMessage((frame) => {
        if (generation !== clientGenerationRef.current) {
          return
        }
        recordRawFrame(frame)
        useChatStore.getState().handleRealtimeFrame(frame)
        useTaskRunStore.getState().handleRealtimeFrame(frame)
        useWorkStore.getState().handleRealtimeFrame(frame)
        recoverTaskRunAfterGap(frame)
        subscribeChildTaskRunFromParentEvent(socketClient, frame)
        if (frame.type === 'task.new') {
          const typedFrame = frame as { type: string; taskRunId?: string; sessionId?: string }
          const taskRunId = typedFrame.taskRunId
          const sessionId = typedFrame.sessionId
          if (taskRunId && !useAiRealtimeStore.getState().subscriptionsByTaskRunId[taskRunId]) {
            useAiRealtimeStore.getState().subscribeTask(taskRunId, undefined)
          }
          if (sessionId && taskRunId) {
            externalTaskSessionMapRef.current.set(taskRunId, sessionId)
            useChatStore.getState().addExternalTaskPlaceholder(sessionId, taskRunId)
            void useChatStore.getState().fetchMessages(sessionId)
            void useTaskRunStore.getState().fetchSnapshot(taskRunId)
          }
        }
        if (frame.type === 'task.event') {
          const payload = getFramePayload(frame)
          if (isJsonObject(payload)) {
            const eventType = getStringField(payload, 'event_type', 'eventType')
            const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
            if (
              taskRunId &&
              (eventType === 'task.completed' ||
                eventType === 'task.failed' ||
                eventType === 'task.canceled')
            ) {
              const sessionId = externalTaskSessionMapRef.current.get(taskRunId)
              if (sessionId) {
                externalTaskSessionMapRef.current.delete(taskRunId)
                void useChatStore.getState().fetchMessages(sessionId)
              }
            }
          }
        }
      })

      socketClient.onMessage((event) => {
        if (generation !== clientGenerationRef.current) {
          return
        }

        if (event.type === 'auth.ok') {
          refreshAttemptedRef.current = false
          reconnectAttemptRef.current = 0
          setSocketClient(socketClient)
          setCommandClient(commandClient)
          setAuthStatus('authenticated')
          setConnectionStatus('authenticated')
          void useChatStore
            .getState()
            .fetchSessions()
            .catch((error) => {
              setLastError(
                error instanceof Error ? error.message : '세션 목록 조회에 실패했습니다.',
              )
            })
          void recoverAndResubscribeTasks(socketClient)
          clearActiveTaskPollInterval()
          activeTaskPollIntervalRef.current = window.setInterval(() => {
            if (socketRef.current !== socketClient || !socketClient.isAuthenticated()) {
              return
            }
            void useTaskRunStore
              .getState()
              .fetchActiveTaskRuns()
              .then((taskRuns) => {
                const subscriptions = useAiRealtimeStore.getState().subscriptionsByTaskRunId
                for (const taskRun of taskRuns) {
                  if (!subscriptions[taskRun.task_run_id]) {
                    useAiRealtimeStore
                      .getState()
                      .subscribeTask(
                        taskRun.task_run_id,
                        getRecoveryLastSequence(taskRun.task_run_id),
                      )
                  }
                }
              })
              .catch(() => {})
          }, 10_000)
          return
        }

        if (event.type === 'auth.failed' || event.type === 'auth.required') {
          setAuthStatus('failed')
          void refreshAndReconnect()
        }
      })

      socketClient.onClose(() => {
        if (generation === clientGenerationRef.current) {
          clearPingInterval()
        }
        commandClient.clearPending('AI WebSocket 연결이 닫혔습니다.')

        if (commandClientRef.current === commandClient) {
          commandClientRef.current = null
        }
        if (socketRef.current === socketClient) {
          socketRef.current = null
        }
        clearExposedClient(socketClient, commandClient)

        // cleanup이나 교체가 의도적으로 닫은 이전 세대 소켓은 재연결 대상이 아니다.
        if (suppressedCloseGenerationsRef.current.delete(generation)) {
          return
        }

        // 오래된 close 이벤트가 최신 소켓 세대를 덮어쓰거나 재연결 타이머를 만들지 않게 막는다.
        if (generation !== clientGenerationRef.current) {
          return
        }

        const currentAccessToken = useAuthStore.getState().accessToken
        if (currentAccessToken === null || currentAccessToken.trim() === '') {
          setConnectionStatus('closed')
          return
        }

        setAuthStatus('authenticating')
        scheduleReconnect(generation, currentAccessToken)
      })

      socketClient.onError(() => {
        if (generation !== clientGenerationRef.current) {
          return
        }
        setConnectionStatus('error')
        setLastError('AI WebSocket 연결 오류가 발생했습니다.')
      })
    }

    const refreshAndReconnect = async () => {
      if (refreshToken === null || refreshAttemptedRef.current) {
        const currentGeneration = clientGenerationRef.current
        if (socketRef.current !== null) {
          suppressedCloseGenerationsRef.current.add(currentGeneration)
        }
        setConnectionStatus('closed')
        socketRef.current?.close(4001, 'AI auth failed')
        return
      }

      refreshAttemptedRef.current = true
      try {
        const response = await refreshAccessToken(refreshToken)
        setTokens(response.data.accessToken, response.data.refreshToken)
        connect(response.data.accessToken)
      } catch (error) {
        setLastError(error instanceof Error ? error.message : 'AI WebSocket 재인증에 실패했습니다.')
        const currentGeneration = clientGenerationRef.current
        if (socketRef.current !== null) {
          suppressedCloseGenerationsRef.current.add(currentGeneration)
        }
        setConnectionStatus('closed')
        socketRef.current?.close(4001, 'AI auth refresh failed')
      }
    }

    const scheduleReconnect = (generation: number, token: string) => {
      if (token.trim() === '') {
        setConnectionStatus('closed')
        return
      }

      setConnectionStatus('reconnecting')
      const delay =
        RECONNECT_DELAYS_MS[Math.min(reconnectAttemptRef.current, RECONNECT_DELAYS_MS.length - 1)]
      reconnectAttemptRef.current += 1
      clearReconnectTimeout()
      reconnectTimeoutRef.current = window.setTimeout(() => {
        // 타이머가 실행될 때 세대가 바뀌어 있으면 이미 새 소켓이 담당 중인 상태다.
        if (generation !== clientGenerationRef.current) {
          return
        }

        const currentAccessToken = useAuthStore.getState().accessToken
        if (currentAccessToken !== token) {
          return
        }

        connect(token)
      }, delay)
    }

    const recoverAndResubscribeTasks = async (socketClient: TaskRunSocketClient) => {
      if (activeRecoveryInFlightRef.current) {
        // 이전 소켓 복구가 진행 중이면 최신 소켓을 기억했다가 finally에서 다시 돌린다.
        pendingRecoveryClientRef.current = socketClient
        return
      }

      activeRecoveryInFlightRef.current = true
      pendingRecoveryClientRef.current = null

      try {
        let activeTaskRunIds: string[] = []
        try {
          // 새로고침/재연결 직후 서버가 아직 진행 중이라고 아는 TaskRun을 먼저 가져온다.
          activeTaskRunIds = (await useTaskRunStore.getState().fetchActiveTaskRuns()).map(
            (taskRun) => taskRun.task_run_id,
          )
        } catch (error) {
          setLastError(
            error instanceof Error ? error.message : '활성 TaskRun 목록 복구에 실패했습니다.',
          )
        }

        if (socketRef.current !== socketClient || !socketClient.isAuthenticated()) {
          return
        }

        const subscriptionIds = Object.values(
          useAiRealtimeStore.getState().subscriptionsByTaskRunId,
        ).map((subscription) => subscription.task_run_id)
        const taskRunIds = Array.from(new Set([...subscriptionIds, ...activeTaskRunIds]))

        for (const taskRunId of taskRunIds) {
          try {
            // recoverTaskRun은 놓친 event를 replay하고, 보관 구간이 부족하면 snapshot으로 현재 상태를 채운다.
            await useTaskRunStore.getState().recoverTaskRun(taskRunId)

            if (socketRef.current !== socketClient || !socketClient.isAuthenticated()) {
              return
            }

            useAiRealtimeStore
              .getState()
              .subscribeTask(taskRunId, getRecoveryLastSequence(taskRunId), { force: true })
          } catch (error) {
            setLastError(error instanceof Error ? error.message : 'TaskRun 재구독에 실패했습니다.')
          }
        }
      } finally {
        activeRecoveryInFlightRef.current = false
        const pendingSocketClient: TaskRunSocketClient | null = pendingRecoveryClientRef.current
        pendingRecoveryClientRef.current = null
        if (
          pendingSocketClient !== null &&
          socketRef.current === pendingSocketClient &&
          (pendingSocketClient as TaskRunSocketClient).isAuthenticated()
        ) {
          void recoverAndResubscribeTasks(pendingSocketClient)
        }
      }
    }

    const recoverTaskRunAfterGap = (frame: { type: string; payload?: unknown; data?: unknown }) => {
      if (frame.type !== 'task.event') {
        return
      }

      const payload = getFramePayload(frame)
      if (!isJsonObject(payload)) {
        return
      }

      const taskRunId = getStringField(payload, 'task_run_id', 'taskRunId')
      if (taskRunId === undefined) {
        return
      }

      // taskRunsById에 없거나 displayContext가 빠진 task run이면 활성 목록을 조회해 displayContext를 채운다.
      const existingInStore = useTaskRunStore.getState().taskRunsById[taskRunId]
      if (
        (!existingInStore || !existingInStore.displayContext?.actorAgent) &&
        !snapshotFetchedTaskRunsRef.current.has(taskRunId)
      ) {
        snapshotFetchedTaskRunsRef.current.add(taskRunId)
        void useTaskRunStore
          .getState()
          .fetchActiveTaskRuns()
          .catch((error) => {
            setLastError(
              error instanceof Error ? error.message : '활성 TaskRun 목록 조회에 실패했습니다.',
            )
          })
      }

      if (useTaskRunStore.getState().replayNeededByTaskRunId[taskRunId] !== true) {
        return
      }

      // sequence gap을 감지한 TaskRun은 다음 live event를 받는 즉시 복구를 시도한다.
      void useTaskRunStore
        .getState()
        .recoverTaskRun(taskRunId)
        .then(() => {
          const currentSocketClient = socketRef.current
          if (currentSocketClient === null || !currentSocketClient.isAuthenticated()) {
            return
          }
          useAiRealtimeStore.getState().subscribeTask(taskRunId, getRecoveryLastSequence(taskRunId))
        })
        .catch((error) => {
          setLastError(
            error instanceof Error ? error.message : 'TaskRun 이벤트 복구에 실패했습니다.',
          )
        })
    }

    const subscribeChildTaskRunFromParentEvent = (
      socketClient: TaskRunSocketClient,
      frame: { type: string; payload?: unknown; data?: unknown },
    ) => {
      if (frame.type !== 'task.event') {
        return
      }

      const taskEvent = getFramePayload(frame)
      if (!isJsonObject(taskEvent)) {
        return
      }

      const eventPayload = taskEvent.payload
      if (!isJsonObject(eventPayload)) {
        return
      }

      const reason = getStringField(eventPayload, 'reason')
      if (reason === undefined || !reason.startsWith('session_agent_work.')) {
        return
      }

      const parentTaskRunId = getStringField(taskEvent, 'task_run_id', 'taskRunId')
      const childTaskRunId =
        getStringField(eventPayload, 'childTaskRunId', 'child_task_run_id') ??
        getStringField(eventPayload, 'taskRunId', 'task_run_id')

      if (
        childTaskRunId === undefined ||
        childTaskRunId === parentTaskRunId ||
        autoSubscribedChildTaskRunsRef.current.has(childTaskRunId)
      ) {
        return
      }

      autoSubscribedChildTaskRunsRef.current.add(childTaskRunId)

      try {
        useAiRealtimeStore
          .getState()
          .subscribeTask(childTaskRunId, getRecoveryLastSequence(childTaskRunId))
      } catch (error) {
        setLastError(error instanceof Error ? error.message : 'child TaskRun 구독에 실패했습니다.')
        return
      }

      void useTaskRunStore
        .getState()
        .fetchSnapshot(childTaskRunId)
        .catch(() => {})

      void useTaskRunStore
        .getState()
        .recoverTaskRun(childTaskRunId)
        .then(() => {
          if (socketRef.current !== socketClient || !socketClient.isAuthenticated()) {
            return
          }
          useAiRealtimeStore
            .getState()
            .subscribeTask(childTaskRunId, getRecoveryLastSequence(childTaskRunId), { force: true })
        })
        .catch((error) => {
          setLastError(
            error instanceof Error ? error.message : 'child TaskRun 이벤트 복구에 실패했습니다.',
          )
        })
    }

    clearReconnectTimeout()

    if (accessToken === null || accessToken.trim() === '') {
      cleanupClient(true)
      setConnectionStatus('idle')
      setAuthStatus('anonymous')
      return () => {
        clearReconnectTimeout()
        cleanupClient(true)
      }
    }

    connect(accessToken)

    return () => {
      clearReconnectTimeout()
      cleanupClient(true)
    }
  }, [
    accessToken,
    refreshToken,
    recordRawFrame,
    setAuthStatus,
    setCommandClient,
    setConnectionStatus,
    setLastError,
    setSocketClient,
    setTokens,
  ])

  return children
}
