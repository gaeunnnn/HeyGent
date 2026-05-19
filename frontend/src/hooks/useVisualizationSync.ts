import { useEffect, useRef } from 'react'
import { useAgentVisualizationStore } from '@/store/useAgentVisualizationStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import type { UIDestination } from '@/components/office/types'
import type { RawTaskRun, TaskRunAgentRef } from '@/types/taskRuns'
import type { RawTaskEventPayload } from '@/realtime/aiRealtimeTypes'

// 목적지 우선순위 — 같은 에이전트에 여러 task run이 있을 때 더 낮은 값이 우선
// meeting 전환은 handleMove 내부 책상 점유 감지로 처리하므로 여기서는 desk/calling/rest만 반환
const DEST_PRIORITY: Record<UIDestination, number> = {
  desk: 0,
  work: 0,
  calling: 1,
  meeting: 1,
  rest: 2,
}

// step.started 계열 — 에이전트가 실제로 무언가 시작했음을 나타내는 event_type
const RUNNING_EVENT_TYPES = new Set(['step.started', 'tool.started', 'search.started'])

// MD 명세: profileKey는 백엔드 profile key이며 sprite key로 추론하지 않는다.
// spriteId는 profileIdMap[agent.profileId] → visualKey 경로로만 결정한다.
// profileIdMap: 세션 에이전트 패널의 profileId → visualKey(agentXX) 매핑 — 서브에이전트 연동용
function resolveProfileKey(
  agent?: TaskRunAgentRef | null,
  profileIdMap?: Record<string, string>,
): string | undefined {
  if (!agent) return undefined
  if (agent.kind === 'main') return 'ceo'
  if (agent.profileId != null) return profileIdMap?.[agent.profileId]
  return undefined
}

// 자식 단위 종료 event_type — 태스크 전체가 끝난 건 아님 (다음 step/tool이 올 수 있음)
// useTaskRunStore의 isChildTerminalEvent와 동일 집합을 유지한다.
const STEP_TERMINAL_EVENT_TYPES = new Set([
  'step.completed',
  'step.failed',
  'step.canceled',
  'step.cancelled',
  'tool.completed',
  'search.completed',
])

const TASK_COMPLETED_EVENT_TYPES = new Set(['task.completed'])
const TASK_FAILED_EVENT_TYPES = new Set(['task.failed'])
const TASK_CANCELED_EVENT_TYPES = new Set(['task.canceled', 'task.cancelled'])

function getTimestamp(value: unknown): number {
  if (typeof value !== 'string') return 0
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? time : 0
}

function getTaskRunSortTime(taskRun: RawTaskRun, latestEvent?: RawTaskEventPayload): number {
  return Math.max(
    getTimestamp(latestEvent?.occurred_at),
    getTimestamp(taskRun.updated_at),
    getTimestamp(taskRun.completed_at),
    getTimestamp(taskRun.created_at),
  )
}

/**
 * task run 상태를 결정한다.
 * 최신 이벤트(task.event)의 status가 있으면 우선 사용 — taskRunsById보다 실시간.
 * status가 없으면 event_type으로 보조 판단하되, step 단위 종료는 무시 (태스크가 아직 진행 중일 수 있음).
 */
function resolveDestination(
  taskRun: RawTaskRun,
  latestEvent?: RawTaskEventPayload,
): UIDestination | null {
  // taskRun 자체가 terminal 이면 latestEvent 의 step.started 같은 비-terminal event 에 휘둘리지 말고
  // taskRun.status 를 기준으로 즉시 결정한다 — task 가 끝났는데 가장 마지막 step event 가
  // step.started 같은 거여서 'desk' 가 잘못 발사되어 캐릭터가 책상에 박히는 사고를 막는다.
  const taskStatus = taskRun.status?.toUpperCase()
  // 작업이 끝났으면 (성공·실패·취소 무관) 무조건 휴식. 실패해도 엘리베이터 앞 calling 자세로
  // 박혀 있는 게 아니라 소파/플로어로 보낸다.
  if (
    taskStatus === 'COMPLETED' ||
    taskStatus === 'CANCELED' ||
    taskStatus === 'CANCELLED' ||
    taskStatus === 'FAILED'
  ) {
    return 'rest'
  }

  if (latestEvent !== undefined) {
    if (TASK_COMPLETED_EVENT_TYPES.has(latestEvent.event_type)) return 'rest'
    if (TASK_FAILED_EVENT_TYPES.has(latestEvent.event_type)) return 'rest'
    if (TASK_CANCELED_EVENT_TYPES.has(latestEvent.event_type)) return 'rest'
    // step 단위 종료 이벤트는 task 전체 완료가 아님 — taskRun.status가 RUNNING이면 desk 유지
    if (STEP_TERMINAL_EVENT_TYPES.has(latestEvent.event_type)) {
      const s = taskRun.status?.toUpperCase()
      if (s === 'RUNNING' || s === 'WAITING' || s === 'BLOCKED') return 'desk'
      return null
    }
  }

  // step 단위 종료 이벤트(step.completed 등)의 status는 task 완료를 의미하지 않음
  // — step event가 아닌 경우에만 event status를 task 상태 판단에 사용
  const eventStatus =
    latestEvent != null && !STEP_TERMINAL_EVENT_TYPES.has(latestEvent.event_type)
      ? latestEvent.status
      : undefined
  const status = (eventStatus ?? taskRun.status)?.toUpperCase()

  if (!status || status === 'PENDING') return null
  if (
    status === 'FAILED' ||
    status === 'COMPLETED' ||
    status === 'CANCELED' ||
    status === 'CANCELLED'
  ) {
    return 'rest'
  }
  if (status === 'RUNNING' || status === 'WAITING' || status === 'BLOCKED') return 'desk'

  // status 필드 없을 때 event_type으로 보조 판단
  if (latestEvent && !STEP_TERMINAL_EVENT_TYPES.has(latestEvent.event_type)) {
    if (RUNNING_EVENT_TYPES.has(latestEvent.event_type)) return 'desk'
    if (latestEvent.event_type === 'step.waiting') return 'desk'
  }

  return null
}

