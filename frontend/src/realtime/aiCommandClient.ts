import {
  AI_REALTIME_PROTOCOL_VERSION,
  type AiCommandErrorPayload,
  type AiRealtimeCommandPayloadMap,
  type AiRealtimeCommandType,
  type AiRealtimeRawFrame,
  type JsonObject,
  isJsonObject,
} from './aiRealtimeTypes'
import { createRequestId } from '@/utils/requestId'

export type AiCommandClientTransport = {
  sendJson: (frame: JsonObject) => void
  onRawMessage: (handler: (frame: AiRealtimeRawFrame) => void) => () => void
  isOpen: () => boolean
}

export type SendCommandOptions = {
  requestId?: string
  timeoutMs?: number
}

export type AiCommandClient = {
  sendCommand: <TResult = unknown, TType extends AiRealtimeCommandType = AiRealtimeCommandType>(
    type: TType,
    payload: AiRealtimeCommandPayloadMap[TType],
    options?: SendCommandOptions,
  ) => Promise<TResult>
  handleFrame: (frame: AiRealtimeRawFrame) => void
  clearPending: (reason?: string) => void
  destroy: () => void
  getPendingRequestIds: () => string[]
}

type PendingCommand = {
  type: AiRealtimeCommandType
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  timeoutId: number
}

const DEFAULT_TIMEOUT_MS = 30_000

const MUTATING_COMMAND_IDEMPOTENCY_KEYS: Partial<Record<AiRealtimeCommandType, string[]>> = {
  'session.message.create': ['clientMessageId'],
  'session.message.retry': ['clientCommandId'],
  'session.message.undo': ['clientCommandId'],
  'session.history.compact': ['clientCommandId'],
  'session.update': ['clientCommandId'],
  'session.delete': ['clientCommandId'],
  'session.settings.update': ['clientCommandId'],
  'taskRun.resume': ['approvalResponseId', 'clientCommandId'],
  'taskRun.cancel': ['clientCommandId'],
}

export class AiCommandError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly requestId?: string
  readonly rawError: AiCommandErrorPayload

  constructor(error: AiCommandErrorPayload, requestId?: string) {
    super(error.message)
    this.name = 'AiCommandError'
    this.code = error.code
    this.retryable = error.retryable === true
    this.requestId = requestId
    this.rawError = error
  }
}

export class AiCommandTimeoutError extends Error {
  readonly requestId: string
  readonly commandType: AiRealtimeCommandType

  constructor(requestId: string, commandType: AiRealtimeCommandType) {
    super(`AI WebSocket command timed out: ${commandType}`)
    this.name = 'AiCommandTimeoutError'
    this.requestId = requestId
    this.commandType = commandType
  }
}

export const assertCommandIdempotencyKey = (
  type: AiRealtimeCommandType,
  payload: unknown,
): void => {
  const requiredKeys = MUTATING_COMMAND_IDEMPOTENCY_KEYS[type]
  if (requiredKeys === undefined) {
    return
  }

  if (!isJsonObject(payload)) {
    throw new Error(`${type} command payload는 객체여야 합니다.`)
  }

  const hasKey = requiredKeys.some((key) => {
    const value = payload[key]
    return typeof value === 'string' && value.trim() !== ''
  })

  if (!hasKey) {
    throw new Error(
      `${type} command에는 idempotency key(${requiredKeys.join(' 또는 ')})가 필요합니다.`,
    )
  }
}

export const createAiCommandClient = (
  transport: AiCommandClientTransport,
  defaultTimeoutMs = DEFAULT_TIMEOUT_MS,
): AiCommandClient => {
  const pending = new Map<string, PendingCommand>()

  const clearPendingRequest = (requestId: string) => {
    const command = pending.get(requestId)
    if (command === undefined) {
      return
    }
    window.clearTimeout(command.timeoutId)
    pending.delete(requestId)
  }

  const handleFrame = (frame: AiRealtimeRawFrame) => {
    if (typeof frame.requestId !== 'string') {
      return
    }

    const command = pending.get(frame.requestId)
    if (command === undefined) {
      return
    }

    clearPendingRequest(frame.requestId)

    if (frame.type === 'command.error' && frame.error !== undefined) {
      command.reject(new AiCommandError(frame.error, frame.requestId))
      return
    }

    // command 결과 frame은 서버 원본 envelope 전체를 반환한다. payload shape는 호출자가 선택적으로 해석한다.
    command.resolve(frame)
  }

  const unsubscribe = transport.onRawMessage(handleFrame)

  const clearPending = (reason = 'AI WebSocket command client가 종료되었습니다.') => {
    pending.forEach((command, requestId) => {
      window.clearTimeout(command.timeoutId)
      command.reject(new Error(`${reason} requestId=${requestId}`))
    })
    pending.clear()
  }

  const sendCommand = <
    TResult = unknown,
    TType extends AiRealtimeCommandType = AiRealtimeCommandType,
  >(
    type: TType,
    payload: AiRealtimeCommandPayloadMap[TType],
    options: SendCommandOptions = {},
  ): Promise<TResult> => {
    // message 생성, approval 응답, 취소처럼 서버 상태를 바꾸는 명령은 재전송될 수 있다.
    // 그래서 requestId와 별개로 서버가 중복 처리하지 않을 idempotency key를 반드시 보낸다.
    assertCommandIdempotencyKey(type, payload)

    if (!transport.isOpen()) {
      return Promise.reject(new Error('AI WebSocket이 열려 있지 않아 command를 보낼 수 없습니다.'))
    }

    const requestId = options.requestId ?? createRequestId()
    const timeoutMs = options.timeoutMs ?? defaultTimeoutMs

    return new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        pending.delete(requestId)
        reject(new AiCommandTimeoutError(requestId, type))
      }, timeoutMs)

      pending.set(requestId, {
        type,
        resolve: (value) => resolve(value as TResult),
        reject,
        timeoutId,
      })

      transport.sendJson({
        protocolVersion: AI_REALTIME_PROTOCOL_VERSION,
        type,
        requestId,
        sentAt: new Date().toISOString(),
        payload,
      })
    })
  }

  return {
    sendCommand,
    handleFrame,
    clearPending,
    destroy: () => {
      unsubscribe()
      clearPending()
    },
    getPendingRequestIds: () => Array.from(pending.keys()),
  }
}
