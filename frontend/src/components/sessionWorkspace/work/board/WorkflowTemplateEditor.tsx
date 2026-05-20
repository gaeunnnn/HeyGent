import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useInternalNode,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type InternalNode,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Loader2, Pencil, Play, Plus, Save, Trash2, Workflow, X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/components/ui/utils'
import { toast } from 'sonner'
import type { BoardAssignee } from './issueBoardPanelTypes'
import {
  createWorkflowTemplate,
  deleteWorkflowTemplate,
  instantiateWorkflowTemplate,
  listWorkflowTemplates,
  updateWorkflowTemplate,
  type WorkflowTemplate,
  type WorkflowTemplateEdge as ApiTplEdge,
  type WorkflowTemplateNode as ApiTplNode,
} from '@/apis/workflowTemplates'
import { useChatStore } from '@/store/useChatStore'
import { buildWorkflowRunInputPayload, buildWorkflowRunTrigger } from '@/utils/workflowRunPayload'

type AgentChoice = {
  assigneeAgentId: string | null
  defaultTitle: string
  id: string
  imageUrl?: string | null
  name: string
  provided?: boolean
  templateKey?: string
}

const CEO_PROFILE_IMAGE = '/assets/agents/ceo/ceo_profile_img.png'

type FlowNodeData = Record<string, unknown> & {
  imageUrl?: string
  agentName?: string
  templateNode?: ApiTplNode
  label?: string
  onCardClick?: () => void
  isConnectingSource?: boolean
  isConnectingValidTarget?: boolean
  isConnectingInvalidTarget?: boolean
  inStartBox?: boolean
}

type FlowNode = Node<FlowNodeData>

const FLOW_NODE_TYPES = {
  tplNode: TemplateFlowNode,
  ceo: CeoFlowNode,
  startBox: StartBoxFlowNode,
}
const FLOW_EDGE_TYPES = { blocks: BlocksEdge }

const CEO_NODE_ID = 'ceo'
const START_BOX_NODE_ID = 'start-box'

// 캔버스 배경: 진한 회색 (모눈종이 느낌)
const CANVAS_BG_STYLE: CSSProperties = {
  background: '#a8aeb8',
}

const CEO_NODE_WIDTH = 240
const CEO_NODE_HEIGHT = 70
const START_BOX_X = 80
const START_BOX_Y = 220
const START_BOX_HEIGHT = 220
const START_BOX_MIN_WIDTH = 240
const START_NODE_GAP = 160
const START_NODE_OFFSET_X = 60
const START_NODE_OFFSET_Y = 40
const START_NODE_WIDTH = 148
const OUTSIDE_START_X = 120
const OUTSIDE_START_Y = 560
const OUTSIDE_STEP_X = 200
const OUTSIDE_STEP_Y = 250

// 슬롯 키 생성기
function newSlotKey(): string {
  return `n_${Math.random().toString(36).slice(2, 10)}`
}

export function WorkflowTemplateEditor({
  assignees,
  sessionId,
  onEnsureDefaultAgents,
  onEnsureProvidedAgent,
}: {
  assignees: BoardAssignee[]
  sessionId: string
  onEnsureDefaultAgents: () => Promise<BoardAssignee[]>
  onEnsureProvidedAgent: (templateKey: string) => Promise<BoardAssignee[]>
}) {
  return (
    <ReactFlowProvider>
      <WorkflowTemplateEditorInner
        assignees={assignees}
        sessionId={sessionId}
        onEnsureDefaultAgents={onEnsureDefaultAgents}
        onEnsureProvidedAgent={onEnsureProvidedAgent}
      />
    </ReactFlowProvider>
  )
}

