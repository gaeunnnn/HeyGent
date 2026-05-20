export type WorkflowRoutineSchedule = {
  cronExpression: string | null
  createdAt: string
  enabled: boolean
  id: string
  lastRunAt: string | null
  scheduledAt: string
  sessionId: string
  templateId: string
  templateName: string
  triggerKind: 'once' | 'schedule'
  updatedAt: string
}

export const WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT = 'workflow-routine-schedules-changed'

const STORAGE_PREFIX = 'heygent.workflowRoutines'

export function createWorkflowRoutineSchedule(input: {
  cronExpression?: string | null
  scheduledAt: string
  sessionId: string
  templateId: string
  templateName: string
  triggerKind?: 'once' | 'schedule'
  now?: Date
}): WorkflowRoutineSchedule {
  const now = input.now ?? new Date()
  const timestamp = now.toISOString()
  const triggerKind = input.triggerKind ?? 'once'
  return {
    cronExpression: triggerKind === 'schedule' ? (input.cronExpression ?? '0 10 * * *') : null,
    createdAt: timestamp,
    enabled: true,
    id: `${input.sessionId}:${input.templateId}:${input.scheduledAt}`,
    lastRunAt: null,
    scheduledAt: input.scheduledAt,
    sessionId: input.sessionId,
    templateId: input.templateId,
    templateName: input.templateName,
    triggerKind,
    updatedAt: timestamp,
  }
}

export function getDueWorkflowRoutineSchedules(
  schedules: WorkflowRoutineSchedule[],
  now = new Date(),
): WorkflowRoutineSchedule[] {
  const currentDateTime = formatLocalDateTime(now)
  return schedules.filter((schedule) => {
    if (!schedule.enabled || !isValidScheduledAt(schedule.scheduledAt)) return false
    if (schedule.scheduledAt > currentDateTime) return false
    if (schedule.triggerKind === 'once') return schedule.lastRunAt === null
    if (!schedule.cronExpression || !cronMatches(schedule.cronExpression, now)) return false
    return getLocalMinuteKey(schedule.lastRunAt) !== getLocalMinuteKey(now)
  })
}

export function markWorkflowRoutineRan(
  schedule: WorkflowRoutineSchedule,
  now = new Date(),
): WorkflowRoutineSchedule {
  return {
    ...schedule,
    enabled: schedule.triggerKind === 'schedule',
    lastRunAt: now.toISOString(),
    updatedAt: now.toISOString(),
  }
}

export function upsertWorkflowRoutineSchedule(
  schedules: WorkflowRoutineSchedule[],
  schedule: WorkflowRoutineSchedule,
): WorkflowRoutineSchedule[] {
  const next = schedules.filter((item) => item.id !== schedule.id)
  return [...next, schedule].sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt))
}

export function updateWorkflowRoutineSchedule(
  schedules: WorkflowRoutineSchedule[],
  scheduleId: string,
  patch: Partial<
    Pick<
      WorkflowRoutineSchedule,
      'cronExpression' | 'enabled' | 'lastRunAt' | 'scheduledAt' | 'templateName' | 'triggerKind'
    >
  >,
  now = new Date(),
): WorkflowRoutineSchedule[] {
  return schedules.map((schedule) =>
    schedule.id === scheduleId
      ? {
          ...schedule,
          ...patch,
          updatedAt: now.toISOString(),
        }
      : schedule,
  )
}

export function removeWorkflowRoutineSchedule(
  schedules: WorkflowRoutineSchedule[],
  scheduleId: string,
): WorkflowRoutineSchedule[] {
  return schedules.filter((schedule) => schedule.id !== scheduleId)
}

export function readWorkflowRoutineSchedules(sessionId: string): WorkflowRoutineSchedule[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(getWorkflowRoutineStorageKey(sessionId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeWorkflowRoutineSchedule).filter(isWorkflowRoutineSchedule)
  } catch {
    return []
  }
}

