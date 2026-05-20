import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..')
const outDir = resolve(rootDir, '../tmp/frontend-workflow-agent-choice-tests')

async function importWorkflowAgentChoices() {
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
      'src/components/sessionWorkspace/work/board/workflowAgentChoices.ts',
    ],
    { cwd: rootDir, stdio: 'pipe' },
  )
  return import(`${pathToFileURL(resolve(outDir, 'board/workflowAgentChoices.js')).href}?v=${Date.now()}`)
}

test('workflow add menu exposes only owned session agents', async () => {
  const { buildWorkflowAgentChoices } = await importWorkflowAgentChoices()

  const choices = buildWorkflowAgentChoices([
    { id: 'CEO', name: '팀장 에이전트' },
    { id: 'agent-dev', name: '내 개발 에이전트', templateKey: 'coder', imageUrl: null },
    { id: 'agent-qa', name: '내 QA 에이전트', templateKey: 'qa', imageUrl: '/agent.png' },
  ])

  const names = choices.map((choice) => choice.name)
  const ids = choices.map((choice) => choice.id)
  const templateKeys = choices.map((choice) => choice.templateKey)

  assert.deepEqual(ids, ['agent-dev', 'agent-qa'])
  assert.deepEqual(names, ['내 개발 에이전트', '내 QA 에이전트'])
  assert.deepEqual(templateKeys, ['coder', 'qa'])
  assert.ok(!names.includes('팀장 에이전트'))
  assert.ok(!names.includes('기본 에이전트'))
  assert.ok(!names.includes('보안 에이전트'))
  assert.ok(!templateKeys.includes('default'))
  assert.ok(!templateKeys.includes('security_engineer'))
})
