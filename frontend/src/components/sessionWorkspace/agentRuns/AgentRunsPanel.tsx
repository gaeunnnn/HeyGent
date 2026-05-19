import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronRight, CircleHelp, Loader2 } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { listAgentSessionMessages, type AgentSessionMessage } from '@/apis/agentSessions'
import { getTaskRun, getTaskRunFlow } from '@/apis/taskRuns'
import type { RawTaskRun, TaskRunFlowResponse } from '@/types/taskRuns'
import { AgentSummaryGrid } from '../AgentDetailPanels'
import type { AgentRunItemData, AgentRunTimelineItemData } from './types'

export function AgentRunsPanel({
  items,
  emptyText,
}: {
  items: AgentRunItemData[]
  emptyText: string
}) {
  const [selectedRunId, setSelectedRunId] = useState('')
  const [taskDetailsByRunId, setTaskDetailsByRunId] = useState<Record<string, RawTaskRun | null>>(
    {},
  )
  const [transcriptBySessionId, setTranscriptBySessionId] = useState<
    Record<string, AgentSessionMessage[]>
  >({})
  const [flowsByRunId, setFlowsByRunId] = useState<Record<string, TaskRunFlowResponse | null>>({})
  const visibleBaseItems = items.filter(
    (item) => !isInternalPlaceholderRun(item, taskDetailsByRunId[item.id]),
  )
  const selectedBaseRun =
    visibleBaseItems.find((item) => item.id === selectedRunId) ?? visibleBaseItems[0] ?? null
  const selectedTaskDetail = selectedBaseRun ? taskDetailsByRunId[selectedBaseRun.id] : undefined
  const selectedFlow = selectedBaseRun ? flowsByRunId[selectedBaseRun.id] : undefined
  const selectedRun =
    selectedBaseRun === null
      ? null
      : buildVisibleRunItem(selectedBaseRun, selectedTaskDetail, selectedFlow)
  const selectedTranscriptSessionId = selectedRun
    ? resolveRunTranscriptSessionId(selectedRun, selectedTaskDetail, selectedFlow)
    : undefined
  const selectedTranscript =
    selectedTranscriptSessionId === undefined
      ? undefined
      : transcriptBySessionId[selectedTranscriptSessionId]
  const selectedTaskLoading =
    selectedRun !== null && isTaskRunId(selectedRun.id) && selectedTaskDetail === undefined
  const selectedTranscriptLoading =
    selectedTranscriptSessionId !== undefined && selectedTranscript === undefined

  useEffect(() => {
    const missingRunIds = items
      .filter(
        (item) =>
          isTaskRunId(item.id) &&
          taskDetailsByRunId[item.id] === undefined &&
          !isInternalPlaceholderRun(item, undefined),
      )
      .map((item) => item.id)
    if (missingRunIds.length === 0) return
    let cancelled = false
    missingRunIds.forEach((runId) => {
      getTaskRun(runId)
        .then((taskRun) => {
          if (cancelled) return
          setTaskDetailsByRunId((current) => ({ ...current, [runId]: taskRun }))
        })
        .catch(() => {
          if (cancelled) return
          setTaskDetailsByRunId((current) => ({ ...current, [runId]: null }))
        })
    })
    return () => {
      cancelled = true
    }
  }, [items, taskDetailsByRunId])

  useEffect(() => {
    const missingRunIds = items
      .filter(
        (item) =>
          isTaskRunId(item.id) &&
          flowsByRunId[item.id] === undefined &&
          !isInternalPlaceholderRun(item, undefined),
      )
      .map((item) => item.id)
    if (missingRunIds.length === 0) return
    let cancelled = false
    missingRunIds.forEach((runId) => {
      getTaskRunFlow(runId)
        .then((flow) => {
          if (cancelled) return
          setFlowsByRunId((current) => ({ ...current, [runId]: flow }))
        })
        .catch(() => {
          if (cancelled) return
          setFlowsByRunId((current) => ({ ...current, [runId]: null }))
        })
    })
    return () => {
      cancelled = true
    }
  }, [items, flowsByRunId])

  useEffect(() => {
    if (
      selectedTranscriptSessionId === undefined ||
      transcriptBySessionId[selectedTranscriptSessionId] !== undefined
    ) {
      return
    }
    let cancelled = false
    listAgentSessionMessages(selectedTranscriptSessionId)
      .then((messages) => {
        if (cancelled) return
        setTranscriptBySessionId((current) => ({
          ...current,
          [selectedTranscriptSessionId]: messages,
        }))
      })
      .catch(() => {
        if (cancelled) return
        setTranscriptBySessionId((current) => ({
          ...current,
          [selectedTranscriptSessionId]: [],
        }))
      })
    return () => {
      cancelled = true
    }
  }, [selectedTranscriptSessionId, transcriptBySessionId])

  const visibleItems = visibleBaseItems.map((item) => ({
    ...buildVisibleRunItem(item, taskDetailsByRunId[item.id], flowsByRunId[item.id]),
  }))

  return (
    <div className="space-y-4 pt-2">
      {visibleItems.length === 0 ? (
        <p className="text-muted-foreground text-sm">{emptyText}</p>
      ) : (
        <>
          <div className="flex justify-end">
            <AgentRunStatusHelp />
          </div>
          <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
            <div className="border-border overflow-hidden rounded-lg border">
              {visibleItems.map((run, index) => (
                <AgentRunListItem
                  key={run.id}
                  run={run}
                  selected={
                    (selectedRun?.id ?? visibleItems[0]?.id) === run.id ||
                    (selectedRun === null && index === 0)
                  }
                  onSelect={() => setSelectedRunId(run.id)}
                />
              ))}
            </div>
            <AgentRunDetailCard
              loadingTask={selectedTaskLoading}
              loadingTranscript={selectedTranscriptLoading}
              run={selectedRun}
              taskFlow={selectedFlow ?? undefined}
              taskDetail={selectedTaskDetail ?? undefined}
              transcript={selectedTranscript}
              transcriptSessionId={selectedTranscriptSessionId}
            />
          </div>
        </>
      )}
    </div>
  )
}

