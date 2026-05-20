import { useEffect, useRef } from 'react'
import { deriveSpriteId } from '@/apis/agents'
import type { AgentActivityStatus, TaskStatus, VisualizationTask } from '@/components/office/types'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { useAgentVisualizationStore } from '@/store/useAgentVisualizationStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import type { AgentPanelItem } from '@/store/useSessionStore'
import { pickCurrentVisualizationTask } from '@/utils/agentCurrentTask'
import type { RawStepRun, RawTaskRun } from '@/types/taskRuns'

const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELED', 'CANCELLED'])

function toActivityStatus(status?: string | null): AgentActivityStatus {
  const s = status?.toUpperCase()
  if (!s || s === 'PENDING') return 'inactive'
  if (TERMINAL_STATUSES.has(s)) return 'resting'
  return 'working'
}

function toTaskStatus(status?: string | null): TaskStatus {
  const s = status?.toUpperCase()
  if (s === 'COMPLETED' || s === 'CANCELED' || s === 'CANCELLED') return 'completed'
  if (s === 'FAILED') return 'failed'
  if (s === 'RUNNING' || s === 'WAITING' || s === 'BLOCKED') return 'in_progress'
  return 'pending'
}

function getTimestamp(value?: string | null): number {
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? time : 0
}

function getTaskRunSortTime(taskRun: RawTaskRun): number {
  return getTimestamp(taskRun.updated_at ?? taskRun.completed_at ?? taskRun.created_at)
}

function getStepRunUpdatedAt(stepRun: RawStepRun): string | undefined {
  return typeof stepRun.updated_at === 'string' ? stepRun.updated_at : undefined
}

// 백엔드는 completed_at 대신 ended_at을 사용한다.
function getStepRunEndedAt(stepRun: RawStepRun): string | undefined {
  const raw = stepRun as Record<string, unknown>
  if (typeof raw.ended_at === 'string') return raw.ended_at
  if (typeof raw.endedAt === 'string') return raw.endedAt
  return undefined
}

// profileIdMap(profileId → spriteId)을 사용해 actorAgent를 spriteId로 해석한다.
// useVisualizationSync의 resolveProfileKey와 동일한 우선순위로 처리한다.
function resolveTaskRunSpriteId(
  taskRun: RawTaskRun,
  profileIdMap?: Record<string, string>,
): string | null {
  const actorAgent = taskRun.displayContext?.actorAgent
  if (!actorAgent) return null
  if (actorAgent.kind === 'main') return 'ceo'
  if (actorAgent.profileId != null) return profileIdMap?.[actorAgent.profileId] ?? null
  return null
}

function resolveSessionTaskRunSpriteId(
  taskRun: RawTaskRun,
  sessionId?: string,
  profileIdMap?: Record<string, string>,
): string | null {
  return (
    resolveTaskRunSpriteId(taskRun, profileIdMap) ??
    (sessionId !== undefined && taskRun.session_id === sessionId ? 'ceo' : null)
  )
}

function pickTaskHistory(taskRun: RawTaskRun, stepRuns: RawStepRun[]): VisualizationTask[] {
  const stepHistory = stepRuns
    .filter((sr) => TERMINAL_STATUSES.has(sr.status?.toUpperCase() ?? ''))
    .sort(
      (a, b) =>
        getTimestamp(b.completed_at ?? getStepRunEndedAt(b) ?? getStepRunUpdatedAt(b)) -
        getTimestamp(a.completed_at ?? getStepRunEndedAt(a) ?? getStepRunUpdatedAt(a)),
    )
    .map((sr) => ({
      taskId: sr.step_run_id,
      title: sr.title ?? '완료된 작업',
      description: '',
      status: toTaskStatus(sr.status),
      completedAt: sr.completed_at ?? getStepRunEndedAt(sr) ?? undefined,
    }))

  if (stepHistory.length > 0) return stepHistory.slice(0, 5)

  if (!TERMINAL_STATUSES.has(taskRun.status?.toUpperCase() ?? '')) {
    return []
  }

  const rawTaskRun = taskRun as Record<string, unknown>
  const taskEndedAt =
    typeof rawTaskRun.ended_at === 'string'
      ? rawTaskRun.ended_at
      : typeof rawTaskRun.endedAt === 'string'
        ? rawTaskRun.endedAt
        : undefined

  return [
    {
      taskId: taskRun.task_run_id,
      title: taskRun.title ?? '작업',
      description: '',
      status: toTaskStatus(taskRun.status),
      completedAt: taskRun.completed_at ?? taskEndedAt ?? taskRun.updated_at ?? undefined,
    },
  ]
}

