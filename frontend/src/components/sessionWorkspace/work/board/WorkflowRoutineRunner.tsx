import { useCallback, useEffect, useMemo, useRef } from 'react'
import { toast } from 'sonner'
import { listWorkflowTemplates, type WorkflowTemplate } from '@/apis/workflowTemplates'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { buildWorkflowAssignees } from './workflowAssignees'
import {
  getDueWorkflowRoutineSchedules,
  markWorkflowRoutineRan,
  readWorkflowRoutineSchedules,
  WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT,
  writeWorkflowRoutineSchedules,
} from './workflowRoutineSchedule'
import { runWorkflowTemplate } from './workflowTemplateRunner'

const EMPTY_AGENT_PANELS: ReturnType<
  typeof useSessionStore.getState
>['agentPanelsBySessionId'][string] = []
const ROUTINE_CHECK_INTERVAL_MS = 30_000

export function WorkflowRoutineRunner({ sessionId }: { sessionId: string }) {
  const agentPanelsBySessionId = useSessionStore((state) => state.agentPanelsBySessionId)
  const sendChatMessage = useChatStore((state) => state.sendMessage)
  const assignees = useMemo(
    () => buildWorkflowAssignees(agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS),
    [agentPanelsBySessionId, sessionId],
  )
  const assigneesRef = useRef(assignees)
  const sendChatMessageRef = useRef(sendChatMessage)
  const templatesRef = useRef<WorkflowTemplate[]>([])
  const runningScheduleIdsRef = useRef(new Set<string>())

  useEffect(() => {
    assigneesRef.current = assignees
  }, [assignees])

  useEffect(() => {
    sendChatMessageRef.current = sendChatMessage
  }, [sendChatMessage])

  const refreshTemplates = useCallback(async () => {
    if (sessionId.startsWith('pending_session_')) return
    try {
      const response = await listWorkflowTemplates(sessionId)
      templatesRef.current = response.items
    } catch (error) {
      console.error('workflow routine template refresh failed', error)
    }
  }, [sessionId])

  const runDueSchedules = useCallback(async () => {
    if (sessionId.startsWith('pending_session_')) return
    const now = new Date()
    const schedules = readWorkflowRoutineSchedules(sessionId)
    const dueSchedules = getDueWorkflowRoutineSchedules(schedules, now)
    if (dueSchedules.length === 0) return

    for (const schedule of dueSchedules) {
      if (runningScheduleIdsRef.current.has(schedule.id)) continue
      const template = templatesRef.current.find((item) => item.templateId === schedule.templateId)
      if (template === undefined) {
        void refreshTemplates()
        continue
      }

      runningScheduleIdsRef.current.add(schedule.id)
      try {
        const result = await runWorkflowTemplate({
          assignees: assigneesRef.current,
          sendChatMessage: sendChatMessageRef.current,
          sessionId,
          template,
        })
        const latestSchedules = readWorkflowRoutineSchedules(sessionId)
        const nextSchedules = latestSchedules.map((item) =>
          item.id === schedule.id ? markWorkflowRoutineRan(item, now) : item,
        )
        writeWorkflowRoutineSchedules(sessionId, nextSchedules)

        if (result.chatSent) {
          toast.success(`"${schedule.templateName}" 루틴을 실행했습니다`)
        } else {
          console.error('workflow routine chat send failed', result.chatError)
          toast.warning('루틴 작업은 생성됐지만 채팅 메시지 전송은 실패했습니다')
        }
      } catch (error) {
        console.error('workflow routine run failed', error)
        toast.error(`"${schedule.templateName}" 루틴 실행에 실패했습니다`)
      } finally {
        runningScheduleIdsRef.current.delete(schedule.id)
      }
    }
  }, [refreshTemplates, sessionId])

  useEffect(() => {
    void refreshTemplates()
  }, [refreshTemplates])

  useEffect(() => {
    void runDueSchedules()
    const intervalId = window.setInterval(() => {
      void runDueSchedules()
    }, ROUTINE_CHECK_INTERVAL_MS)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [runDueSchedules])

  useEffect(() => {
    const handleSchedulesChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string }>).detail
      if (detail?.sessionId === sessionId) {
        void refreshTemplates()
        void runDueSchedules()
      }
    }
    window.addEventListener(WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT, handleSchedulesChanged)
    return () => {
      window.removeEventListener(WORKFLOW_ROUTINE_SCHEDULES_CHANGED_EVENT, handleSchedulesChanged)
    }
  }, [refreshTemplates, runDueSchedules, sessionId])

  return null
}
