import { useAuthStore } from '@/store/useAuthStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useChatStore } from '@/store/useChatStore'
import type {
  ChatMessageView,
  SessionMessageAccepted,
  SessionMessageCreateCallbacks,
} from './chatTypes'

type RawFrame = {
  type?: unknown
  requestId?: unknown
  payload?: unknown
  data?: unknown
  error?: unknown
  [key: string]: unknown
}

type SendMessageInput = {
  sessionId?: string
  content: string
  callbacks?: SessionMessageCreateCallbacks
}

const COMMAND_TIMEOUT_MS = 15_000
const STREAM_GRACE_MS = 45_000

export const createClientMessageId = () =>
  `client_msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`

const createRequestId = () =>
  `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`

const getAiWebSocketUrl = () => {
  const url = import.meta.env.VITE_AI_WS_BASE_URL
  if (typeof url !== 'string' || url.trim() === '') {
    throw new Error('VITE_AI_WS_BASE_URL이 설정되지 않았습니다.')
  }
  return url
}

const getPayloadObject = (frame: RawFrame): Record<string, unknown> => {
  const payload = frame.payload ?? frame.data
  return typeof payload === 'object' && payload !== null ? (payload as Record<string, unknown>) : {}
}

const pickString = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string' && value.trim() !== '') return value
  }
  return undefined
}

const pickStringFromUnknown = (source: unknown, keys: string[]) => {
  if (typeof source !== 'object' || source === null) return undefined
  return pickString(source as Record<string, unknown>, keys)
}

const normalizeAccepted = (frame: RawFrame): SessionMessageAccepted => {
  const payload = getPayloadObject(frame)
  return {
    sessionId:
      pickString(payload, ['sessionId', 'session_id']) ??
      pickString(frame, ['sessionId', 'session_id']) ??
      '',
    userMessageId: pickString(payload, [
      'userMessageId',
      'user_message_id',
      'messageId',
      'message_id',
    ]),
    assistantMessageId: pickString(payload, [
      'assistantMessageId',
      'assistant_message_id',
      'assistantMessageID',
    ]),
    taskRunId: pickString(payload, ['taskRunId', 'task_run_id']),
  }
}

const parseJsonFrame = (data: string): RawFrame | null => {
  try {
    const parsed: unknown = JSON.parse(data)
    return typeof parsed === 'object' && parsed !== null ? (parsed as RawFrame) : null
  } catch {
    return null
  }
}

const openCommandSocket = () => {
  const accessToken = useAuthStore.getState().accessToken
  if (typeof accessToken !== 'string' || accessToken.trim() === '') {
    throw new Error('AI WebSocket 인증에 사용할 accessToken이 없습니다.')
  }

  const socket = new WebSocket(getAiWebSocketUrl())
  return { socket, accessToken }
}

const sendJson = (socket: WebSocket, value: Record<string, unknown>) => {
  socket.send(JSON.stringify(value))
}

const closeQuietly = (socket: WebSocket) => {
  if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
    socket.close(1000, 'chat command complete')
  }
}