function buildVisibleRunItem(
  run: AgentRunItemData,
  taskDetail?: RawTaskRun | null,
  taskFlow?: TaskRunFlowResponse | null,
): AgentRunItemData {
  const inputPayload = toRecord(taskDetail?.input_payload)
  const resultPayload = toRecord(taskDetail?.result_payload)
  const model =
    getStringValue(inputPayload, 'model', 'provider_model', 'providerModel') ??
    getStringValue(resultPayload, 'model') ??
    getStringValue(toRecord(resultPayload?.metadata), 'model') ??
    run.model
  const provider =
    getStringValue(inputPayload, 'provider_name', 'providerName', 'provider') ??
    getStringValue(resultPayload, 'provider_name', 'providerName', 'provider') ??
    run.adapter
  return {
    ...run,
    status: getEffectiveRunStatus(run, taskDetail, taskFlow),
    adapter: getRunAdapterLabel(provider, model) ?? run.adapter,
    model,
    delegationInput:
      run.delegationInput ?? buildDelegationInput(inputPayload, taskDetail?.displayContext),
  }
}

function AgentRunListItem({
  onSelect,
  run,
  selected,
}: {
  onSelect: () => void
  run: AgentRunItemData
  selected: boolean
}) {
  const title = getRunListTitle(run)
  const source = run.source && run.source !== 'chat' ? run.source : undefined
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`hover:bg-accent/20 border-border flex w-full flex-col gap-2 border-b px-3 py-3 text-left text-sm last:border-b-0 ${
        selected ? 'bg-accent/40' : ''
      }`}
    >
      <span className="min-w-0 truncate text-xs font-medium">{title}</span>
      <span className="text-muted-foreground grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1.5 text-[11px]">
        <AgentStatusPill status={run.status} />
        <span className="flex min-w-0 items-center gap-1.5 overflow-hidden">
          <span className="shrink-0 font-mono">{shortRunId(run.id)}</span>
          {source ? (
            <span className="bg-muted max-w-24 min-w-0 truncate rounded px-1.5 py-0.5 text-[10px]">
              {source}
            </span>
          ) : null}
        </span>
        <span className="whitespace-nowrap">{run.createdAt ?? '방금 전'}</span>
      </span>
    </button>
  )
}

