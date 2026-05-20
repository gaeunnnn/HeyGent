type VisualizationTaskLike = {
  taskId: string
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  startedAt?: string
  completedAt?: string
}

type TaskRunLike = {
  task_run_id: string
  status?: string | null
  title?: string | null
  created_at?: string | null
}

type StepRunLike = {
  step_run_id: string
  task_run_id?: string | null
  status?: string | null
  title?: string | null
  goal?: string | null
  semantic?: { goal?: unknown } | null
  step_order?: number | null
  stepOrder?: number | null
  started_at?: string | null
  updated_at?: string | null
}

const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELED', 'CANCELLED'])
const ACTIVE_STEP_STATUSES = new Set(['RUNNING', 'WAITING', 'BLOCKED'])
const ACTIVE_TASK_STATUSES = new Set(['RUNNING', 'WAITING', 'BLOCKED'])

export function pickCurrentVisualizationTask(input: {
  taskRun: TaskRunLike
  stepRuns: StepRunLike[]
  previousCurrentTask?: VisualizationTaskLike
}): VisualizationTaskLike | undefined {
  const taskStatus = input.taskRun.status?.toUpperCase()
  if (TERMINAL_STATUSES.has(taskStatus ?? '')) return undefined

  const activeStep = input.stepRuns
    .filter((stepRun) => ACTIVE_STEP_STATUSES.has(stepRun.status?.toUpperCase() ?? ''))
    .sort(compareStepRunPriority)[0]

  if (activeStep !== undefined) {
    const title = typeof activeStep.title === 'string' ? activeStep.title.trim() : ''
    if (title === '') return keepPreviousStepTask(input)
    const nextTask: VisualizationTaskLike = {
      taskId: activeStep.step_run_id,
      title,
      description: getStepRunGoal(activeStep),
      status: 'in_progress',
      startedAt: activeStep.started_at ?? undefined,
    }
    return areVisualizationTasksEqual(nextTask, input.previousCurrentTask)
      ? input.previousCurrentTask
      : nextTask
  }

  return keepPreviousStepTask(input)
}

export function areVisualizationTasksEqual(
  left?: VisualizationTaskLike,
  right?: VisualizationTaskLike,
): boolean {
  if (left === right) return true
  if (left === undefined || right === undefined) return false
  return (
    left.taskId === right.taskId &&
    left.title === right.title &&
    left.description === right.description &&
    left.status === right.status &&
    left.startedAt === right.startedAt &&
    left.completedAt === right.completedAt
  )
}

function keepPreviousStepTask(input: {
  taskRun: TaskRunLike
  stepRuns: StepRunLike[]
  previousCurrentTask?: VisualizationTaskLike
}): VisualizationTaskLike | undefined {
  const taskStatus = input.taskRun.status?.toUpperCase()
  if (!ACTIVE_TASK_STATUSES.has(taskStatus ?? '')) return undefined
  if (input.previousCurrentTask === undefined) return undefined

  const previousStepStillBelongsToTask = input.stepRuns.some(
    (stepRun) => stepRun.step_run_id === input.previousCurrentTask?.taskId,
  )
  return previousStepStillBelongsToTask ? input.previousCurrentTask : undefined
}

function compareStepRunPriority(left: StepRunLike, right: StepRunLike): number {
  const orderDelta =
    (right.step_order ?? right.stepOrder ?? 0) - (left.step_order ?? left.stepOrder ?? 0)
  if (orderDelta !== 0) return orderDelta
  return (
    getTimestamp(right.updated_at ?? right.started_at) -
    getTimestamp(left.updated_at ?? left.started_at)
  )
}

function getStepRunGoal(stepRun: StepRunLike): string {
  if (typeof stepRun.goal === 'string') return stepRun.goal
  const semantic = stepRun.semantic
  if (typeof semantic === 'object' && semantic !== null && typeof semantic.goal === 'string') {
    return semantic.goal
  }
  return ''
}

function getTimestamp(value?: string | null): number {
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? time : 0
}