export const sendSessionMessageCreate = ({
  sessionId,
  content,
  callbacks,
}: SendMessageInput): Promise<SessionMessageAccepted> => {
  const realtimeState = useAiRealtimeStore.getState()
  if (realtimeState.commandClient !== null && realtimeState.socketClient !== null) {
    let acceptedSeen = false
    let completedSeen = false
    let trackedTaskRunId: string | undefined
    let trackedAssistantMessageId: string | undefined
    let streamTimer: number | null = null

    const clearStreamTimer = () => {
      if (streamTimer !== null) {
        window.clearTimeout(streamTimer)
        streamTimer = null
      }
    }

    const unsubscribe = realtimeState.socketClient.onRawMessage((frame) => {
      if (frame.type === 'session.message.accepted') {
        const acceptedPayload = normalizeAccepted(frame)
        trackedTaskRunId = acceptedPayload.taskRunId
        trackedAssistantMessageId = acceptedPayload.assistantMessageId
        if (!acceptedSeen) {
          acceptedSeen = true
          callbacks?.onAccepted?.(acceptedPayload)
        }
        return
      }

      const payload = getPayloadObject(frame)
      const frameTaskRunId = pickString(payload, ['taskRunId', 'task_run_id'])
      const frameMessageId = pickString(payload, ['messageId', 'message_id'])
      const isTrackedFrame =
        (trackedTaskRunId !== undefined && frameTaskRunId === trackedTaskRunId) ||
        (trackedAssistantMessageId !== undefined && frameMessageId === trackedAssistantMessageId)

      if (!isTrackedFrame) {
        return
      }

      if (frame.type === 'session.message.delta') {
        const delta = pickString(payload, ['delta', 'content', 'text'])
        if (delta) callbacks?.onDelta?.(delta)
        return
      }

      if (frame.type === 'session.message.completed') {
        const finalContent = pickString(payload, ['content', 'text', 'message']) ?? ''
        completedSeen = true
        clearStreamTimer()
        callbacks?.onCompleted?.(finalContent)
        unsubscribe()
        return
      }

      if (frame.type === 'session.message.waiting' || frame.type === 'session.message.failed') {
        completedSeen = true
        clearStreamTimer()
        unsubscribe()
        return
      }

      if (frame.type === 'task.event') {
        callbacks?.onTaskEvent?.(payload as never)
      }
    })

    streamTimer = window.setTimeout(() => {
      if (!completedSeen) {
        unsubscribe()
      }
    }, STREAM_GRACE_MS)

    // realtime/store 워커가 제공하는 primary path다. 이 함수는 화면 쪽 optimistic 상태와
    // store action contract를 잇는 얇은 어댑터로만 동작한다.
    return useChatStore
      .getState()
      .sendMessage({ sessionId, content })
      .then((frame) => {
        const acceptedPayload = normalizeAccepted(frame as RawFrame)
        trackedTaskRunId = acceptedPayload.taskRunId
        trackedAssistantMessageId = acceptedPayload.assistantMessageId
        if (!acceptedSeen) {
          acceptedSeen = true
          callbacks?.onAccepted?.(acceptedPayload)
        }
        return acceptedPayload
      })
      .catch((error) => {
        clearStreamTimer()
        unsubscribe()
        throw error
      })
  }

  const requestId = createRequestId()
  const clientMessageId = createClientMessageId()
  const { socket, accessToken } = openCommandSocket()
  let accepted = false
  let completed = false

  return new Promise((resolve, reject) => {
    const commandTimer = window.setTimeout(() => {
      if (!accepted) {
        closeQuietly(socket)
        reject(new Error('session.message.create accepted 응답 시간이 초과되었습니다.'))
      }
    }, COMMAND_TIMEOUT_MS)

    const streamTimer = window.setTimeout(() => {
      if (accepted && !completed) closeQuietly(socket)
    }, STREAM_GRACE_MS)

    socket.addEventListener('open', () => {
      sendJson(socket, { type: 'auth.start', accessToken })
    })

    socket.addEventListener('error', () => {
      window.clearTimeout(commandTimer)
      window.clearTimeout(streamTimer)
      reject(new Error('AI WebSocket 연결에 실패했습니다.'))
    })

    socket.addEventListener('message', (message) => {
      if (typeof message.data !== 'string') return

      const frame = parseJsonFrame(message.data)
      if (!frame || typeof frame.type !== 'string') return

      if (frame.type === 'auth.ok') {
        // session.message.create는 첫 사용자 입력과 같은 mutating command라
        // requestId와 clientMessageId를 분리해 accepted 병합과 중복 실행 방지를 동시에 추적한다.
        sendJson(socket, {
          protocolVersion: 1,
          type: 'session.message.create',
          requestId,
          sentAt: new Date().toISOString(),
          payload: {
            sessionId,
            content,
            clientMessageId,
          },
        })
        return
      }

      if (frame.type === 'auth.failed' || frame.type === 'auth.required') {
        window.clearTimeout(commandTimer)
        window.clearTimeout(streamTimer)
        closeQuietly(socket)
        reject(new Error('AI WebSocket 인증이 만료되었거나 실패했습니다.'))
        return
      }

      if (frame.type === 'command.error' && frame.requestId === requestId) {
        const payload = getPayloadObject(frame)
        const messageText =
          pickString(payload, ['message']) ?? pickStringFromUnknown(frame.error, ['message'])
        window.clearTimeout(commandTimer)
        window.clearTimeout(streamTimer)
        closeQuietly(socket)
        reject(new Error(messageText ?? 'session.message.create 요청이 실패했습니다.'))
        return
      }

      if (frame.type === 'session.message.accepted' && frame.requestId === requestId) {
        const acceptedPayload = normalizeAccepted(frame)
        if (!acceptedPayload.sessionId) {
          window.clearTimeout(commandTimer)
          window.clearTimeout(streamTimer)
          closeQuietly(socket)
          reject(new Error('accepted 응답에 sessionId가 없습니다.'))
          return
        }
        accepted = true
        window.clearTimeout(commandTimer)
        callbacks?.onAccepted?.(acceptedPayload)
        resolve(acceptedPayload)
        return
      }

      if (frame.type === 'session.message.delta') {
        const payload = getPayloadObject(frame)
        const delta = pickString(payload, ['delta', 'content', 'text'])
        if (delta) callbacks?.onDelta?.(delta)
        return
      }

      if (frame.type === 'session.message.completed') {
        const payload = getPayloadObject(frame)
        const finalContent = pickString(payload, ['content', 'text', 'message']) ?? ''
        completed = true
        window.clearTimeout(streamTimer)
        callbacks?.onCompleted?.(finalContent)
        closeQuietly(socket)
        return
      }

      if (frame.type === 'session.message.waiting' || frame.type === 'session.message.failed') {
        completed = true
        window.clearTimeout(streamTimer)
        closeQuietly(socket)
        return
      }

      if (frame.type === 'task.event') {
        const payload = getPayloadObject(frame)
        callbacks?.onTaskEvent?.(payload as never)
      }
    })
  })
}

