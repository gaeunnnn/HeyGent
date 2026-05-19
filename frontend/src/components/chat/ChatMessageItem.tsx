import { CheckCircle2, Clock3, ListTodo, Loader2, XCircle } from 'lucide-react'
import type { ChatMessageView } from '@/types/aiChat'
import type {
  ActivityItemView,
  RawStepRun,
  TaskRunSummaryView,
  TaskRunStatusTone,
} from '@/types/taskRuns'
import { toTaskRunStatusTone } from '@/utils/taskRunStatusView'
import { shouldShowAssistantTaskRunProgress } from '@/utils/taskRunDisplayStatus'
import {
  toStepProgressSentence,
  toUserFacingTaskTitle,
} from '@/components/taskRuns/stepRunActivityPanel/activityPanelText'
import { TaskRunStatusIcon } from '@/components/taskRuns/stepRunActivityPanel/TaskRunStatusIcon'
import { ChatMarkdown } from '@/components/chat/ChatMarkdown'

type ChatMessageItemProps = {
  message: ChatMessageView
  activities?: ActivityItemView[]
  stepRuns?: RawStepRun[]
  taskRunSummary?: TaskRunSummaryView
  onOpenTaskRun?: (taskRunId: string) => void
  assistantName?: string
}

export function ChatMessageItem({
  message,
  activities = [],
  stepRuns = [],
  taskRunSummary,
  onOpenTaskRun,
  assistantName,
}: ChatMessageItemProps) {
  const isUser = message.role === 'user'
  const taskStatus =
    typeof taskRunSummary?.raw?.status === 'string' ? taskRunSummary.raw.status : undefined
  const showTaskRunProgress =
    !isUser &&
    shouldShowAssistantTaskRunProgress({
      messageStatus: message.status,
      taskStatus,
      stepRunCount: stepRuns.length,
    })
  const taskRunChip = isUser
    ? undefined
    : getAssistantTaskRunChip(activities, taskRunSummary, message.status)
  const taskRunProgress = showTaskRunProgress
    ? getAssistantTaskRunProgress(stepRuns, taskRunSummary)
    : undefined
  // 메시지 본문이 비어 있고 어시스턴트의 진행 표시(progress 또는 chip)가 있을 땐
  // 본문 자리의 단순 로딩 스피너를 숨기고, 진행 상태 자체가 그 자리에 보이도록 한다.
  const hasAssistantProgressIndicator = !isUser && (taskRunProgress || taskRunChip)
  const shouldShowMessageBody =
    message.content.trim() !== '' ||
    isUser ||
    (!isTerminalTaskStatus(taskStatus) && !hasAssistantProgressIndicator)

  return (
    <article className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mt-1 h-8 w-8 shrink-0 overflow-hidden rounded-full">
          <img
            src="/assets/agents/ceo/ceo_profile_img.png"
            alt={assistantName?.trim() || '팀장 에이전트'}
            className="h-full w-full object-cover"
          />
        </div>
      )}
      <div className={`max-w-[78%] space-y-1 ${isUser ? 'items-end' : 'items-start'}`}>
        {!isUser && (
          <p className="text-muted-foreground px-1 text-xs font-medium">
            {assistantName?.trim() || '팀장 에이전트'}
          </p>
        )}
        {shouldShowMessageBody && (
          <div
            className={
              isUser
                ? 'rounded-2xl border [border-color:var(--chat-user-border)] px-4 py-3 text-sm leading-6 wrap-anywhere [color:var(--chat-user-foreground)] shadow-sm [background:var(--chat-user-bubble)] dark:shadow-black/10'
                : 'selectable-text text-foreground rounded-2xl py-2 text-base leading-7 wrap-anywhere'
            }
          >
            {message.content.trim() !== '' ? (
              <div className="space-y-2">
                {isUser && message.work && <WorkContextBadge work={message.work} />}
                {isUser ? (
                  <p className="selectable-text [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
                    {message.content}
                  </p>
                ) : (
                  <div className="selectable-text [overflow-wrap:anywhere] break-words">
                    <ChatMarkdown content={message.content} />
                  </div>
                )}
              </div>
            ) : (
              <div className="text-muted-foreground flex items-center gap-2">
                {message.status === 'waiting' ? (
                  <>
                    <Clock3 className="h-4 w-4 text-amber-500" />
                    <span>사용자 확인을 기다리는 중입니다.</span>
                  </>
                ) : (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
              </div>
            )}
          </div>
        )}
        {message.taskRunId && taskRunProgress && (
          <button
            type="button"
            onClick={() => onOpenTaskRun?.(message.taskRunId as string)}
            aria-label="답변 진행 단계 열기"
            className="border-border bg-card hover:bg-muted/40 w-full max-w-xl rounded-lg border px-3 py-2 text-left shadow-sm transition-colors"
          >
            <ol className="space-y-1.5">
              {taskRunProgress.items.map((item) => (
                <li key={item.id} className="flex items-start gap-2">
                  <TaskRunStatusIcon tone={item.tone} />
                  <span className="min-w-0 flex-1">
                    <span className="text-foreground line-clamp-1 block text-xs font-medium [overflow-wrap:anywhere] break-words">
                      {item.text}
                    </span>
                    <span className="text-muted-foreground line-clamp-1 block text-[11px]">
                      {item.detail}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </button>
        )}
        {message.taskRunId && taskRunChip && taskRunProgress === undefined && (
          <button
            type="button"
            onClick={() => onOpenTaskRun?.(message.taskRunId as string)}
            aria-label="답변 진행 상황 열기"
            className="text-muted-foreground hover:text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs transition-colors"
          >
            <TaskRunChipIcon tone={taskRunChip.tone} />
            <span>{taskRunChip.text}</span>
          </button>
        )}
      </div>
    </article>
  )
}

function WorkContextBadge({ work }: { work: NonNullable<ChatMessageView['work']> }) {
  const label = [work.identifier, work.title].filter(Boolean).join(' · ')
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-white/60 px-2 py-1 text-[11px] font-medium text-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-200">
      <ListTodo className="h-3 w-3 shrink-0" />
      <span className="truncate">{label || '연결된 작업'}</span>
      {work.assigneeAgentId && (
        <span className="text-muted-foreground shrink-0">· {work.assigneeAgentId}</span>
      )}
    </span>
  )
}

type AssistantTaskRunProgress = {
  items: {
    id: string
    text: string
    detail: string
    tone: TaskRunStatusTone
  }[]
}

function getAssistantTaskRunProgress(
  stepRuns: RawStepRun[],
  taskRunSummary?: TaskRunSummaryView,
): AssistantTaskRunProgress | undefined {
  const taskStatus =
    typeof taskRunSummary?.raw?.status === 'string' ? taskRunSummary.raw.status : undefined
  if (isTerminalTaskStatus(taskStatus) || stepRuns.length === 0) {
    return undefined
  }

  const visibleSteps = stepRuns
    .filter((stepRun) => !isTerminalTaskStatus(stepRun.status) || stepRun.status === 'COMPLETED')
    .slice(-3)

  if (visibleSteps.length === 0) {
    return undefined
  }

  return {
    items: visibleSteps.map((stepRun) => {
      const title = toUserFacingTaskTitle(stepRun.title ?? stepRun.goal ?? '답변 진행')
      const status = stepRun.status
      return {
        id: stepRun.step_run_id,
        text: `${title}${toCompactStepSuffix(status)}`,
        detail: toStepProgressSentence(status),
        tone: toTaskRunStatusTone(status),
      }
    }),
  }
}

function getAssistantTaskRunChip(
  activities: ActivityItemView[],
  taskRunSummary?: TaskRunSummaryView,
  messageStatus?: ChatMessageView['status'],
): { text: string; tone: TaskRunStatusTone } | undefined {
  const latestActivity = activities.at(-1)
  const taskStatus =
    typeof taskRunSummary?.raw?.status === 'string' ? taskRunSummary.raw.status : undefined
  const latestEventType = latestActivity?.raw.event_type

  if (messageStatus === 'streaming') {
    if (
      latestActivity !== undefined &&
      latestActivity.tone !== 'completed' &&
      !isAnswerCompletionEvent(latestEventType)
    ) {
      return { text: latestActivity.statusText, tone: latestActivity.tone }
    }
    return { text: '답변 진행 중', tone: 'running' }
  }

  if (messageStatus === 'completed') {
    return { text: '답변 완료', tone: 'completed' }
  }

  if (taskStatus === 'COMPLETED' || isAnswerCompletionEvent(latestEventType)) {
    return { text: '답변 완료', tone: 'completed' }
  }

  if (
    latestActivity !== undefined &&
    latestActivity.tone === 'completed' &&
    !isAnswerCompletionEvent(latestEventType)
  ) {
    return { text: '답변 진행 중', tone: 'running' }
  }

  if (latestActivity !== undefined) {
    return { text: latestActivity.statusText, tone: latestActivity.tone }
  }

  if (taskRunSummary !== undefined) {
    return { text: taskRunSummary.statusText, tone: taskRunSummary.tone }
  }

  return undefined
}

function isAnswerCompletionEvent(eventType?: string) {
  return eventType === 'task.completed' || eventType === 'session.message.completed'
}

function isTerminalTaskStatus(status?: string | null) {
  return (
    status === 'COMPLETED' ||
    status === 'FAILED' ||
    status === 'CANCELLED' ||
    status === 'CANCELED' ||
    status === 'task.completed' ||
    status === 'task.failed' ||
    status === 'task.canceled'
  )
}

function toCompactStepSuffix(status?: string | null) {
  switch (status) {
    case 'COMPLETED':
    case 'step.completed':
      return ' 완료'
    case 'RUNNING':
    case 'step.started':
      return ' 중'
    case 'WAITING':
    case 'step.waiting':
      return ' 대기 중'
    case 'FAILED':
    case 'step.failed':
      return ' 실패'
    default:
      return ''
  }
}

function TaskRunChipIcon({ tone }: { tone: TaskRunStatusTone }) {
  if (tone === 'completed') return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
  if (tone === 'failed') return <XCircle className="text-destructive h-3.5 w-3.5" />
  if (tone === 'waiting') return <Clock3 className="h-3.5 w-3.5 text-amber-500" />
  if (tone === 'running') return <Loader2 className="text-primary h-3.5 w-3.5 animate-spin" />
  return <Clock3 className="h-3.5 w-3.5" />
}
