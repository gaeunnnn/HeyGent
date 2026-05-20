import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..')
const outDir = resolve(rootDir, '../tmp/frontend-workflow-routine-tests')

async function importWorkflowRoutineSchedule() {
  await rm(outDir, { recursive: true, force: true })
  await mkdir(outDir, { recursive: true })
  execFileSync(
    process.execPath,
    [
      resolve(rootDir, 'node_modules/typescript/bin/tsc'),
      '--ignoreConfig',
      '--target',
      'ES2022',
      '--module',
      'ES2022',
      '--moduleResolution',
      'Bundler',
      '--strict',
      '--skipLibCheck',
      '--outDir',
      outDir,
      'src/components/sessionWorkspace/work/board/workflowRoutineSchedule.ts',
    ],
    { cwd: rootDir, stdio: 'pipe' },
  )
  return import(
    `${pathToFileURL(resolve(outDir, 'workflowRoutineSchedule.js')).href}?v=${Date.now()}`
  )
}

test('workflow routine schedule fires once at the selected local date and minute', async () => {
  const {
    createWorkflowRoutineSchedule,
    getDueWorkflowRoutineSchedules,
    markWorkflowRoutineRan,
  } = await importWorkflowRoutineSchedule()

  const schedule = createWorkflowRoutineSchedule({
    sessionId: 'session-1',
    templateId: 'template-1',
    templateName: '아침 점검',
    scheduledAt: '2026-05-21T09:30',
    now: new Date('2026-05-21T09:00:00+09:00'),
  })

  assert.equal(schedule.id, 'session-1:template-1:2026-05-21T09:30')
  assert.equal(schedule.scheduledAt, '2026-05-21T09:30')

  assert.deepEqual(
    getDueWorkflowRoutineSchedules([schedule], new Date('2026-05-21T09:29:00+09:00')),
    [],
  )
  assert.equal(
    getDueWorkflowRoutineSchedules([schedule], new Date('2026-05-21T09:31:00+09:00'))[0]?.id,
    schedule.id,
  )

  const ran = markWorkflowRoutineRan(schedule, new Date('2026-05-21T09:31:00+09:00'))

  assert.equal(ran.enabled, false)
  assert.equal(ran.lastRunAt, '2026-05-21T00:31:00.000Z')
  assert.deepEqual(
    getDueWorkflowRoutineSchedules([ran], new Date('2026-05-21T10:00:00+09:00')),
    [],
  )
  assert.deepEqual(
    getDueWorkflowRoutineSchedules([ran], new Date('2026-05-22T09:31:00+09:00')),
    [],
  )
})

test('workflow routine schedule repeats by cron after its start date', async () => {
  const {
    createWorkflowRoutineSchedule,
    getDueWorkflowRoutineSchedules,
    markWorkflowRoutineRan,
  } = await importWorkflowRoutineSchedule()

  const schedule = createWorkflowRoutineSchedule({
    sessionId: 'session-1',
    templateId: 'template-1',
    templateName: '매일 점검',
    triggerKind: 'schedule',
    scheduledAt: '2026-05-21T09:30',
    cronExpression: '30 9 * * *',
    now: new Date('2026-05-21T09:00:00+09:00'),
  })

  assert.deepEqual(
    getDueWorkflowRoutineSchedules([schedule], new Date('2026-05-21T09:29:00+09:00')),
    [],
  )
  assert.equal(
    getDueWorkflowRoutineSchedules([schedule], new Date('2026-05-21T09:30:00+09:00'))[0]?.id,
    schedule.id,
  )

  const ran = markWorkflowRoutineRan(schedule, new Date('2026-05-21T09:30:00+09:00'))

  assert.equal(ran.enabled, true)
  assert.deepEqual(
    getDueWorkflowRoutineSchedules([ran], new Date('2026-05-21T09:30:30+09:00')),
    [],
  )
  assert.equal(
    getDueWorkflowRoutineSchedules([ran], new Date('2026-05-22T09:30:00+09:00'))[0]?.id,
    schedule.id,
  )
})
