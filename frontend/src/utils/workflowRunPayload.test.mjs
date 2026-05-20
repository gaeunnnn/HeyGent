import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const outDir = resolve(rootDir, '../tmp/frontend-workflow-tests')

async function importWorkflowRunPayload() {
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
      'src/utils/workflowRunPayload.ts',
    ],
    { cwd: rootDir, stdio: 'pipe' },
  )
  return import(`${pathToFileURL(resolve(outDir, 'workflowRunPayload.js')).href}?v=${Date.now()}`)
}

test('workflow run input links chat TaskRun to root work and strict child reuse', async () => {
  const { buildWorkflowRunInputPayload } = await importWorkflowRunPayload()

  const inputPayload = buildWorkflowRunInputPayload({
    templateId: 'wftmpl-1',
    templateName: '삼성 관련 조사 공유 및 UX 화면 확인',
    rootWorkId: 'work-root',
    childWorkIds: ['work-research', 'work-screen'],
    childrenBySlotKey: {
      research: 'work-research',
      screen: 'work-screen',
    },
    children: [
      {
        slotKey: 'research',
        workId: 'work-research',
        identifier: 'TASK-2',
        title: '삼성 관련 조사',
        assigneeAgentId: 'agent-dev',
      },
    ],
  })

  assert.equal(inputPayload.workId, 'work-root')
  assert.equal(inputPayload.workflowExecution.mode, 'strict_reuse_children')
  assert.deepEqual(inputPayload.workflowExecution.childWorkIds, ['work-research', 'work-screen'])
  assert.equal(inputPayload.workflowExecution.childrenBySlotKey.research, 'work-research')
  assert.equal(inputPayload.workflowExecution.children[0].identifier, 'TASK-2')
})

test('workflow run trigger tells team lead to use existing child work ids', async () => {
  const { buildWorkflowRunTrigger } = await importWorkflowRunPayload()

  const trigger = buildWorkflowRunTrigger({
    templateName: '삼성 관련 조사 공유 및 UX 화면 확인',
    templateDescription:
      '삼성 관련 조사 결과를 Mattermost 우리만 채널로 보내고, UX 디자이너가 만든 화면을 확인한 뒤 사용자에게 보여준다.',
    children: [
      {
        slotKey: 'research',
        workId: 'work-research',
        identifier: 'TASK-2',
        title: '삼성 관련 조사',
        description: '삼성 관련 최신 동향을 조사한다.',
        assigneeName: '개발 에이전트',
      },
    ],
    edges: [],
  })

  assert.match(trigger, /childWorkId: work-research/)
  assert.match(trigger, /TASK-2/)
  assert.match(trigger, /새 작업 만들지 마세요/)
})