function AgentRunDetailCard({
  loadingTask,
  loadingTranscript,
  run,
  taskFlow,
  taskDetail,
  transcript,
  transcriptSessionId,
}: {
  loadingTask: boolean
  loadingTranscript: boolean
  run: AgentRunItemData | null
  taskFlow?: TaskRunFlowResponse
  taskDetail?: RawTaskRun
  transcript?: AgentSessionMessage[]
  transcriptSessionId?: string
}) {
  if (!run) return null
  const detail = buildRunDetailView(run, taskDetail, taskFlow, transcript)
  const effectiveStatus = getEffectiveRunStatus(run, taskDetail, taskFlow)
  return (
    <div className="space-y-4">
      <div className="border-border overflow-hidden rounded-lg border">
        <div className="space-y-3 p-4">
          <div className="flex items-center gap-2">
            <AgentStatusPill status={effectiveStatus} />
            <span className="text-muted-foreground font-mono text-xs">{run.id}</span>
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
            {run.adapter ? (
              <span className="bg-muted rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                {run.adapter}
              </span>
            ) : null}
            {run.model ? <span>{run.model}</span> : null}
          </div>
          <AgentSummaryGrid
            items={[
              { label: '시작', value: run.createdAt ?? '-' },
              { label: '토큰', value: run.tokens ?? '-' },
              { label: '비용', value: run.cost ?? '-' },
              { label: '출처', value: run.source ?? '-' },
            ]}
          />
          {transcriptSessionId ? (
            <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
              <span>대화 기록</span>
              <span className="bg-muted rounded px-1.5 py-0.5 font-mono text-[10px]">
                {shortRunId(transcriptSessionId)}
              </span>
              {detail.parentTranscriptSessionId ? (
                <>
                  <span>부모</span>
                  <span className="bg-muted rounded px-1.5 py-0.5 font-mono text-[10px]">
                    {shortRunId(detail.parentTranscriptSessionId)}
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <AgentRunConversationFlow detail={detail} />
      <AgentRunTranscriptSection
        defaultOpen={false}
        loading={loadingTask || loadingTranscript}
        messages={detail.messages}
      />
      <AgentRunToolSection
        defaultOpen={false}
        messages={detail.messages}
        timeline={detail.timeline}
      />
    </div>
  )
}

function AgentRunConversationFlow({
  detail,
}: {
  detail: {
    delegateRoute?: string
    request?: string
    delegationInput?: string
    returnRoute?: string
    result?: string
  }
}) {
  return (
    <div className="border-border rounded-lg border p-4">
      <div className="mb-3">
        <h4 className="text-sm font-medium">대화 흐름</h4>
        <p className="text-muted-foreground mt-1 text-xs">
          어떤 요청을 받았고, 누구에게 맡겼고, 어떤 답변을 돌려줬는지 봅니다.
        </p>
      </div>
      <div className="grid gap-3">
        <AgentRunFlowBlock
          emptyText="저장된 사용자 요청을 찾지 못했습니다."
          eyebrow="사용자 -> 팀장"
          title="받은 요청"
          value={detail.request}
        />
        <AgentRunFlowBlock
          emptyText="이 실행에 연결된 맡긴 내용이 없습니다."
          eyebrow={detail.delegateRoute}
          title="맡긴 내용"
          value={detail.delegationInput}
        />
        <AgentRunFlowBlock
          emphasis
          emptyText="아직 반환된 답변이 없습니다."
          eyebrow={detail.returnRoute}
          title="돌려준 답변"
          value={detail.result}
        />
      </div>
    </div>
  )
}

function AgentRunFlowBlock({
  emphasis,
  eyebrow,
  emptyText,
  title,
  value,
}: {
  emphasis?: boolean
  eyebrow?: string
  emptyText: string
  title: string
  value?: string
}) {
  return (
    <div
      className={`rounded-md border p-3 ${
        emphasis ? 'border-emerald-200 bg-emerald-50/50' : 'border-border bg-muted/20'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
            emphasis ? 'bg-emerald-100 text-emerald-700' : 'bg-background text-muted-foreground'
          }`}
        >
          {title}
        </span>
        {eyebrow ? <span className="text-muted-foreground text-xs">{eyebrow}</span> : null}
      </div>
      <div className="mt-2 max-h-56 overflow-y-auto pr-1">
        <p className="text-sm leading-6 whitespace-pre-wrap">{value || emptyText}</p>
      </div>
    </div>
  )
}

function AgentRunTranscriptSection({
  defaultOpen,
  loading,
  messages,
}: {
  defaultOpen: boolean
  loading: boolean
  messages?: AgentSessionMessage[]
}) {
  const count = messages?.length ?? 0
  return (
    <AgentRunCollapsibleSection
      defaultOpen={defaultOpen}
      meta={count > 0 ? `${count}개 메시지` : undefined}
      title="저장된 원문 대화"
    >
      <div className="flex items-center justify-end gap-3">
        {loading ? <Loader2 className="text-muted-foreground h-3.5 w-3.5 animate-spin" /> : null}
      </div>
      {messages === undefined && !loading ? (
        <p className="text-muted-foreground mt-2 text-sm">연결된 대화 기록이 없습니다.</p>
      ) : null}
      {messages !== undefined && messages.length === 0 && !loading ? (
        <p className="text-muted-foreground mt-2 text-sm">저장된 메시지가 없습니다.</p>
      ) : null}
      {messages !== undefined && messages.length > 0 ? (
        <div className="mt-3 max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {messages.map((message) => (
            <AgentRunTranscriptMessage key={message.id} message={message} />
          ))}
        </div>
      ) : null}
    </AgentRunCollapsibleSection>
  )
}

function AgentRunTranscriptMessage({ message }: { message: AgentSessionMessage }) {
  const role = normalizeMessageRole(message.role)
  const toolCallCount = Array.isArray(message.toolCalls) ? message.toolCalls.length : 0
  return (
    <div className="bg-muted/30 rounded-md p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-background rounded px-1.5 py-0.5 text-[10px] font-medium uppercase">
          {role}
        </span>
        {message.toolName ? (
          <span className="text-muted-foreground font-mono text-[10px]">{message.toolName}</span>
        ) : null}
        {toolCallCount > 0 ? (
          <span className="text-muted-foreground text-[10px]">tool call {toolCallCount}</span>
        ) : null}
      </div>
      {message.content ? (
        <p className="mt-2 text-sm leading-6 whitespace-pre-wrap">
          {compactLongText(message.content)}
        </p>
      ) : (
        <p className="text-muted-foreground mt-2 text-sm">
          본문 없이 도구 호출 메타데이터만 있습니다.
        </p>
      )}
    </div>
  )
}

function AgentRunToolSection({
  defaultOpen,
  messages,
  timeline,
}: {
  defaultOpen: boolean
  messages?: AgentSessionMessage[]
  timeline: AgentRunTimelineItemData[]
}) {
  const toolItems = useMemo(() => buildToolTimeline(messages, timeline), [messages, timeline])
  return (
    <AgentRunCollapsibleSection
      defaultOpen={defaultOpen}
      meta={toolItems.length > 0 ? `${toolItems.length}개 기록` : undefined}
      title="실행 과정"
    >
      {toolItems.length === 0 ? (
        <p className="text-muted-foreground mt-2 text-sm">표시할 도구 실행 기록이 없습니다.</p>
      ) : (
        <div className="mt-3 space-y-2">
          {toolItems.map((item) => (
            <div key={item.id} className="bg-muted/30 rounded-md p-3">
              <div className="flex flex-wrap items-center gap-2">
                <AgentStatusDot status={item.status ?? 'completed'} />
                <span className="text-sm font-medium">{item.label}</span>
                {item.time ? (
                  <span className="text-muted-foreground text-xs">{item.time}</span>
                ) : null}
              </div>
              {item.message ? (
                <p className="text-muted-foreground mt-1 text-xs leading-5 whitespace-pre-wrap">
                  {item.message}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </AgentRunCollapsibleSection>
  )
}

function AgentRunCollapsibleSection({
  children,
  defaultOpen,
  meta,
  title,
}: {
  children: ReactNode
  defaultOpen: boolean
  meta?: string
  title: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-border rounded-lg border">
      <button
        type="button"
        className="hover:bg-muted/40 flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <ChevronRight
            className={`text-muted-foreground h-4 w-4 shrink-0 transition-transform ${
              open ? 'rotate-90' : ''
            }`}
          />
          <span className="text-sm font-medium">{title}</span>
        </span>
        {meta ? <span className="text-muted-foreground shrink-0 text-xs">{meta}</span> : null}
      </button>
      {open ? <div className="border-border border-t p-4">{children}</div> : null}
    </div>
  )
}

function AgentRunStatusHelp() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-muted-foreground hover:bg-muted inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs transition-colors"
        >
          <CircleHelp className="h-3.5 w-3.5" />
          <span>상태 기준</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 text-sm">
        <div className="space-y-3">
          <div>
            <div className="font-medium">실행 기록 상태</div>
            <p className="text-muted-foreground mt-1 text-xs leading-5">
              팀장과 서브에이전트는 같은 상태 체계를 씁니다. 색상은 역할 차이가 아니라 현재 실행
              상태를 뜻합니다.
            </p>
          </div>
          <div className="grid gap-2">
            {RUN_STATUS_HELP_ITEMS.map((item) => (
              <div key={item.status} className="flex items-start gap-2">
                <AgentStatusDot status={item.status} />
                <div>
                  <div className="text-xs font-medium">{item.label}</div>
                  <div className="text-muted-foreground text-xs">{item.description}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

const RUN_STATUS_HELP_ITEMS = [
  { status: 'running', label: '실행 중', description: '모델 응답 또는 도구 실행이 진행 중입니다.' },
  { status: 'waiting', label: '대기 중', description: '사용자 승인이나 외부 응답을 기다립니다.' },
  { status: 'succeeded', label: '완료', description: '요청 처리가 정상 종료되었습니다.' },
  { status: 'failed', label: '오류', description: '실행 실패, 차단, 취소 상태입니다.' },
  {
    status: 'pending',
    label: '준비 중',
    description: '실행 시작 전이거나 상세 상태가 아직 없습니다.',
  },
] as const

function buildRunDetailView(
  run: AgentRunItemData,
  taskDetail?: RawTaskRun,
  taskFlow?: TaskRunFlowResponse,
  transcript?: AgentSessionMessage[],
) {
  const inputPayload = toRecord(taskDetail?.input_payload)
  const resultPayload = toRecord(taskDetail?.result_payload)
  const assigneeName = taskDetail?.displayContext?.assigneeAgent?.displayName ?? run.agentName
  const actorName = taskDetail?.displayContext?.actorAgent?.displayName ?? assigneeName
  const assigneeIsMain = isTeamLeadAgentName(
    assigneeName,
    taskDetail?.displayContext?.assigneeAgent?.kind,
  )
  const actorIsMain = isTeamLeadAgentName(actorName, taskDetail?.displayContext?.actorAgent?.kind)
  const transcriptUserRequest = getFirstUserMessageContent(transcript)
  const lastAssistantAnswer = getLastAssistantMessageContent(transcript)
  const parentTranscriptSessionId =
    run.parentTranscriptSessionId ??
    getStringValue(inputPayload, 'parentTranscriptSessionId', 'parent_transcript_session_id')
  const storedRequest =
    run.request ??
    getStringValue(inputPayload, 'prompt', 'content', 'rawUserInput', 'raw_user_input') ??
    getStringValue(taskDetail, 'input_summary', 'title', 'goal') ??
    run.summary
  const request = isInternalContinuationInstruction(storedRequest)
    ? (transcriptUserRequest ?? storedRequest)
    : (storedRequest ?? transcriptUserRequest)
  const delegationInput =
    run.delegationInput ??
    buildDelegationInput(inputPayload, taskDetail?.displayContext) ??
    getStringValue(inputPayload, 'executionInstruction', 'execution_instruction')
  const result =
    lastAssistantAnswer ??
    getStringValue(resultPayload, 'answer', 'content', 'finalAnswer', 'final_answer') ??
    run.result ??
    run.handoff ??
    run.summary
  return {
    delegateRoute: assigneeName && !assigneeIsMain ? `팀장 -> ${assigneeName}` : '팀장이 직접 처리',
    returnRoute: actorName && !actorIsMain ? `${actorName} -> 팀장/사용자` : '팀장 -> 사용자',
    parentTranscriptSessionId,
    request,
    delegationInput,
    result,
    messages: transcript,
    timeline: mergeRunTimeline(run.timeline ?? [], taskFlow),
  }
}

function isTeamLeadAgentName(name?: string | null, kind?: string | null) {
  if (kind === 'main') return true
  return name === 'CEO' || name === '팀장' || name === '팀장 에이전트'
}

function getEffectiveRunStatus(
  run: AgentRunItemData,
  taskDetail?: RawTaskRun | null,
  taskFlow?: TaskRunFlowResponse | null,
) {
  return getStringValue(taskDetail, 'status') ?? getStringValue(taskFlow, 'status') ?? run.status
}

function getFirstUserMessageContent(messages?: AgentSessionMessage[]) {
  return messages
    ?.find((message) => message.role === 'user' && typeof message.content === 'string')
    ?.content?.trim()
}

function getLastAssistantMessageContent(messages?: AgentSessionMessage[]) {
  return [...(messages ?? [])]
    .reverse()
    .find((message) => message.role === 'assistant' && typeof message.content === 'string')
    ?.content?.trim()
}

function isInternalContinuationInstruction(value?: string | null) {
  const text = typeof value === 'string' ? value.trim() : ''
  return (
    text === '이어진 실행' ||
    text === '복구 실행' ||
    text.startsWith('선행 작업이 완료되었습니다. 이 작업을 이어서 진행해') ||
    text.startsWith('이전 실행이 중단되었습니다. 진행 가능한 지점부터')
  )
}

function isInternalPlaceholderRun(
  run: AgentRunItemData,
  taskDetail: RawTaskRun | null | undefined,
) {
  if (taskDetail !== undefined && taskDetail !== null) return false
  const hasInternalSignal = [run.summary, run.request, run.result].some((value) =>
    isInternalContinuationInstruction(value),
  )
  const hasReadableContent = [run.summary, run.request, run.result].some((value) =>
    hasReadableRunText(value),
  )
  if (!hasInternalSignal || hasReadableContent) return false
  return run.tokens === '-' && run.cost === '-'
}

function hasReadableRunText(value?: string | null) {
  const text = typeof value === 'string' ? value.trim() : ''
  return text.length > 0 && !isInternalContinuationInstruction(text)
}

function resolveRunTranscriptSessionId(
  run: AgentRunItemData,
  taskDetail?: RawTaskRun | null,
  taskFlow?: TaskRunFlowResponse | null,
) {
  if (run.transcriptSessionId) return run.transcriptSessionId
  const inputPayload = toRecord(taskDetail?.input_payload)
  return (
    getStringValue(
      inputPayload,
      'transcript_session_id',
      'transcriptSessionId',
      'agentSessionId',
      'agent_session_id',
    ) ?? resolveFlowTranscriptSessionId(taskFlow)
  )
}

function resolveFlowTranscriptSessionId(taskFlow?: TaskRunFlowResponse | null) {
  const workerNode = taskFlow?.nodes?.find((node) => {
    const workerSessionId = getStringValue(node, 'worker_session_id', 'workerSessionId')
    return workerSessionId !== undefined
  })
  const edge = taskFlow?.edges?.find((item) => {
    const agentSessionId = getStringValue(item, 'to_agent_session_id', 'toAgentSessionId')
    return agentSessionId !== undefined
  })
  return (
    getStringValue(workerNode, 'worker_session_id', 'workerSessionId') ??
    getStringValue(edge, 'to_agent_session_id', 'toAgentSessionId')
  )
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

function buildToolTimeline(
  messages: AgentSessionMessage[] | undefined,
  timeline: AgentRunTimelineItemData[],
) {
  const items = [...timeline]
  messages?.forEach((message) => {
    if (message.toolName) {
      items.push({
        id: `tool-${message.id}`,
        label: message.toolName,
        message: message.content ?? undefined,
        status: 'completed',
      })
    }
    message.toolCalls?.forEach((toolCall, index) => {
      const name =
        getStringValue(toolCall, 'name') ?? getStringValue(toRecord(toolCall.function), 'name')
      if (!name) return
      items.push({
        id: `tool-call-${message.id}-${index}`,
        label: name,
        message:
          getStringValue(toolCall, 'arguments') ??
          getStringValue(toRecord(toolCall.function), 'arguments'),
        status: 'running',
      })
    })
  })
  return items
}

function mergeRunTimeline(
  timeline: AgentRunTimelineItemData[],
  taskFlow?: TaskRunFlowResponse,
): AgentRunTimelineItemData[] {
  const items = [...timeline]
  taskFlow?.nodes?.forEach((node, nodeIndex) => {
    node.activity?.forEach((activity, activityIndex) => {
      const label =
        getStringValue(activity, 'event_type', 'eventType') ??
        getStringValue(node, 'title') ??
        `flow-${nodeIndex + 1}`
      items.push({
        id: `flow-${nodeIndex}-${activityIndex}`,
        label,
        message: getStringValue(activity, 'summary_message', 'summaryMessage'),
        status: getStringValue(activity, 'status') ?? getStringValue(node, 'status'),
        time: getStringValue(activity, 'occurred_at', 'occurredAt'),
      })
    })
    const workerSessionId = getStringValue(node, 'worker_session_id', 'workerSessionId')
    if (workerSessionId) {
      items.push({
        id: `worker-${nodeIndex}`,
        label: '위임 대화 연결',
        message: workerSessionId,
        status: getStringValue(node, 'status'),
      })
    }
  })
  return dedupeTimelineItems(items)
}

function dedupeTimelineItems(items: AgentRunTimelineItemData[]) {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = `${item.label}:${item.message ?? ''}:${item.time ?? ''}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function isTaskRunId(value: string) {
  return value.startsWith('task_')
}

function getRunListTitle(run: AgentRunItemData) {
  const request = normalizeRunListTitle(run.request)
  const result = normalizeRunListTitle(run.result)
  const summary = normalizeRunListTitle(run.summary)
  const delegatedAgent = getDelegatedAgentName(run.delegationInput)
  return (
    request ??
    (delegatedAgent ? `${delegatedAgent} 위임 실행` : undefined) ??
    result ??
    summary ??
    shortRunId(run.id)
  )
}

function normalizeRunListTitle(value?: string | null) {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''
  if (!text) return undefined
  if (text.startsWith('선행 작업이 완료되었습니다. 이 작업을 이어서 진행해')) {
    return undefined
  }
  if (text.startsWith('이전 실행이 중단되었습니다. 진행 가능한 지점부터')) {
    return undefined
  }
  return text.length > 90 ? `${text.slice(0, 87)}...` : text
}

function getDelegatedAgentName(value?: string | null) {
  const match = value?.match(/^담당 에이전트:\s*(.+)$/m)
  return match?.[1]?.trim()
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

function compactLongText(value: string) {
  const text = value.trim()
  return text.length > 1200 ? `${text.slice(0, 1200)}...` : text
}

function normalizeMessageRole(role: string) {
  if (role === 'assistant') return 'assistant'
  if (role === 'user') return 'user'
  if (role === 'tool') return 'tool'
  if (role === 'system') return 'system'
  return role || 'message'
}

function AgentStatusDot({ status }: { status: string }) {
  const tone = getRunStatusView(status).dotClassName
  return <span className={`h-2 w-2 rounded-full ${tone}`} />
}

function AgentStatusPill({ status }: { status: string }) {
  const statusView = getRunStatusView(status)
  return (
    <span
      className={`inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide whitespace-nowrap ${statusView.pillClassName}`}
    >
      {statusView.label}
    </span>
  )
}

function getRunStatusView(status: string) {
  const normalized = normalizeRunStatusValue(status)
  switch (normalized) {
    case 'failed':
      return {
        label: '오류',
        dotClassName: 'bg-red-500',
        pillClassName: 'border-red-200 bg-red-50 text-red-700',
      }
    case 'running':
      return {
        label: '실행 중',
        dotClassName: 'bg-blue-500',
        pillClassName: 'border-blue-200 bg-blue-50 text-blue-700',
      }
    case 'waiting':
      return {
        label: '대기 중',
        dotClassName: 'bg-amber-500',
        pillClassName: 'border-amber-200 bg-amber-50 text-amber-700',
      }
    case 'succeeded':
      return {
        label: '완료',
        dotClassName: 'bg-emerald-500',
        pillClassName: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      }
    default:
      return {
        label: '준비 중',
        dotClassName: 'bg-muted-foreground/50',
        pillClassName: 'border-border bg-muted text-muted-foreground',
      }
  }
}

function normalizeRunStatusValue(status: string) {
  switch (status) {
    case 'failed':
    case 'FAILED':
    case 'blocked':
    case 'BLOCKED':
    case 'cancelled':
    case 'CANCELLED':
    case 'canceled':
    case 'CANCELED':
      return 'failed'
    case 'running':
    case 'RUNNING':
      return 'running'
    case 'waiting':
    case 'WAITING':
      return 'waiting'
    case 'succeeded':
    case 'completed':
    case 'COMPLETED':
      return 'succeeded'
    case 'pending':
    case 'PENDING':
      return 'pending'
    default:
      return 'pending'
  }
}

function shortRunId(id: string) {
  return id.length > 8 ? id.slice(0, 8) : id
}