function WorkflowTemplateEditorInner({
  assignees,
  sessionId,
  onEnsureDefaultAgents,
  onEnsureProvidedAgent,
}: {
  assignees: BoardAssignee[]
  sessionId: string
  onEnsureDefaultAgents: () => Promise<BoardAssignee[]>
  onEnsureProvidedAgent: (templateKey: string) => Promise<BoardAssignee[]>
}) {
  // ── 템플릿 목록 ──
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const selectedTemplate = useMemo(
    () => templates.find((t) => t.templateId === selectedTemplateId) ?? null,
    [templates, selectedTemplateId],
  )

  // ── 캔버스 데이터 (드래프트 — 아직 저장 전) ──
  // template 선택 시 그 graph 를 여기로 복사. 사용자 편집 = 이 상태만 바뀜.
  const [draftNodes, setDraftNodes] = useState<ApiTplNode[]>([])
  const [draftEdges, setDraftEdges] = useState<ApiTplEdge[]>([])
  const [draftDirty, setDraftDirty] = useState(false)
  // 그림(=팀장 작업) 메타데이터 (이름, 지시사항)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  // 팀장 카드 편집 모달
  const [leaderModalOpen, setLeaderModalOpen] = useState(false)
  const [leaderInitializing, setLeaderInitializing] = useState(false) // 처음 정의 vs 수정

  // 사용자 드래그 위치 (캐시)
  const [userPositions, setUserPositions] = useState<Record<string, { x: number; y: number }>>({})

  // 잇기 상태
  const [connectingSourceSlot, setConnectingSourceSlot] = useState<string | null>(null)
  const [pointerPos, setPointerPos] = useState<{ x: number; y: number } | null>(null)
  const [actionSheetSlot, setActionSheetSlot] = useState<string | null>(null)
  const [edgeToDelete, setEdgeToDelete] = useState<{ source: string; target: string } | null>(null)

  // 작업 추가 모달
  const [composerOpen, setComposerOpen] = useState(false)
  const [composerAgent, setComposerAgent] = useState<AgentChoice | null>(null)
  const [composerTitle, setComposerTitle] = useState('')
  const [composerDescription, setComposerDescription] = useState('')
  const [composerAgentBusy, setComposerAgentBusy] = useState(false)
  const [editingSlot, setEditingSlot] = useState<string | null>(null) // 노드 수정

  // 저장/실행
  const [busySaving, setBusySaving] = useState(false)
  const [busyRunning, setBusyRunning] = useState(false)

  // ── 템플릿 목록 로드 ──
  const refreshTemplates = useCallback(async () => {
    try {
      const res = await listWorkflowTemplates(sessionId)
      setTemplates(res.items)
      if (selectedTemplateId === null && res.items.length > 0) {
        setSelectedTemplateId(res.items[0].templateId)
      }
    } catch (error) {
      console.error(error)
    }
  }, [selectedTemplateId, sessionId])

  /* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */
  useEffect(() => {
    void refreshTemplates()
  }, [])

  // 선택된 템플릿 → 드래프트로 로드
  useEffect(() => {
    if (!selectedTemplate) {
      setDraftNodes([])
      setDraftEdges([])
      setDraftDirty(false)
      setUserPositions({})
      setDraftName('')
      setDraftDescription('')
      return
    }
    setDraftNodes(selectedTemplate.graph.nodes.map((n) => ({ ...n })))
    setDraftEdges(selectedTemplate.graph.edges.map((e) => ({ ...e })))
    setDraftDirty(false)
    setDraftName(selectedTemplate.name)
    setDraftDescription(selectedTemplate.description)
    const positions: Record<string, { x: number; y: number }> = {}
    for (const n of selectedTemplate.graph.nodes) {
      if (n.positionX || n.positionY) {
        positions[`work:${n.slotKey}`] = { x: n.positionX, y: n.positionY }
      }
    }
    setUserPositions(positions)
  }, [selectedTemplate])
  /* eslint-enable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */

  // ── agent picker 목록 ──
  const agentChoices = useMemo<AgentChoice[]>(
    () => [
      ...assignees
        .filter((assignee) => assignee.id !== 'CEO')
        .map((assignee) => ({
          id: assignee.id,
          name: assignee.name,
          defaultTitle: `${assignee.name} 작업`,
          assigneeAgentId: assignee.id,
          templateKey: assignee.templateKey,
          imageUrl: assignee.imageUrl ?? undefined,
        })),
      ...DEFAULT_AGENT_CHOICES.filter(
        (choice) => !assignees.some((assignee) => assignee.templateKey === choice.templateKey),
      ),
    ],
    [assignees],
  )

  // ── 사이클/중복 가드 ──
  const wouldCreateCycle = useCallback(
    (sourceSlot: string, targetSlot: string): boolean => {
      const adj = new Map<string, string[]>()
      for (const n of draftNodes) adj.set(n.slotKey, [])
      for (const e of draftEdges) adj.get(e.sourceSlotKey)?.push(e.targetSlotKey)
      const seen = new Set<string>()
      const queue = [targetSlot]
      while (queue.length > 0) {
        const cur = queue.shift() as string
        if (cur === sourceSlot) return true
        if (seen.has(cur)) continue
        seen.add(cur)
        for (const n of adj.get(cur) ?? []) if (!seen.has(n)) queue.push(n)
      }
      return false
    },
    [draftEdges, draftNodes],
  )

  const relationExists = useCallback(
    (sourceSlot: string, targetSlot: string): boolean => {
      return draftEdges.some(
        (e) => e.sourceSlotKey === sourceSlot && e.targetSlotKey === targetSlot,
      )
    },
    [draftEdges],
  )

  // 박스 안/밖
  const isPosInsideBox = useCallback(
    (
      pos: { x: number; y: number } | undefined,
      boxPos: { x: number; y: number },
      boxWidth: number,
    ): boolean => {
      if (!pos) return false
      const cx = pos.x + START_NODE_WIDTH / 2
      const cy = pos.y + 80
      return (
        cx >= boxPos.x &&
        cx <= boxPos.x + boxWidth &&
        cy >= boxPos.y &&
        cy <= boxPos.y + START_BOX_HEIGHT
      )
    },
    [],
  )

  const { inStartBox, outsideOrder } = useMemo(() => {
    const boxPos = userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y }
    // 들어오는 화살표 없는 슬롯
    const incomingCount = new Map<string, number>()
    for (const n of draftNodes) incomingCount.set(n.slotKey, 0)
    for (const e of draftEdges) {
      incomingCount.set(e.targetSlotKey, (incomingCount.get(e.targetSlotKey) ?? 0) + 1)
    }
    const tentativeCount = draftNodes.filter(
      (n) => (incomingCount.get(n.slotKey) ?? 0) === 0,
    ).length
    const tentativeWidth = Math.max(
      START_BOX_MIN_WIDTH,
      START_NODE_OFFSET_X * 2 +
        Math.max(1, tentativeCount) * START_NODE_WIDTH +
        Math.max(0, tentativeCount - 1) * (START_NODE_GAP - START_NODE_WIDTH),
    )

    const inBox = new Set<string>()
    const outside: string[] = []
    for (const n of draftNodes) {
      const indegree = incomingCount.get(n.slotKey) ?? 0
      const userPos = userPositions[`work:${n.slotKey}`]
      if (indegree > 0) {
        outside.push(n.slotKey)
        continue
      }
      if (userPos === undefined) {
        inBox.add(n.slotKey)
      } else if (isPosInsideBox(userPos, boxPos, tentativeWidth)) {
        inBox.add(n.slotKey)
      } else {
        outside.push(n.slotKey)
      }
    }
    return { inStartBox: inBox, outsideOrder: outside }
  }, [draftNodes, draftEdges, isPosInsideBox, userPositions])

  const startBoxWidth = useMemo(() => {
    const count = Math.max(1, inStartBox.size)
    const needed =
      START_NODE_OFFSET_X * 2 +
      count * START_NODE_WIDTH +
      Math.max(0, count - 1) * (START_NODE_GAP - START_NODE_WIDTH)
    return Math.max(START_BOX_MIN_WIDTH, needed)
  }, [inStartBox])

  const ceoX = useMemo(() => START_BOX_X + startBoxWidth / 2 - CEO_NODE_WIDTH / 2, [startBoxWidth])
  const ceoY = 20

  // 자동 위치 계산
  const computeAutoPositions = useCallback((): Record<string, { x: number; y: number }> => {
    const positions: Record<string, { x: number; y: number }> = {}
    const boxPos = userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y }
    let boxIndex = 0
    for (const n of draftNodes) {
      const nodeId = `work:${n.slotKey}`
      if (inStartBox.has(n.slotKey)) {
        positions[nodeId] = {
          x: boxPos.x + START_NODE_OFFSET_X + boxIndex * START_NODE_GAP,
          y: boxPos.y + START_NODE_OFFSET_Y,
        }
        boxIndex++
      }
    }
    outsideOrder.forEach((slotKey, index) => {
      const nodeId = `work:${slotKey}`
      const col = index % 4
      const row = Math.floor(index / 4)
      positions[nodeId] = {
        x: OUTSIDE_START_X + col * OUTSIDE_STEP_X,
        y: OUTSIDE_START_Y + row * OUTSIDE_STEP_Y,
      }
    })
    return positions
  }, [draftNodes, inStartBox, outsideOrder, userPositions])

  // 잇기
  const canConnect = useCallback(
    (sourceSlot: string, targetSlot: string): boolean => {
      if (sourceSlot === targetSlot) return false
      if (inStartBox.has(sourceSlot) && inStartBox.has(targetSlot)) return false
      if (relationExists(sourceSlot, targetSlot)) return false
      if (wouldCreateCycle(sourceSlot, targetSlot)) return false
      return true
    },
    [inStartBox, relationExists, wouldCreateCycle],
  )

  useEffect(() => {
    if (connectingSourceSlot === null) return
    const handleMove = (event: MouseEvent) => {
      setPointerPos({ x: event.clientX, y: event.clientY })
    }
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setConnectingSourceSlot(null)
        setPointerPos(null)
      }
    }
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('keydown', handleEsc)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('keydown', handleEsc)
    }
  }, [connectingSourceSlot])

  const handleCardClick = useCallback(
    (slotKey: string) => {
      if (connectingSourceSlot !== null) {
        if (canConnect(connectingSourceSlot, slotKey)) {
          setDraftEdges((prev) => [
            ...prev,
            { sourceSlotKey: connectingSourceSlot, targetSlotKey: slotKey },
          ])
          setDraftDirty(true)
        }
        setConnectingSourceSlot(null)
        setPointerPos(null)
        return
      }
      setActionSheetSlot(slotKey)
    },
    [canConnect, connectingSourceSlot],
  )

  const cancelConnecting = useCallback(() => {
    setConnectingSourceSlot(null)
    setPointerPos(null)
  }, [])

  // 노드 드래그
  const handleNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      setUserPositions((prev) => {
        const next = { ...prev }
        let changed = false
        for (const change of changes) {
          if (change.type === 'position' && change.position) {
            // 박스 이동 시 박스 안 노드 캐시 지워서 자동 정렬로 따라가게
            if (change.id === START_BOX_NODE_ID) {
              next[change.id] = { x: change.position.x, y: change.position.y }
              for (const slotKey of inStartBox) {
                delete next[`work:${slotKey}`]
              }
              changed = true
              continue
            }
            next[change.id] = { x: change.position.x, y: change.position.y }
            changed = true
          }
        }
        if (changed) setDraftDirty(true)
        return next
      })
    },
    [inStartBox],
  )

  // 노드 추가 모달
  const openAddNode = () => {
    setEditingSlot(null)
    setComposerAgent(null)
    setComposerTitle('')
    setComposerDescription('')
    setComposerOpen(true)
  }

  const openEditNode = (slotKey: string) => {
    const node = draftNodes.find((n) => n.slotKey === slotKey)
    if (!node) return
    setEditingSlot(slotKey)
    setComposerAgent({
      id: node.assigneeAgentId ?? node.templateKey ?? 'unknown',
      name:
        assignees.find((a) => a.id === node.assigneeAgentId)?.name ??
        DEFAULT_AGENT_CHOICES.find((c) => c.templateKey === node.templateKey)?.name ??
        '에이전트',
      defaultTitle: node.title,
      assigneeAgentId: node.assigneeAgentId,
      templateKey: node.templateKey ?? undefined,
      imageUrl: assignees.find((a) => a.id === node.assigneeAgentId)?.imageUrl ?? undefined,
    })
    setComposerTitle(node.title)
    setComposerDescription(node.description)
    setComposerOpen(true)
  }

  const closeComposer = () => {
    setComposerOpen(false)
    setComposerAgent(null)
    setComposerTitle('')
    setComposerDescription('')
    setEditingSlot(null)
  }

  const handleSelectAgent = async (agent: AgentChoice) => {
    if (agent.provided && agent.templateKey === 'default') {
      setComposerAgent({
        ...agent,
        assigneeAgentId: null,
      })
      return
    }
    if (agent.provided && agent.templateKey) {
      setComposerAgentBusy(true)
      try {
        let next = await onEnsureDefaultAgents()
        let matched = next.find((assignee) => assignee.templateKey === agent.templateKey) ?? null
        if (!matched) {
          next = await onEnsureProvidedAgent(agent.templateKey)
          matched = next.find((assignee) => assignee.templateKey === agent.templateKey) ?? null
        }
        setComposerAgent({
          id: matched?.id ?? agent.id,
          name: matched?.name ?? agent.name,
          defaultTitle: agent.defaultTitle,
          assigneeAgentId: matched?.id ?? null,
          templateKey: agent.templateKey,
          imageUrl: matched?.imageUrl ?? agent.imageUrl ?? null,
        })
      } finally {
        setComposerAgentBusy(false)
      }
      return
    }
    setComposerAgent(agent)
  }

  const submitComposer = () => {
    const title = composerTitle.trim()
    if (!composerAgent || !title) return
    const description = composerDescription.trim() || title
    if (editingSlot) {
      setDraftNodes((prev) =>
        prev.map((n) =>
          n.slotKey === editingSlot
            ? {
                ...n,
                title,
                description,
                assigneeAgentId: composerAgent.assigneeAgentId,
                templateKey: composerAgent.templateKey ?? null,
              }
            : n,
        ),
      )
    } else {
      setDraftNodes((prev) => [
        ...prev,
        {
          slotKey: newSlotKey(),
          title,
          description,
          assigneeAgentId: composerAgent.assigneeAgentId,
          templateKey: composerAgent.templateKey ?? null,
          positionX: 0,
          positionY: 0,
        },
      ])
    }
    setDraftDirty(true)
    closeComposer()
  }

  // 노드 삭제
  const handleDeleteNode = (slotKey: string) => {
    setDraftNodes((prev) => prev.filter((n) => n.slotKey !== slotKey))
    setDraftEdges((prev) =>
      prev.filter((e) => e.sourceSlotKey !== slotKey && e.targetSlotKey !== slotKey),
    )
    setUserPositions((prev) => {
      const next = { ...prev }
      delete next[`work:${slotKey}`]
      return next
    })
    setActionSheetSlot(null)
    setDraftDirty(true)
  }

  // 화살표 삭제
  const handleDeleteEdge = (sourceSlot: string, targetSlot: string) => {
    setDraftEdges((prev) =>
      prev.filter((e) => !(e.sourceSlotKey === sourceSlot && e.targetSlotKey === targetSlot)),
    )
    setEdgeToDelete(null)
    setDraftDirty(true)
  }

  // ── 저장 ──
  const buildGraphForSave = useCallback(() => {
    return {
      nodes: draftNodes.map((n) => {
        const pos = userPositions[`work:${n.slotKey}`]
        return {
          ...n,
          positionX: pos?.x ?? n.positionX,
          positionY: pos?.y ?? n.positionY,
        }
      }),
      edges: draftEdges,
    }
  }, [draftEdges, draftNodes, userPositions])

  const handleSaveExisting = async () => {
    if (!selectedTemplate) return
    const name = draftName.trim()
    if (!name) {
      toast.error('작업명이 필요합니다')
      return
    }
    setBusySaving(true)
    try {
      const updated = await updateWorkflowTemplate(sessionId, selectedTemplate.templateId, {
        name,
        description: draftDescription,
        graph: buildGraphForSave(),
      })
      setTemplates((prev) => prev.map((t) => (t.templateId === updated.templateId ? updated : t)))
      setDraftDirty(false)
      toast.success('템플릿 저장됨')
    } catch (error) {
      console.error(error)
      toast.error('저장 실패')
    } finally {
      setBusySaving(false)
    }
  }

  const handleSaveNew = async () => {
    const name = draftName.trim()
    if (!name) {
      toast.error('작업명이 필요합니다')
      return
    }
    setBusySaving(true)
    try {
      const created = await createWorkflowTemplate(sessionId, {
        name,
        description: draftDescription,
        graph: buildGraphForSave(),
      })
      setTemplates((prev) => [created, ...prev])
      setSelectedTemplateId(created.templateId)
      setDraftDirty(false)
      toast.success(`템플릿 "${name}" 저장됨`)
    } catch (error) {
      console.error(error)
      toast.error('저장 실패')
    } finally {
      setBusySaving(false)
    }
  }

  // ── 실행 (instantiate + 자동 메시지 전송) ──
  const sendChatMessage = useChatStore((state) => state.sendMessage)
  const handleRun = async () => {
    if (!selectedTemplate) {
      toast.error('실행할 템플릿이 없습니다')
      return
    }
    if (draftDirty) {
      toast.warning('변경사항이 있어요. 먼저 저장하세요')
      return
    }
    setBusyRunning(true)
    try {
      const execution = await instantiateWorkflowTemplate(sessionId, selectedTemplate.templateId)
      toast.success(`"${selectedTemplate.name}" 작업 생성됨`)
      // 팀장 에이전트한테 시작 신호 — 이미 만들어진 자식 작업들을 명시해 위임 유도
      try {
        const children = execution.children.map((child) => {
          const templateNode = selectedTemplate.graph.nodes.find((n) => n.slotKey === child.slotKey)
          return {
            slotKey: child.slotKey,
            workId: child.workId,
            identifier: child.identifier,
            title: child.title,
            description: templateNode?.description ?? child.title,
            assigneeAgentId: child.assigneeAgentId,
            assigneeName:
              assignees.find((a) => a.id === child.assigneeAgentId)?.name ??
              DEFAULT_AGENT_CHOICES.find((c) => c.templateKey === templateNode?.templateKey)
                ?.name ??
              '에이전트',
          }
        })
        const trigger = buildWorkflowRunTrigger({
          templateName: selectedTemplate.name,
          templateDescription: selectedTemplate.description,
          children,
          edges: selectedTemplate.graph.edges,
        })
        const inputPayload = buildWorkflowRunInputPayload({
          templateId: selectedTemplate.templateId,
          templateName: selectedTemplate.name,
          rootWorkId: execution.rootWorkId,
          childWorkIds: execution.childWorkIds,
          childrenBySlotKey: execution.childrenBySlotKey,
          children,
        })
        await sendChatMessage({ sessionId, content: trigger, inputPayload })
        toast.success('팀장 에이전트에게 시작 신호 전송됨')
      } catch (chatError) {
        console.error('sendChatMessage failed', chatError)
        toast.warning('작업은 생성됐지만 채팅 메시지 실패. 채팅창에서 수동으로 시작하세요')
      }
    } catch (error) {
      console.error(error)
      toast.error('실행 실패')
    } finally {
      setBusyRunning(false)
    }
  }

  // ── 새 템플릿 ──
  const handleNewTemplate = () => {
    setSelectedTemplateId(null)
    setDraftNodes([])
    setDraftEdges([])
    setUserPositions({})
    setDraftDirty(false)
    setDraftName('')
    setDraftDescription('')
    setLeaderInitializing(true)
    setLeaderModalOpen(true)
  }

  // ── 템플릿 삭제 ──
  const handleDeleteTemplate = async (templateId: string) => {
    try {
      await deleteWorkflowTemplate(sessionId, templateId)
      setTemplates((prev) => prev.filter((t) => t.templateId !== templateId))
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(null)
      }
      toast.success('템플릿 삭제됨')
    } catch (error) {
      console.error(error)
      toast.error('삭제 실패')
    }
  }

  // ── 노드/엣지 만들기 ──
  const nodes = useMemo<FlowNode[]>(() => {
    const autoPos = computeAutoPositions()
    const list: FlowNode[] = [
      {
        id: CEO_NODE_ID,
        type: 'ceo',
        position: userPositions[CEO_NODE_ID] ?? { x: ceoX, y: ceoY },
        data: {
          label: draftName || '새 작업',
          onCardClick: () => {
            setLeaderInitializing(false)
            setLeaderModalOpen(true)
          },
        },
        draggable: true,
        style: { width: CEO_NODE_WIDTH },
        measured: { width: CEO_NODE_WIDTH, height: CEO_NODE_HEIGHT },
      },
      {
        id: START_BOX_NODE_ID,
        type: 'startBox',
        position: userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y },
        data: {
          label: inStartBox.size > 0 ? `${inStartBox.size}개 작업` : '비어있음',
        },
        draggable: true,
        style: { width: startBoxWidth, height: START_BOX_HEIGHT },
        measured: { width: startBoxWidth, height: START_BOX_HEIGHT },
      },
    ]
    for (const n of draftNodes) {
      const nodeId = `work:${n.slotKey}`
      const isInBox = inStartBox.has(n.slotKey)
      const userPos = userPositions[nodeId]
      const position = isInBox ? autoPos[nodeId] : (userPos ?? autoPos[nodeId])
      const isSource = connectingSourceSlot === n.slotKey
      const isValid =
        connectingSourceSlot !== null && !isSource && canConnect(connectingSourceSlot, n.slotKey)
      const isInvalid =
        connectingSourceSlot !== null && !isSource && !canConnect(connectingSourceSlot, n.slotKey)
      const agentName = resolveAgentName(n, assignees)
      const imageUrl = resolveAgentImage(n, assignees)
      list.push({
        id: nodeId,
        type: 'tplNode',
        position,
        data: {
          templateNode: n,
          agentName,
          imageUrl: imageUrl ?? undefined,
          onCardClick: () => handleCardClick(n.slotKey),
          isConnectingSource: isSource,
          isConnectingValidTarget: isValid,
          isConnectingInvalidTarget: isInvalid,
          inStartBox: isInBox,
        },
        draggable: true,
        measured: { width: 148, height: 130 },
      })
    }
    return list
  }, [
    assignees,
    canConnect,
    ceoX,
    ceoY,
    computeAutoPositions,
    connectingSourceSlot,
    draftName,
    draftNodes,
    handleCardClick,
    inStartBox,
    startBoxWidth,
    userPositions,
  ])

  const edges = useMemo<Edge[]>(
    () => [
      {
        id: 'ceo-to-startbox',
        source: CEO_NODE_ID,
        target: START_BOX_NODE_ID,
        type: 'straight',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#52525b',
          width: 28,
          height: 28,
        },
        style: { stroke: '#52525b', strokeWidth: 3 },
        selectable: false,
      },
      ...draftEdges.map((e) => ({
        id: `blocks:${e.sourceSlotKey}:${e.targetSlotKey}`,
        source: `work:${e.sourceSlotKey}`,
        target: `work:${e.targetSlotKey}`,
        type: 'blocks',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#71717a',
          width: 18,
          height: 18,
        },
        data: { sourceSlot: e.sourceSlotKey, targetSlot: e.targetSlotKey },
      })),
    ],
    [draftEdges],
  )

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[16rem_minmax(0,1fr)] overflow-hidden">
      {/* 좌측 — 템플릿 목록 */}
      <aside className="border-border bg-muted/30 flex min-h-0 flex-col border-r">
        <div className="border-border flex h-12 shrink-0 items-center justify-between border-b px-3">
          <span className="text-foreground text-sm font-semibold">내 워크플로우</span>
          <button
            type="button"
            onClick={handleNewTemplate}
            className="text-muted-foreground hover:text-foreground rounded-md p-1"
            title="새 작업"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            {templates.map((tpl) => (
              <div
                key={tpl.templateId}
                className={cn(
                  'group flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors',
                  selectedTemplate?.templateId === tpl.templateId
                    ? 'bg-background shadow-sm'
                    : 'hover:bg-background/60',
                )}
              >
                <button
                  type="button"
                  onClick={() => setSelectedTemplateId(tpl.templateId)}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="text-foreground block truncate text-[13px] font-medium">
                    {tpl.name}
                  </span>
                  <span className="text-muted-foreground mt-0.5 block truncate text-[10px]">
                    {tpl.graph.nodes.length}개 작업 · {tpl.graph.edges.length}개 순서
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteTemplate(tpl.templateId)}
                  className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-red-500"
                  title="삭제"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {templates.length === 0 && (
              <div className="text-muted-foreground p-3 text-xs">
                저장된 그림 없음. 캔버스에서 그리고 저장하세요.
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* 우측 캔버스 */}
      <main className="relative min-h-0 overflow-hidden">
        {templates.length === 0 && draftNodes.length === 0 && !draftName ? (
          <EmptyState
            onStart={() => {
              setLeaderInitializing(true)
              setDraftName('')
              setDraftDescription('')
              setLeaderModalOpen(true)
            }}
          />
        ) : (
          <CanvasArea
            connectingSourceSlot={connectingSourceSlot}
            edges={edges}
            nodes={nodes}
            onCancelConnecting={cancelConnecting}
            onEdgeClick={(s, t) => setEdgeToDelete({ source: s, target: t })}
            onNodesChange={handleNodesChange}
            onRequestAddAgent={openAddNode}
            onSaveExisting={() => void handleSaveExisting()}
            onSaveNew={() => void handleSaveNew()}
            onRun={() => void handleRun()}
            busySaving={busySaving}
            busyRunning={busyRunning}
            canSaveExisting={selectedTemplate !== null && draftDirty}
            canRun={selectedTemplate !== null && !draftDirty}
            hasDraft={draftNodes.length > 0}
            isNewTemplate={selectedTemplate === null}
            pointerPos={pointerPos}
            templateName={draftName || null}
          />
        )}
      </main>

      {composerOpen && (
        <NodeComposer
          agent={composerAgent}
          agentBusy={composerAgentBusy}
          agents={agentChoices}
          description={composerDescription}
          editing={editingSlot !== null}
          onCancel={closeComposer}
          onChangeAgent={() => setComposerAgent(null)}
          onChangeDescription={setComposerDescription}
          onChangeTitle={setComposerTitle}
          onSelectAgent={handleSelectAgent}
          onSubmit={submitComposer}
          title={composerTitle}
        />
      )}

      {actionSheetSlot !== null && (
        <CardActionSheet
          onCancel={() => setActionSheetSlot(null)}
          onEdit={() => {
            const slot = actionSheetSlot
            setActionSheetSlot(null)
            openEditNode(slot)
          }}
          onDelete={() => handleDeleteNode(actionSheetSlot)}
          onStartConnect={() => {
            setConnectingSourceSlot(actionSheetSlot)
            setActionSheetSlot(null)
          }}
        />
      )}

      {edgeToDelete !== null && (
        <EdgeDeleteSheet
          onCancel={() => setEdgeToDelete(null)}
          onConfirm={() => handleDeleteEdge(edgeToDelete.source, edgeToDelete.target)}
        />
      )}

      {leaderModalOpen && (
        <LeaderEditSheet
          initializing={leaderInitializing}
          name={draftName}
          description={draftDescription}
          onChangeName={(value) => {
            setDraftName(value)
            setDraftDirty(true)
          }}
          onChangeDescription={(value) => {
            setDraftDescription(value)
            setDraftDirty(true)
          }}
          onCancel={() => setLeaderModalOpen(false)}
          onConfirm={() => setLeaderModalOpen(false)}
        />
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 캔버스
// ──────────────────────────────────────────────────────────────────────────────
function CanvasArea({
  busyRunning,
  busySaving,
  canRun,
  canSaveExisting,
  connectingSourceSlot,
  edges,
  hasDraft,
  isNewTemplate,
  nodes,
  onCancelConnecting,
  onEdgeClick,
  onNodesChange,
  onRequestAddAgent,
  onRun,
  onSaveExisting,
  onSaveNew,
  pointerPos,
  templateName,
}: {
  busyRunning: boolean
  busySaving: boolean
  canRun: boolean
  canSaveExisting: boolean
  connectingSourceSlot: string | null
  edges: Edge[]
  hasDraft: boolean
  isNewTemplate: boolean
  nodes: FlowNode[]
  onCancelConnecting: () => void
  onEdgeClick: (sourceSlot: string, targetSlot: string) => void
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void
  onRequestAddAgent: () => void
  onRun: () => void
  onSaveExisting: () => void
  onSaveNew: () => void
  pointerPos: { x: number; y: number } | null
  templateName: string | null
}) {
  const rfInstance = useReactFlow()
  const [containerRect, setContainerRect] = useState<DOMRect | null>(null)
  const setContainerRef = useCallback((el: HTMLDivElement | null) => {
    if (el) setContainerRect(el.getBoundingClientRect())
  }, [])

  const ghostLine = useMemo(() => {
    if (connectingSourceSlot === null || pointerPos === null || containerRect === null) return null
    const sourceNode = rfInstance.getNode(`work:${connectingSourceSlot}`)
    if (!sourceNode) return null
    const center = {
      x: sourceNode.position.x + (sourceNode.measured?.width ?? 100) / 2,
      y: sourceNode.position.y + (sourceNode.measured?.height ?? 100) / 2,
    }
    const screen = rfInstance.flowToScreenPosition(center)
    const x1 = screen.x - containerRect.left
    const y1 = screen.y - containerRect.top
    const x2 = pointerPos.x - containerRect.left
    const y2 = pointerPos.y - containerRect.top
    return (
      <svg
        className="pointer-events-none absolute inset-0"
        style={{ width: '100%', height: '100%' }}
      >
        <defs>
          <marker
            id="ghost-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#71717a" />
          </marker>
        </defs>
        <line
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke="#71717a"
          strokeWidth={2}
          strokeDasharray="6 4"
          markerEnd="url(#ghost-arrow)"
          opacity={0.9}
        />
      </svg>
    )
  }, [connectingSourceSlot, containerRect, pointerPos, rfInstance])

  return (
    <div
      ref={setContainerRef}
      className="relative h-full w-full"
      style={{ ...CANVAS_BG_STYLE, '--xy-node-boxshadow-selected': 'none' } as CSSProperties}
    >
      <style>{`.react-flow__node { visibility: visible !important; }`}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={FLOW_NODE_TYPES}
        edgeTypes={FLOW_EDGE_TYPES}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        panOnDrag={[1, 2]}
        panOnScroll
        zoomOnScroll={false}
        zoomOnPinch
        zoomOnDoubleClick={false}
        preventScrolling={false}
        defaultViewport={{ x: 100, y: 30, zoom: 0.85 }}
        minZoom={0.4}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        onNodesChange={onNodesChange}
        onPaneClick={() => {
          if (connectingSourceSlot !== null) onCancelConnecting()
        }}
        onEdgeClick={(_event, edge) => {
          const data = edge.data as { sourceSlot?: string; targetSlot?: string } | undefined
          if (data?.sourceSlot && data?.targetSlot) {
            onEdgeClick(data.sourceSlot, data.targetSlot)
          }
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.8} color="#7d8290" />
      </ReactFlow>

      {ghostLine}

      {/* 상단 좌측 — 작업명 */}
      <div className="pointer-events-none absolute top-4 left-4 z-10 flex items-center gap-2">
        <div className="pointer-events-auto rounded-full border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-900 shadow-sm">
          <Workflow className="mr-1 inline h-3.5 w-3.5" />
          {isNewTemplate ? '새 작업' : (templateName ?? '작업')}
        </div>
      </div>

      {/* 우상단 — 저장 + 실행 */}
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        {isNewTemplate ? (
          <button
            type="button"
            onClick={onSaveNew}
            disabled={!hasDraft || busySaving}
            className="flex h-9 items-center gap-2 rounded-md bg-zinc-900 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-zinc-800 disabled:opacity-50"
          >
            {busySaving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            새로 저장
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onSaveExisting}
              disabled={!canSaveExisting || busySaving}
              className="flex h-9 items-center gap-2 rounded-md border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-900 shadow-sm transition-colors hover:bg-zinc-50 disabled:opacity-40"
            >
              {busySaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              저장
            </button>
            <button
              type="button"
              onClick={onRun}
              disabled={!canRun || busyRunning}
              className="flex h-9 items-center gap-2 rounded-md bg-zinc-900 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-zinc-800 disabled:opacity-40"
            >
              {busyRunning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              실행
            </button>
          </>
        )}
      </div>

      {connectingSourceSlot !== null && (
        <div className="pointer-events-none absolute inset-x-0 top-20 z-20 flex justify-center">
          <div className="border-border bg-background text-foreground pointer-events-auto flex items-center gap-3 rounded-md border px-4 py-2 text-sm shadow">
            <Zap className="text-foreground/60 h-4 w-4" />
            <span>
              <span className="font-semibold">잇기 모드</span> · 다음 작업 클릭
            </span>
            <button
              type="button"
              onClick={onCancelConnecting}
              className="text-muted-foreground hover:text-foreground rounded px-2 py-0.5 text-xs"
            >
              취소 (ESC)
            </button>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={onRequestAddAgent}
        className="bg-foreground text-background hover:bg-foreground/90 absolute right-6 bottom-6 z-10 flex h-12 w-12 items-center justify-center rounded-full shadow-lg transition-transform hover:scale-105"
        aria-label="작업 추가"
      >
        <Plus className="h-6 w-6" />
      </button>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 노드 (CEO / 박스 / 작업)
// ──────────────────────────────────────────────────────────────────────────────
function CeoFlowNode({ data }: NodeProps<FlowNode>) {
  const label = typeof data.label === 'string' ? data.label : '새 작업'
  const onCardClick = (data.onCardClick as () => void) ?? (() => undefined)
  const [downPos, setDownPos] = useState<{ x: number; y: number } | null>(null)
  return (
    <div className="relative" style={{ width: CEO_NODE_WIDTH }}>
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="!h-1 !w-1 !border-0 !bg-transparent"
      />
      <div
        onPointerDown={(event) => setDownPos({ x: event.clientX, y: event.clientY })}
        onPointerUp={(event) => {
          if (!downPos) return
          const dx = event.clientX - downPos.x
          const dy = event.clientY - downPos.y
          setDownPos(null)
          if (Math.sqrt(dx * dx + dy * dy) < 5) onCardClick()
        }}
        className="flex cursor-pointer items-center gap-3 rounded-xl border-2 border-zinc-800 bg-white px-4 py-3 shadow-md transition-all hover:shadow-lg"
      >
        <div className="h-14 w-14 shrink-0 overflow-hidden rounded-full bg-zinc-100 ring-2 ring-amber-500">
          <img
            src={CEO_PROFILE_IMAGE}
            alt=""
            className="h-full w-full object-cover"
            draggable={false}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-bold tracking-wider text-amber-700 uppercase">
            팀장 에이전트
          </div>
          <div className="truncate text-sm font-semibold text-zinc-900">{label}</div>
        </div>
      </div>
    </div>
  )
}

function StartBoxFlowNode({ data }: NodeProps<FlowNode>) {
  const label = typeof data.label === 'string' ? data.label : '비어있음'
  return (
    <div className="group/box relative h-full w-full">
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={false}
        className="!h-1 !w-1 !border-0 !bg-transparent"
        style={{ top: -24 }}
      />
      <div className="pointer-events-auto h-full w-full rounded-xl border-2 border-dashed border-zinc-700 bg-transparent transition-colors hover:border-zinc-900">
        <div className="pointer-events-none absolute -top-3 left-4 flex items-center gap-1.5 rounded-full border border-zinc-700 bg-white px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-zinc-800 uppercase shadow-sm">
          <Zap className="h-3 w-3" />
          시작 그룹 · {label}
        </div>
      </div>
    </div>
  )
}

function TemplateFlowNode({ data }: NodeProps<FlowNode>) {
  const node = data.templateNode as ApiTplNode | undefined
  if (!node) return null
  const imageUrl = typeof data.imageUrl === 'string' ? data.imageUrl : undefined
  const agentName = typeof data.agentName === 'string' ? data.agentName : ''
  const onCardClick = (data.onCardClick as () => void) ?? (() => undefined)
  const isSource = data.isConnectingSource === true
  const isValid = data.isConnectingValidTarget === true
  const isInvalid = data.isConnectingInvalidTarget === true
  return (
    <div className="relative">
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="!h-1 !w-1 !border-0 !bg-transparent"
      />
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={false}
        className="!h-1 !w-1 !border-0 !bg-transparent"
      />
      <div
        onClick={onCardClick}
        className={cn(
          'group bg-card border-border relative flex w-[148px] cursor-pointer flex-col items-center gap-2 rounded-xl border p-3 shadow-sm transition-colors',
          'hover:border-foreground/40',
          isSource && '!border-foreground ring-foreground/30 ring-2',
          isValid && '!border-emerald-500 ring-2 ring-emerald-500/40',
          isInvalid && '!border-red-500/70 opacity-70 ring-2 ring-red-500/70',
        )}
      >
        <div className="relative">
          <div className="bg-muted ring-border h-14 w-14 overflow-hidden rounded-full shadow-lg ring-2">
            {imageUrl ? (
              <img src={imageUrl} alt="" className="h-full w-full object-cover" draggable={false} />
            ) : (
              <div className="text-foreground/80 flex h-full w-full items-center justify-center text-base font-semibold">
                {agentName.charAt(0).toUpperCase() || '?'}
              </div>
            )}
          </div>
        </div>
        <div className="w-full text-center">
          <div className="text-foreground line-clamp-2 text-[12px] leading-tight font-semibold">
            {node.title}
          </div>
          <div className="text-muted-foreground mt-1 truncate text-[10px]">{agentName}</div>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 엣지 (floating)
// ──────────────────────────────────────────────────────────────────────────────
function BlocksEdge({ id, source, target, markerEnd }: EdgeProps) {
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)
  if (!sourceNode || !targetNode) return null
  const { sx, sy, tx, ty } = computeFloatingEdgePoints(sourceNode, targetNode)
  const path = `M ${sx} ${sy} L ${tx} ${ty}`
  return (
    <g className="group/edge">
      <path
        d={path}
        stroke="transparent"
        strokeWidth={20}
        fill="none"
        style={{ cursor: 'pointer' }}
      />
      <path
        id={id}
        d={path}
        stroke="#71717a"
        strokeWidth={2}
        fill="none"
        markerEnd={markerEnd}
        className="transition-all group-hover/edge:!stroke-[#27272a] group-hover/edge:[stroke-width:3]"
      />
    </g>
  )
}

function computeFloatingEdgePoints(source: InternalNode, target: InternalNode) {
  const sw = source.measured?.width ?? 148
  const sh = source.measured?.height ?? 130
  const tw = target.measured?.width ?? 148
  const th = target.measured?.height ?? 130
  const sx0 = (source.internals?.positionAbsolute?.x ?? source.position.x) + sw / 2
  const sy0 = (source.internals?.positionAbsolute?.y ?? source.position.y) + sh / 2
  const tx0 = (target.internals?.positionAbsolute?.x ?? target.position.x) + tw / 2
  const ty0 = (target.internals?.positionAbsolute?.y ?? target.position.y) + th / 2
  return {
    sx: intersectBorderX(sx0, sy0, tx0, ty0, sw, sh),
    sy: intersectBorderY(sx0, sy0, tx0, ty0, sw, sh),
    tx: intersectBorderX(tx0, ty0, sx0, sy0, tw, th),
    ty: intersectBorderY(tx0, ty0, sx0, sy0, tw, th),
  }
}

function intersectBorderX(cx: number, cy: number, ox: number, oy: number, w: number, h: number) {
  const dx = ox - cx
  const dy = oy - cy
  const hw = w / 2
  const hh = h / 2
  if (dx === 0 && dy === 0) return cx
  const tx = dx === 0 ? Infinity : hw / Math.abs(dx)
  const ty = dy === 0 ? Infinity : hh / Math.abs(dy)
  const t = Math.min(tx, ty)
  return cx + dx * t
}

function intersectBorderY(cx: number, cy: number, ox: number, oy: number, w: number, h: number) {
  const dx = ox - cx
  const dy = oy - cy
  const hw = w / 2
  const hh = h / 2
  if (dx === 0 && dy === 0) return cy
  const tx = dx === 0 ? Infinity : hw / Math.abs(dx)
  const ty = dy === 0 ? Infinity : hh / Math.abs(dy)
  const t = Math.min(tx, ty)
  return cy + dy * t
}

// ──────────────────────────────────────────────────────────────────────────────
// 모달들
// ──────────────────────────────────────────────────────────────────────────────
function EmptyState({ onStart }: { onStart: () => void }) {
  return (
    <div className="relative h-full w-full" style={CANVAS_BG_STYLE}>
      <div className="flex h-full w-full flex-col items-center justify-center gap-5 px-6">
        <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-zinc-500 bg-zinc-200 shadow-sm">
          <Workflow className="h-7 w-7 text-zinc-700" />
        </div>
        <div className="max-w-md text-center">
          <div className="text-lg font-bold text-zinc-900">저장된 워크플로우가 없어요</div>
          <p className="mt-2 text-sm leading-6 text-zinc-700">
            팀장 에이전트가 처리할 작업을 만들어보세요.
            <br />
            작업과 순서를 한 번 정의해두면, 같은 흐름으로 여러 번 실행할 수 있어요.
          </p>
        </div>
        <button
          type="button"
          onClick={onStart}
          className="mt-1 flex items-center gap-2 rounded-md bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-zinc-800"
        >
          <Plus className="h-4 w-4" />새 워크플로우 만들기
        </button>
      </div>
    </div>
  )
}

function CardActionSheet({
  onCancel,
  onDelete,
  onEdit,
  onStartConnect,
}: {
  onCancel: () => void
  onDelete: () => void
  onEdit: () => void
  onStartConnect: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="border-border bg-popover text-popover-foreground w-[280px] max-w-full overflow-hidden rounded-xl border shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="p-2">
          <button
            type="button"
            onClick={onEdit}
            className="text-foreground hover:bg-accent flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-colors"
          >
            <Pencil className="text-muted-foreground h-4 w-4" />
            수정
          </button>
          <button
            type="button"
            onClick={onStartConnect}
            className="text-foreground hover:bg-accent flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-colors"
          >
            <Zap className="h-4 w-4 text-violet-300" />
            다음 작업으로 잇기
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-red-300 transition-colors hover:bg-red-500/10"
          >
            <Trash2 className="h-4 w-4" />
            삭제
          </button>
        </div>
        <div className="border-border border-t p-2">
          <button
            type="button"
            onClick={onCancel}
            className="text-muted-foreground hover:bg-muted hover:text-foreground w-full rounded-xl px-3 py-2 text-sm transition-colors"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}

function EdgeDeleteSheet({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="border-border bg-popover text-popover-foreground w-[320px] max-w-full overflow-hidden rounded-xl border shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="p-5 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/20">
            <Trash2 className="h-6 w-6 text-red-400" />
          </div>
          <div className="text-foreground text-base font-semibold">화살표를 삭제할까요?</div>
          <div className="text-muted-foreground mt-1 text-xs">작업 순서 관계가 해제됩니다.</div>
        </div>
        <div className="border-border grid grid-cols-2 gap-2 border-t p-3">
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-xl bg-red-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
          >
            삭제
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="text-foreground/80 hover:bg-accent hover:text-foreground rounded-xl px-3 py-2 text-sm font-medium transition-colors"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}

function LeaderEditSheet({
  description,
  initializing,
  name,
  onCancel,
  onChangeDescription,
  onChangeName,
  onConfirm,
}: {
  description: string
  initializing: boolean
  name: string
  onCancel: () => void
  onChangeDescription: (value: string) => void
  onChangeName: (value: string) => void
  onConfirm: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="border-border bg-popover text-popover-foreground w-[480px] max-w-full overflow-hidden rounded-xl border shadow-lg">
        <div className="border-border flex items-center gap-3 border-b px-5 py-3">
          <div className="bg-muted ring-border h-10 w-10 shrink-0 overflow-hidden rounded-full ring-2">
            <img
              src={CEO_PROFILE_IMAGE}
              alt=""
              className="h-full w-full object-cover"
              draggable={false}
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-foreground/70 text-[10px] font-semibold tracking-wider uppercase">
              팀장 에이전트
            </div>
            <div className="text-foreground text-base font-semibold">
              {initializing ? '새 작업 만들기' : '작업 정보 수정'}
            </div>
          </div>
        </div>

        <div className="space-y-4 p-5">
          <div>
            <label className="text-muted-foreground mb-2 block text-[11px] font-semibold tracking-wider uppercase">
              작업명
            </label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(event) => onChangeName(event.target.value)}
              placeholder="예: 분기 보고서 만들기"
              className="border-border bg-muted text-foreground placeholder:text-muted-foreground/70 focus-visible:ring-foreground/30 h-10 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-2"
            />
          </div>
          <div>
            <label className="text-muted-foreground mb-2 block text-[11px] font-semibold tracking-wider uppercase">
              팀장 지시사항
            </label>
            <Textarea
              value={description}
              onChange={(event) => onChangeDescription(event.target.value)}
              placeholder="팀장 에이전트가 받을 전반 지시. 자식 작업들의 맥락과 최종 결과물을 설명하세요."
              className="border-border bg-muted text-foreground placeholder:text-muted-foreground/70 min-h-32 resize-y rounded-lg"
            />
            <p className="text-muted-foreground mt-1.5 text-[11px]">
              실행 시 팀장 에이전트가 이 지시를 받고, 자식 작업들을 위임/종합합니다.
            </p>
          </div>
        </div>

        <div className="border-border flex justify-end gap-2 border-t px-5 py-3">
          <Button type="button" size="sm" onClick={onConfirm} disabled={!name.trim()}>
            {initializing ? '워크플로우 시작' : '확인'}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            취소
          </Button>
        </div>
      </div>
    </div>
  )
}

function NodeComposer({
  agent,
  agentBusy,
  agents,
  description,
  editing,
  onCancel,
  onChangeAgent,
  onChangeDescription,
  onChangeTitle,
  onSelectAgent,
  onSubmit,
  title,
}: {
  agent: AgentChoice | null
  agentBusy: boolean
  agents: AgentChoice[]
  description: string
  editing: boolean
  onCancel: () => void
  onChangeAgent: () => void
  onChangeDescription: (value: string) => void
  onChangeTitle: (value: string) => void
  onSelectAgent: (agent: AgentChoice) => void | Promise<void>
  onSubmit: () => void
  title: string
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="border-border bg-popover text-popover-foreground w-[460px] max-w-full overflow-hidden rounded-xl border shadow-lg">
        <div className="border-border flex items-center justify-between border-b px-5 py-3">
          <h3 className="text-foreground text-base font-semibold">
            {editing ? '작업 수정' : '새 작업'}
          </h3>
          <button
            type="button"
            onClick={onCancel}
            className="text-muted-foreground hover:bg-accent hover:text-foreground flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div>
            <label className="text-muted-foreground mb-2 block text-[11px] font-semibold tracking-wider uppercase">
              에이전트
            </label>
            {agent ? (
              <div className="border-border bg-muted flex items-center gap-3 rounded-xl border px-3 py-2.5">
                <div className="bg-muted ring-border h-10 w-10 shrink-0 overflow-hidden rounded-full ring-2">
                  {agent.imageUrl ? (
                    <img src={agent.imageUrl} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="text-foreground/80 flex h-full w-full items-center justify-center text-sm">
                      {agent.name.charAt(0).toUpperCase() || '?'}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-foreground truncate text-sm font-medium">{agent.name}</div>
                </div>
                <Button type="button" variant="ghost" size="sm" onClick={onChangeAgent}>
                  변경
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {agents.map((choice) => (
                  <button
                    key={choice.id}
                    type="button"
                    disabled={agentBusy}
                    onClick={() => void onSelectAgent(choice)}
                    className="border-border bg-muted hover:bg-accent flex flex-col items-center gap-2 rounded-xl border p-3 transition-colors hover:border-white/30 disabled:opacity-50"
                  >
                    <div className="bg-muted ring-border h-11 w-11 overflow-hidden rounded-full ring-2">
                      {choice.imageUrl ? (
                        <img src={choice.imageUrl} alt="" className="h-full w-full object-cover" />
                      ) : (
                        <div className="text-foreground/80 flex h-full w-full items-center justify-center text-sm">
                          {choice.name.charAt(0).toUpperCase() || '?'}
                        </div>
                      )}
                    </div>
                    <span className="text-foreground line-clamp-1 max-w-full text-[11px] font-medium">
                      {choice.name}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {agent && (
            <>
              <div>
                <label className="text-muted-foreground mb-2 block text-[11px] font-semibold tracking-wider uppercase">
                  작업 제목
                </label>
                <input
                  autoFocus
                  type="text"
                  value={title}
                  onChange={(event) => onChangeTitle(event.target.value)}
                  placeholder="예: 매출 데이터 수집"
                  className="border-border bg-muted text-foreground placeholder:text-muted-foreground/70 h-10 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-violet-400/40"
                />
              </div>
              <div>
                <label className="text-muted-foreground mb-2 block text-[11px] font-semibold tracking-wider uppercase">
                  세부사항
                </label>
                <Textarea
                  value={description}
                  onChange={(event) => onChangeDescription(event.target.value)}
                  placeholder="에이전트에게 전달할 지시사항"
                  className="border-border bg-muted text-foreground placeholder:text-muted-foreground/70 min-h-24 resize-y rounded-lg"
                />
              </div>
            </>
          )}
        </div>

        <div className="border-border flex justify-end gap-2 border-t px-5 py-3">
          <Button
            type="button"
            size="sm"
            onClick={onSubmit}
            disabled={!agent || !title.trim() || agentBusy}
          >
            {editing ? '수정' : '추가'}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            취소
          </Button>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 헬퍼
// ──────────────────────────────────────────────────────────────────────────────
function resolveAgentName(node: ApiTplNode, assignees: BoardAssignee[]): string {
  if (node.assigneeAgentId) {
    const found = assignees.find((a) => a.id === node.assigneeAgentId)
    if (found) return found.name
  }
  if (node.templateKey) {
    const tmpl = DEFAULT_AGENT_CHOICES.find((c) => c.templateKey === node.templateKey)
    if (tmpl) return tmpl.name
  }
  return '에이전트'
}

function resolveAgentImage(node: ApiTplNode, assignees: BoardAssignee[]): string | null {
  if (node.assigneeAgentId) {
    const found = assignees.find((a) => a.id === node.assigneeAgentId)
    if (found?.imageUrl) return found.imageUrl
  }
  return null
}

const DEFAULT_AGENT_CHOICES: AgentChoice[] = [
  {
    id: 'provided-default',
    name: '기본 에이전트',
    defaultTitle: '보조 작업',
    assigneeAgentId: null,
    provided: true,
    templateKey: 'default',
  },
  {
    id: 'provided-coder',
    name: '개발 에이전트',
    defaultTitle: '개발 작업',
    assigneeAgentId: null,
    provided: true,
    templateKey: 'coder',
  },
  {
    id: 'provided-qa',
    name: 'QA 에이전트',
    defaultTitle: '검증 작업',
    assigneeAgentId: null,
    provided: true,
    templateKey: 'qa',
  },
  {
    id: 'provided-ux-designer',
    name: 'UX 디자이너',
    defaultTitle: 'UX 검토',
    assigneeAgentId: null,
    provided: true,
    templateKey: 'ux_designer',
  },
  {
    id: 'provided-security',
    name: '보안 에이전트',
    defaultTitle: '보안 검토',
    assigneeAgentId: null,
    provided: true,
    templateKey: 'security_engineer',
  },
]