type CachedSubAgentProfile = {
  name: string
  role: string
  skills: string[]
  profileImage?: string
}

export function useAgentInfoSync(
  sessionId?: string,
  profileIdMap?: Record<string, string>,
  agentPanels?: AgentPanelItem[],
) {
  const taskRunsById = useTaskRunStore((s) => s.taskRunsById)
  const stepRunsById = useTaskRunStore((s) => s.stepRunsById)
  const fetchSessionTaskRuns = useTaskRunStore((s) => s.fetchSessionTaskRuns)
  const fetchSnapshot = useTaskRunStore((s) => s.fetchSnapshot)
  const agentInfoMap = useAgentVisualizationStore((s) => s.agentInfoMap)
  const updateAgentInfo = useAgentVisualizationStore((s) => s.updateAgentInfo)
  const selectedAgentId = useAgentVisualizationStore((s) => s.selectedAgentId)
  const fetchedTaskRunIds = useRef<Set<string>>(new Set())
  const fetchedSessionIds = useRef<Set<string>>(new Set())
  // profileId → profile data 캐시 — profileIdMap이 늦게 도착해도 spriteId 매핑에 재사용한다.
  const cachedProfilesRef = useRef<Map<string, CachedSubAgentProfile>>(new Map())
  // async 콜백에서 항상 최신 profileIdMap을 읽기 위한 ref
  const profileIdMapRef = useRef(profileIdMap)
  useEffect(() => {
    profileIdMapRef.current = profileIdMap
  }, [profileIdMap])

  useEffect(() => {
    const sessionIds = new Set<string>()
    if (sessionId !== undefined && sessionId !== '') {
      sessionIds.add(sessionId)
    }

    for (const taskRun of Object.values(taskRunsById)) {
      if (typeof taskRun.session_id === 'string' && taskRun.session_id) {
        sessionIds.add(taskRun.session_id)
      }
    }

    for (const currentSessionId of sessionIds) {
      if (fetchedSessionIds.current.has(currentSessionId)) continue
      fetchedSessionIds.current.add(currentSessionId)

      void useAgentCacheStore
        .getState()
        .fetchSessionAgents(currentSessionId)
        .then((profiles) => {
          for (const profile of profiles) {
            const profileData: CachedSubAgentProfile = {
              name: profile.name,
              role: profile.role,
              skills: profile.skills,
              ...(profile.profileImage ? { profileImage: profile.profileImage } : {}),
            }
            // profileId 기준으로 캐시 — profileIdMap이 나중에 도착해도 재매핑 가능
            cachedProfilesRef.current.set(profile.profileId, profileData)
            // visualKey → profileIdMap → deriveSpriteId 순서로 spriteId를 결정한다.
            const spriteId =
              profile.visualKey ??
              profileIdMapRef.current?.[profile.profileId] ??
              deriveSpriteId(profile.profileImage)
            if (spriteId) updateAgentInfo(spriteId, profileData)
          }
        })
        .catch(() => {})

      void useAgentCacheStore
        .getState()
        .fetchSessionMainAgent(currentSessionId)
        .then((profile) => {
          const profileData = {
            name: '팀장',
            role:
              profile.role && profile.role !== 'ceo' && profile.role !== 'main'
                ? profile.role
                : '팀장 에이전트',
            skills: profile.skills,
            ...(profile.profileImage ? { profileImage: profile.profileImage } : {}),
          }
          if (profile.profileKey) updateAgentInfo(profile.profileKey, profileData)
          updateAgentInfo('ceo', profileData)
        })
        .catch(() => {})

      void fetchSessionTaskRuns(currentSessionId).catch(() => {})
    }
  }, [fetchSessionTaskRuns, sessionId, taskRunsById, updateAgentInfo])

  // profileIdMap이 늦게 채워지거나 agentPanels(이름·역할 등)가 바뀌면 agentInfoMap을 갱신한다.
  // agentPanels의 최신 값을 캐시 데이터보다 우선 적용해 사이드바 수정이 즉시 반영되도록 한다.
  // 신규 추가 에이전트(API 캐시 미적재)는 agentPanels 데이터로 즉시 반영한다.
  useEffect(() => {
    if (!profileIdMap) return
    for (const [profileId, spriteId] of Object.entries(profileIdMap)) {
      const cachedData = cachedProfilesRef.current.get(profileId)
      const panel = agentPanels?.find((p) => p.agent.profileId === profileId)
      if (!cachedData && !panel) continue
      const baseData: CachedSubAgentProfile = cachedData ?? {
        name: panel!.agent.name,
        role: panel!.agent.role ?? '',
        skills: panel!.agent.skills ?? [],
        ...(panel!.agent.profileImage ? { profileImage: panel!.agent.profileImage } : {}),
      }
      const profileData: CachedSubAgentProfile = panel
        ? {
            ...baseData,
            name: panel.agent.name,
            role: panel.agent.role ?? baseData.role,
            ...(panel.agent.profileImage !== undefined
              ? { profileImage: panel.agent.profileImage ?? undefined }
              : {}),
          }
        : baseData
      updateAgentInfo(spriteId, profileData)
    }
  }, [profileIdMap, updateAgentInfo, agentPanels])

  useEffect(() => {
    const updatesBySpriteId = new Map<
      string,
      {
        latestTaskRun: RawTaskRun
        currentTask?: VisualizationTask
        taskHistory: VisualizationTask[]
      }
    >()

    const taskRuns = Object.values(taskRunsById).sort(
      (a, b) => getTaskRunSortTime(b) - getTaskRunSortTime(a),
    )

    for (const taskRun of taskRuns) {
      const spriteId = resolveSessionTaskRunSpriteId(taskRun, sessionId, profileIdMap)
      if (!spriteId) continue

      const agentStepRuns = Object.values(stepRunsById).filter(
        (sr) => sr.task_run_id === taskRun.task_run_id,
      )
      const update = updatesBySpriteId.get(spriteId)
      const previousCurrentTask = update?.currentTask ?? agentInfoMap[spriteId]?.currentTask
      const currentTask = pickCurrentVisualizationTask({
        taskRun,
        stepRuns: agentStepRuns,
        previousCurrentTask,
      })
      const taskHistory = pickTaskHistory(taskRun, agentStepRuns)

      if (update === undefined) {
        updatesBySpriteId.set(spriteId, {
          latestTaskRun: taskRun,
          currentTask,
          taskHistory,
        })
        continue
      }

      for (const task of taskHistory) {
        if (!update.taskHistory.some((existing) => existing.taskId === task.taskId)) {
          update.taskHistory.push(task)
        }
      }
      if (update.currentTask === undefined && currentTask !== undefined) {
        update.currentTask = currentTask
      }
    }

    for (const [spriteId, update] of updatesBySpriteId) {
      updateAgentInfo(spriteId, {
        activityStatus:
          update.currentTask !== undefined
            ? 'working'
            : toActivityStatus(update.latestTaskRun.status),
        currentTask: update.currentTask,
        ...(update.taskHistory.length > 0 ? { taskHistory: update.taskHistory.slice(0, 5) } : {}),
      })
    }
  }, [sessionId, taskRunsById, stepRunsById, updateAgentInfo, profileIdMap, agentInfoMap])

  useEffect(() => {
    if (!selectedAgentId) return

    const taskRun = Object.values(taskRunsById)
      .filter(
        (tr) => resolveSessionTaskRunSpriteId(tr, sessionId, profileIdMap) === selectedAgentId,
      )
      .sort((a, b) => getTaskRunSortTime(b) - getTaskRunSortTime(a))[0]
    if (!taskRun) return
    if (fetchedTaskRunIds.current.has(taskRun.task_run_id)) return

    fetchedTaskRunIds.current.add(taskRun.task_run_id)
    void fetchSnapshot(taskRun.task_run_id)
  }, [fetchSnapshot, selectedAgentId, sessionId, taskRunsById, profileIdMap])
}
