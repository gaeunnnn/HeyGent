import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const panelPath = resolve(currentDir, 'WorkflowRoutinePanel.tsx')

test('workflow routine panel uses workflow import CTA and full-width page spacing', async () => {
  const source = await readFile(panelPath, 'utf8')

  assert.match(source, /워크플로우 불러오기/)
  assert.match(source, /불러올 워크플로우/)
  assert.match(source, /편집/)
  assert.match(source, /min-h-full p-6/)
  assert.doesNotMatch(source, /max-w-5xl/)
  assert.doesNotMatch(source, /루틴 만들기/)
  assert.doesNotMatch(source, /작업 불러오기/)
  assert.doesNotMatch(source, /DropdownMenuItem onClick=\{\(\) => onRunNow\(schedule\)\}>지금 실행/)
})
