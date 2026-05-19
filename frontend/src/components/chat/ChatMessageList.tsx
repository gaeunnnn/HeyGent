import { ArrowDown } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatMessageItem } from './ChatMessageItem'
import type { ChatMessageView } from '@/types/aiChat'
import type { ActivityItemView, RawStepRun, TaskRunSummaryView } from '@/types/taskRuns'

const NEAR_BOTTOM_THRESHOLD = 96
const SHOW_JUMP_THRESHOLD = 220

type ChatMessageListProps = {
  messages: ChatMessageView[]
  activitiesByTaskRunId: Record<string, ActivityItemView[]>
  stepRunsByTaskRunId: Record<string, RawStepRun[]>
  taskRunSummariesById: Record<string, TaskRunSummaryView>
  onOpenTaskRun: (taskRunId: string) => void
  focusedTaskRunTarget?: { taskRunId: string; requestId: number }
  assistantName?: string
}

export function ChatMessageList({
  messages,
  activitiesByTaskRunId,
  stepRunsByTaskRunId,
  taskRunSummariesById,
  onOpenTaskRun,
  focusedTaskRunTarget,
  assistantName,
}: ChatMessageListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const wasNearBottomRef = useRef(true)
  const latestMessageIdRef = useRef<string | undefined>(messages.at(-1)?.id)
  const sessionIdRef = useRef<string | undefined>(messages.at(-1)?.sessionId)
  const didInitialScrollRef = useRef(false)
  const handledAssistantScrollIdsRef = useRef(
    new Set(
      messages.filter((message) => message.role === 'assistant').map((message) => message.id),
    ),
  )
  const [showJump, setShowJump] = useState(false)

  const getDistanceFromBottom = useCallback(() => {
    const element = scrollRef.current
    if (!element) return 0
    return element.scrollHeight - element.scrollTop - element.clientHeight
  }, [])

  const updateScrollState = useCallback(() => {
    const distanceFromBottom = getDistanceFromBottom()
    wasNearBottomRef.current = distanceFromBottom <= NEAR_BOTTOM_THRESHOLD
    setShowJump(distanceFromBottom > SHOW_JUMP_THRESHOLD)
  }, [getDistanceFromBottom])

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    bottomRef.current?.scrollIntoView({ behavior, block: 'end' })
    setShowJump(false)
    wasNearBottomRef.current = true
  }, [])

  const scrollToMessageStart = useCallback(
    (messageId: string) => {
      const scrollContainer = scrollRef.current
      const target = [
        ...(scrollContainer?.querySelectorAll<HTMLElement>('[data-chat-message-id]') ?? []),
      ].find((element) => element.dataset.chatMessageId === messageId)

      target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      window.requestAnimationFrame(updateScrollState)
    },
    [updateScrollState],
  )

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return

    updateScrollState()
    element.addEventListener('scroll', updateScrollState, { passive: true })
    return () => element.removeEventListener('scroll', updateScrollState)
  }, [updateScrollState])

  useEffect(() => {
    const latestMessage = messages.at(-1)
    const latestMessageId = latestMessage?.id
    const latestSessionId = latestMessage?.sessionId
    if (latestSessionId !== sessionIdRef.current) {
      sessionIdRef.current = latestSessionId
      latestMessageIdRef.current = latestMessageId
      didInitialScrollRef.current = false
      wasNearBottomRef.current = true
      handledAssistantScrollIdsRef.current = new Set(
        messages.filter((message) => message.role === 'assistant').map((message) => message.id),
      )
    }
    const isNewLatestMessage = latestMessageId !== latestMessageIdRef.current
    latestMessageIdRef.current = latestMessageId

    if (latestMessage === undefined) {
      wasNearBottomRef.current = true
      return
    }

    if (!didInitialScrollRef.current) {
      didInitialScrollRef.current = true
      scrollToBottom('auto')
      return
    }

    if (isNewLatestMessage && latestMessage.role === 'user') {
      scrollToBottom()
      return
    }

    if (
      isNewLatestMessage &&
      latestMessage.role === 'assistant' &&
      !handledAssistantScrollIdsRef.current.has(latestMessage.id)
    ) {
      handledAssistantScrollIdsRef.current.add(latestMessage.id)
      scrollToMessageStart(latestMessage.id)
      return
    }

    window.requestAnimationFrame(updateScrollState)
  }, [messages, scrollToBottom, scrollToMessageStart, updateScrollState])

  useEffect(() => {
    if (focusedTaskRunTarget === undefined) return

    const scrollContainer = scrollRef.current
    // taskRunId를 CSS selector 문자열로 직접 조립하지 않고 DOM dataset으로 비교한다.
    // 이렇게 해두면 서버 ID 형식이 바뀌어도 카드 클릭 위치 이동이 깨질 가능성이 낮다.
    const target = [
      ...(scrollContainer?.querySelectorAll<HTMLElement>('[data-chat-task-run-id]') ?? []),
    ].find((element) => element.dataset.chatTaskRunId === focusedTaskRunTarget.taskRunId)
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusedTaskRunTarget])

  return (
    <div className="bg-background relative min-h-0 flex-1">
      <div ref={scrollRef} className="bg-background h-full overflow-y-auto px-4 pt-6 pb-20">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          {messages.map((message) => (
            <div
              key={message.id}
              data-chat-message-id={message.id}
              {...(message.taskRunId === undefined
                ? {}
                : { 'data-chat-task-run-id': message.taskRunId })}
            >
              <ChatMessageItem
                message={message}
                activities={
                  message.taskRunId === undefined
                    ? []
                    : (activitiesByTaskRunId[message.taskRunId] ?? [])
                }
                taskRunSummary={
                  message.taskRunId === undefined
                    ? undefined
                    : taskRunSummariesById[message.taskRunId]
                }
                stepRuns={
                  message.taskRunId === undefined
                    ? []
                    : (stepRunsByTaskRunId[message.taskRunId] ?? [])
                }
                onOpenTaskRun={onOpenTaskRun}
                assistantName={assistantName}
              />
            </div>
          ))}
          <div ref={bottomRef} aria-hidden="true" />
        </div>
      </div>
      {showJump && (
        <div className="pointer-events-none absolute right-0 bottom-4 left-0 z-10 mx-auto max-w-3xl px-4 sm:bottom-5">
          <button
            type="button"
            onClick={() => scrollToBottom()}
            aria-label="가장 아래 메시지로 이동"
            className="border-border bg-popover text-foreground hover:bg-accent active:bg-accent/80 pointer-events-auto ml-auto flex items-center gap-1.5 rounded-full border px-3 py-2 text-xs shadow-sm transition-colors"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            아래로
          </button>
        </div>
      )}
    </div>
  )
}