export function writeWorkflowRoutineSchedules(
  sessionId: string,
  schedules: WorkflowRoutineSchedule[],
) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(getWorkflowRoutineStorageKey(sessionId), JSON.stringify(schedules))
  window.dispatchEvent(
    new CustomEvent(WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT, { detail: { sessionId } }),
  )
}

export function getWorkflowRoutineStorageKey(sessionId: string) {
  return `${STORAGE_PREFIX}.${sessionId}`
}

export function formatWorkflowRoutineScheduleLabel(scheduledAt: string) {
  if (!isValidScheduledAt(scheduledAt)) return scheduledAt
  const [dateText, timeText] = scheduledAt.split('T')
  const [hourText, minuteText] = timeText.split(':')
  const hour = Number(hourText)
  const period = hour < 12 ? '오전' : '오후'
  const displayHour = hour % 12 === 0 ? 12 : hour % 12
  return `${dateText} ${period} ${displayHour}:${minuteText}`
}

export function formatWorkflowRoutineLastRunLabel(lastRunAt: string | null) {
  if (lastRunAt === null) return 'Never'
  const date = new Date(lastRunAt)
  if (Number.isNaN(date.getTime())) return lastRunAt
  return date.toLocaleString()
}

function isWorkflowRoutineSchedule(value: unknown): value is WorkflowRoutineSchedule {
  if (typeof value !== 'object' || value === null) return false
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'string' &&
    typeof item.sessionId === 'string' &&
    typeof item.scheduledAt === 'string' &&
    typeof item.templateId === 'string' &&
    typeof item.templateName === 'string' &&
    (item.triggerKind === 'once' || item.triggerKind === 'schedule') &&
    (typeof item.cronExpression === 'string' || item.cronExpression === null) &&
    typeof item.enabled === 'boolean' &&
    (typeof item.lastRunAt === 'string' || item.lastRunAt === null)
  )
}

function normalizeWorkflowRoutineSchedule(value: unknown): WorkflowRoutineSchedule | unknown {
  if (typeof value !== 'object' || value === null) return value
  const item = value as Record<string, unknown>
  if (typeof item.scheduledAt === 'string') return value
  if (typeof item.timeOfDay !== 'string') return value
  const scheduledAt = `${formatLocalDate(new Date())}T${item.timeOfDay}`
  return {
    ...item,
    id:
      typeof item.id === 'string' && item.id.split(':').length >= 3
        ? item.id
        : `${String(item.sessionId)}:${String(item.templateId)}:${scheduledAt}`,
    lastRunAt: null,
    cronExpression: null,
    scheduledAt,
    triggerKind: 'once',
  }
}

function cronMatches(cronExpression: string, date: Date) {
  const parts = cronExpression.trim().split(/\s+/)
  if (parts.length !== 5) return false
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts
  return (
    cronPartMatches(minute, date.getMinutes()) &&
    cronPartMatches(hour, date.getHours()) &&
    cronPartMatches(dayOfMonth, date.getDate()) &&
    cronPartMatches(month, date.getMonth() + 1) &&
    cronDayOfWeekMatches(dayOfWeek, date.getDay())
  )
}

function cronPartMatches(part: string, value: number) {
  if (part === '*') return true
  if (/^\d+$/.test(part)) return Number(part) === value
  return false
}

function cronDayOfWeekMatches(part: string, value: number) {
  if (part === '*') return true
  if (part === '1-5') return value >= 1 && value <= 5
  return cronPartMatches(part, value)
}

function isValidScheduledAt(value: string) {
  return /^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatLocalTime(date: Date) {
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${hour}:${minute}`
}

function formatLocalDateTime(date: Date) {
  return `${formatLocalDate(date)}T${formatLocalTime(date)}`
}

function getLocalMinuteKey(value: Date | string | null) {
  if (value === null) return null
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return null
  return formatLocalDateTime(date)
}