/**
 * useTaskRunStore의 실시간 task run / task.event 데이터를 읽어 에이전트 시각화 이동을 트리거한다.
 * - Spec 4 (taskRuns.active.list): taskRunsById 초기 상태
 * - Spec 1 (task.event): eventsByTaskRunId 실시간 갱신 → 최신 이벤트 status/event_type 반영
 * - profileIdMap: 세션 에이전트 profileId → spriteId(agentXX) 매핑 — 서브에이전트 task run 연동용
 */
export function useVisualizationSync(
  handleMove: (agentId: string, dest: UIDestination) => void,
  sessionId?: string,
  profileIdMap?: Record<string, string>,
) {
  const handleMoveRef = useRef(handleMove)
  useEffect(() => {
    handleMoveRef.current = handleMove
  }, [handleMove])

  const taskRunsById = useTaskRunStore((s) => s.taskRunsById)
  const eventsByTaskRunId = useTaskRunStore((s) => s.eventsByTaskRunId)
  // sitting_desk 에 stuck 된 에이전트가 생기면 effect 가 한 번 더 돌아 rest 발사하도록 deps 에 포함.
  const stuckAtDeskKey = useAgentVisualizationStore((s) =>
    s.agentRuntimes
      .filter(
        (a) =>
          a.config.id !== 'ceo' &&
          (a.state === 'sitting_desk' ||
            (a.state === 'walking' && a.targetState === 'sitting_desk')),
      )
      .map((a) => a.config.id)
      .sort()
      .join(','),
  )
  const lastDestByAgentId = useRef<Record<string, UIDestination>>({})
  // 'rest' 전환 디바운스 timer. 에이전트 loop 가 짧은 task 를 연속 만들 때
  // desk → rest → desk → rest 가 빠르게 반복되는 걸 막는다.
  // task 완료 후 N 초간 새 task 가 안 오면 그제야 rest 발사.
  const restDebounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  useEffect(() => {
    return () => {
      for (const timer of Object.values(restDebounceTimers.current)) {
        clearTimeout(timer)
      }
      restDebounceTimers.current = {}
    }
  }, [])

  useEffect(() => {
    const pendingMoves: Record<string, { destination: UIDestination; sortTime: number }> = {}

    for (const taskRun of Object.values(taskRunsById)) {
      const profileKey = resolveProfileKey(taskRun.displayContext?.actorAgent, profileIdMap)
      if (!profileKey) continue

      // CEO 세션 필터: 다른 세션의 CEO task run 제외
      // 서브에이전트는 sub-session ID를 가지므로 세션 필터를 적용하지 않고
      // profileIdMap 귀속으로 현재 세션 범위를 보장한다
      if (
        profileKey === 'ceo' &&
        sessionId !== undefined &&
        taskRun.session_id !== undefined &&
        taskRun.session_id !== sessionId
      ) {
        continue
      }

      // 해당 task run의 최신 이벤트 (sequence 순 정렬된 배열의 마지막)
      const events = eventsByTaskRunId[taskRun.task_run_id] ?? []
      const latestEvent = events.length > 0 ? events[events.length - 1] : undefined

      const destination = resolveDestination(taskRun, latestEvent)
      if (destination === null) continue

      const sortTime = getTaskRunSortTime(taskRun, latestEvent)
      const existing = pendingMoves[profileKey]
      if (
        existing === undefined ||
        sortTime > existing.sortTime ||
        (sortTime === existing.sortTime &&
          DEST_PRIORITY[destination] < DEST_PRIORITY[existing.destination])
      ) {
        pendingMoves[profileKey] = { destination, sortTime }
      }
    }

    {
      const runtimes = useAgentVisualizationStore.getState().agentRuntimes
      for (const [profileKey, { destination }] of Object.entries(pendingMoves)) {
        // 이미 같은 명령 보냈고, 실제 state 도 그 명령과 호환되면 skip — 그렇지 않으면 강제로 재발사.
        // 예: destination='rest' 인데 lastDest='rest' 면 보통 skip 하지만 runtime.state 가 여전히
        // 'sitting_desk' 면 어딘가 막혀서 일어나지 못한 것이므로 한 번 더 시도한다.
        if (lastDestByAgentId.current[profileKey] === destination) {
          if (destination === 'rest') {
            const runtime = runtimes.find((r) => r.config.id === profileKey)
            const stuckAtDesk =
              runtime &&
              (runtime.state === 'sitting_desk' ||
                (runtime.state === 'walking' && runtime.targetState === 'sitting_desk'))
            if (!stuckAtDesk) continue
          } else {
            continue
          }
        }
        // desk/work/meeting/calling 같이 작업 가는 destination 은 즉시 발사 + rest 디바운스 취소.
        if (destination !== 'rest') {
          const existing = restDebounceTimers.current[profileKey]
          if (existing !== undefined) {
            clearTimeout(existing)
            delete restDebounceTimers.current[profileKey]
          }
          lastDestByAgentId.current[profileKey] = destination
          handleMoveRef.current(profileKey, destination)
          continue
        }
        // rest 전환은 3 초 디바운스. 같은 task 의 step 들 사이 또는 새 task 가 곧 올 가능성이
        // 있으므로 잠시 기다린다. 그 사이 desk 신호 오면 위 분기에서 timer 취소.
        const prevTimer = restDebounceTimers.current[profileKey]
        if (prevTimer !== undefined) clearTimeout(prevTimer)
        const keyAtFire = profileKey
        restDebounceTimers.current[profileKey] = setTimeout(() => {
          delete restDebounceTimers.current[keyAtFire]
          if (lastDestByAgentId.current[keyAtFire] === 'rest') {
            // 이미 rest 였으면 다시 발사 안 함 (stuck 가드는 fallback 에서 처리).
            return
          }
          lastDestByAgentId.current[keyAtFire] = 'rest'
          handleMoveRef.current(keyAtFire, 'rest')
        }, 3000)
      }
    }

    // 진행 중 task 가 없는데 책상에 박혀 있는 서브에이전트 = 휴식 보내기.
    // backend 의 active task 목록에서 빠지면 위 loop 에 들어오지 않아 마지막 명령(보통 'desk')에 박힘.
    // 가드:
    //   - profileIdMap 이 비어있으면(초기 진입 직후) 발사 금지
    //   - CEO 는 별도 정책으로 움직이므로 제외
    //   - 아직 runtime 에 spawn 안 된 에이전트는 제외 (지금 rest 보내면 handleMove 의 자동 spawn 분기가
    //     'sitting_desk' targetState 로 박아 넣어 오히려 stuck 의 원인이 됨)
    //   - 이미 sitting_sofa/floor_lean 등으로 쉬는 중이면 한 번 더 보낼 필요 없음 — sitting_desk 일 때만 발사
    if (profileIdMap !== undefined) {
      const runtimes = useAgentVisualizationStore.getState().agentRuntimes
      for (const spriteKey of Object.values(profileIdMap)) {
        if (!spriteKey || spriteKey === 'ceo') continue
        if (pendingMoves[spriteKey] !== undefined) continue
        const runtime = runtimes.find((r) => r.config.id === spriteKey)
        if (!runtime) continue
        // lastDest === 'rest' 라도 실제 state 가 sitting_desk 면 발사 — 메인 루프에서
        // 이전에 rest 를 보냈는데 어떤 이유로 위치 전환이 안 됐을 수 있음 (handleMove 의 early-return 분기 등).
        // sitting_desk 또는 sitting_desk 로 가는 walking 만 대상.
        const isAtDesk =
          runtime.state === 'sitting_desk' ||
          (runtime.state === 'walking' && runtime.targetState === 'sitting_desk')
        if (!isAtDesk) continue
        lastDestByAgentId.current[spriteKey] = 'rest'
        handleMoveRef.current(spriteKey, 'rest')
      }
    }
  }, [taskRunsById, eventsByTaskRunId, sessionId, profileIdMap, stuckAtDeskKey])
}