export const listSessionMessages = (sessionId: string): Promise<ChatMessageView[]> => {
  if (useAiRealtimeStore.getState().commandClient !== null) {
    return useChatStore
      .getState()
      .fetchMessages(sessionId)
      .then((messages) =>
        messages
          .filter((message) => message.role === 'user' || message.role === 'assistant')
          .map((message) => ({
            id: message.id,
            role: message.role === 'user' ? 'user' : 'assistant',
            content: message.content,
            createdAt: message.createdAt ?? new Date().toISOString(),
            status: message.status,
            taskRunId: message.taskRunId,
            clientMessageId: message.clientMessageId,
          })),
      )
  }

  const requestId = createRequestId()
  const { socket, accessToken } = openCommandSocket()

  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      closeQuietly(socket)
      reject(new Error('session.messages.list 응답 시간이 초과되었습니다.'))
    }, COMMAND_TIMEOUT_MS)

    socket.addEventListener('open', () => {
      sendJson(socket, { type: 'auth.start', accessToken })
    })

    socket.addEventListener('error', () => {
      window.clearTimeout(timer)
      reject(new Error('AI WebSocket 연결에 실패했습니다.'))
    })

    socket.addEventListener('message', (message) => {
      if (typeof message.data !== 'string') return
      const frame = parseJsonFrame(message.data)
      if (!frame || typeof frame.type !== 'string') return

      if (frame.type === 'auth.ok') {
        sendJson(socket, {
          protocolVersion: 1,
          type: 'session.messages.list',
          requestId,
          sentAt: new Date().toISOString(),
          payload: { sessionId },
        })
        return
      }

      if (frame.type === 'command.error' && frame.requestId === requestId) {
        window.clearTimeout(timer)
        closeQuietly(socket)
        reject(new Error('세션 메시지 조회에 실패했습니다.'))
        return
      }

      if (
        frame.requestId === requestId &&
        (frame.type === 'session.messages.result' || frame.type === 'session.messages.list.result')
      ) {
        const payload = getPayloadObject(frame)
        const rawMessages = Array.isArray(payload.messages) ? payload.messages : []
        window.clearTimeout(timer)
        closeQuietly(socket)
        resolve(rawMessages.map(normalizeMessage).filter((message) => message !== null))
      }
    })
  })
}

const normalizeMessage = (raw: unknown): ChatMessageView | null => {
  if (typeof raw !== 'object' || raw === null) return null
  const message = raw as Record<string, unknown>
  const id = pickString(message, ['id', 'messageId', 'message_id'])
  const role = pickString(message, ['role'])
  const content = pickString(message, ['content', 'text'])

  if (!id || !content || (role !== 'user' && role !== 'assistant' && role !== 'agent')) {
    return null
  }

  return {
    id,
    role: role === 'user' ? 'user' : 'assistant',
    content,
    createdAt: pickString(message, ['createdAt', 'created_at']) ?? new Date().toISOString(),
    status: 'completed',
    taskRunId: pickString(message, ['taskRunId', 'task_run_id']),
  }
}
