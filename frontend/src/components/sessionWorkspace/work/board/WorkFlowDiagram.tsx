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
import { CheckCircle2, Circle, Info, Loader2, Plus, Save, Trash2, X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/components/ui/utils'
import type { IssueBoardIssue } from '../model/issueBoardModel'
import type { BoardAssignee } from './issueBoardPanelTypes'
import { assigneeImageUrl, assigneeLabel } from './issueBoardPanelUtils'

type CreateWorkInput = {
  assigneeAgentId: string | null
  description: string
  title: string
}

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
  assigneeImageUrl?: string
  assigneeName?: string
  issue?: IssueBoardIssue
  label?: string
  onCardClick?: () => void
  isConnectingSource?: boolean
  isConnectingValidTarget?: boolean
  isConnectingInvalidTarget?: boolean
  inStartBox?: boolean
}

type FlowNode = Node<FlowNodeData>

const FLOW_NODE_TYPES = { work: WorkFlowNode, ceo: CeoFlowNode, startBox: StartBoxFlowNode }
const FLOW_EDGE_TYPES = { blocks: BlocksEdge }

const CEO_NODE_ID = 'ceo'
const START_BOX_NODE_ID = 'start-box'

const BG_GRADIENT =
  'radial-gradient(1200px 600px at 30% 0%, rgba(99, 102, 241, 0.18), transparent 60%), radial-gradient(1000px 500px at 80% 100%, rgba(168, 85, 247, 0.18), transparent 55%), linear-gradient(180deg, #0b0f1d 0%, #14102c 100%)'

// 팀장 노드 (캔버스 좌표)
const CEO_NODE_WIDTH = 240
const CEO_NODE_HEIGHT = 70
// 시작 박스 영역 — 자식 수에 따라 width 자동 계산
const START_BOX_X = 80
const START_BOX_Y = 220
const START_BOX_HEIGHT = 220
const START_BOX_MIN_WIDTH = 240
// 박스 안 노드 자동 정렬
const START_NODE_GAP = 160
const START_NODE_OFFSET_X = 60
const START_NODE_OFFSET_Y = 40
const START_NODE_WIDTH = 148 // 카드 width
// 박스 밖 노드 자동 정렬 (박스 아래)
const OUTSIDE_START_X = 120
const OUTSIDE_START_Y = 560
const OUTSIDE_STEP_X = 200
const OUTSIDE_STEP_Y = 250

export function WorkFlowDiagram(props: {
  assignees: BoardAssignee[]
  issues: IssueBoardIssue[]
  onAddRelation: (sourceId: string, targetId: string) => void
  onRemoveRelation?: (sourceId: string, targetId: string) => void
  onCreateChildWork: (parentId: string, input: CreateWorkInput) => void
  onCreateRootWork: (input: CreateWorkInput) => void
  onEnsureDefaultAgents: () => Promise<BoardAssignee[]>
  onOpenIssue: (issueId: string) => void
  onReorderChildWork: (parentId: string, workIds: string[]) => void
}) {
  return (
    <ReactFlowProvider>
      <WorkFlowDiagramInner {...props} />
    </ReactFlowProvider>
  )
}

function WorkFlowDiagramInner({
  assignees,
  issues,
  onAddRelation,
  onRemoveRelation,
  onCreateChildWork,
  onCreateRootWork,
  onEnsureDefaultAgents,
  onOpenIssue,
}: {
  assignees: BoardAssignee[]
  issues: IssueBoardIssue[]
  onAddRelation: (sourceId: string, targetId: string) => void
  onRemoveRelation?: (sourceId: string, targetId: string) => void
  onCreateChildWork: (parentId: string, input: CreateWorkInput) => void
  onCreateRootWork: (input: CreateWorkInput) => void
  onEnsureDefaultAgents: () => Promise<BoardAssignee[]>
  onOpenIssue: (issueId: string) => void
  onReorderChildWork: (parentId: string, workIds: string[]) => void
}) {
  const rootIssues = useMemo(
    () => sortFlowIssues(issues.filter((issue) => !issue.parentId)),
    [issues],
  )
  const [selectedRootId, setSelectedRootId] = useState<string | null>(rootIssues[0]?.id ?? null)
  const selectedRoot =
    rootIssues.find((issue) => issue.id === selectedRootId) ?? rootIssues[0] ?? null
  const childIssues = useMemo(
    () =>
      sortFlowIssues(issues.filter((issue) => selectedRoot && issue.parentId === selectedRoot.id)),
    [issues, selectedRoot],
  )

  // 사용자가 직접 드래그한 위치
  const [userPositions, setUserPositions] = useState<Record<string, { x: number; y: number }>>({})

  // 박스 안/밖 = 사용자 의도 (드래그 위치) 기반
  // - 사용자 위치 없음 + indegree=0 → 박스 안
  // - 사용자 위치 박스 영역 안 → 박스 안
  // - 사용자 위치 박스 영역 밖 → 박스 밖 (미배치)
  // - indegree>0 → 무조건 박스 밖
  // 박스 width 는 항상 indegree=0 인 노드 수 + 사용자가 빼지 않은 것 기준
  // 우선 indegree 기반 후보부터 만들고, 사용자 위치 검사는 아래에서

  // 박스 영역 내 판정
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

  // 박스 안에 들어있는 자식들 (indegree=0 + 사용자가 박스 밖으로 빼지 않은 것)
  const { inStartBox, outsideOrder } = useMemo(() => {
    const boxPos = userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y }
    // 임시 박스 width — 전체 indegree=0 갯수 기준
    const tentativeCount = childIssues.filter((i) => i.blockedBy.length === 0).length
    const tentativeWidth = Math.max(
      START_BOX_MIN_WIDTH,
      START_NODE_OFFSET_X * 2 +
        Math.max(1, tentativeCount) * START_NODE_WIDTH +
        Math.max(0, tentativeCount - 1) * (START_NODE_GAP - START_NODE_WIDTH),
    )

    const inBox = new Set<string>()
    const outside: string[] = []
    for (const issue of childIssues) {
      const nodeId = `work:${issue.id}`
      const userPos = userPositions[nodeId]
      if (issue.blockedBy.length > 0) {
        outside.push(issue.id)
        continue
      }
      // indegree=0 — 사용자 위치 없으면 박스 안, 있으면 박스 영역 안에 있는지 확인
      if (userPos === undefined) {
        inBox.add(issue.id)
      } else if (isPosInsideBox(userPos, boxPos, tentativeWidth)) {
        inBox.add(issue.id)
      } else {
        outside.push(issue.id) // 박스 밖 = 미배치
      }
    }
    return { inStartBox: inBox, outsideOrder: outside }
  }, [childIssues, isPosInsideBox, userPositions])

  // 박스 width — 실제 박스 안에 있는 노드 수 기준
  const startBoxWidth = useMemo(() => {
    const count = Math.max(1, inStartBox.size)
    const needed =
      START_NODE_OFFSET_X * 2 +
      count * START_NODE_WIDTH +
      Math.max(0, count - 1) * (START_NODE_GAP - START_NODE_WIDTH)
    return Math.max(START_BOX_MIN_WIDTH, needed)
  }, [inStartBox])

  // 팀장 X = 박스 가로 중앙
  const ceoX = useMemo(() => START_BOX_X + startBoxWidth / 2 - CEO_NODE_WIDTH / 2, [startBoxWidth])
  const ceoY = 20

  // 박스 안 노드들의 자동 위치
  const computeAutoPositions = useCallback((): Record<string, { x: number; y: number }> => {
    const positions: Record<string, { x: number; y: number }> = {}
    const boxPos = userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y }
    let boxIndex = 0
    for (const issue of childIssues) {
      const nodeId = `work:${issue.id}`
      if (inStartBox.has(issue.id)) {
        positions[nodeId] = {
          x: boxPos.x + START_NODE_OFFSET_X + boxIndex * START_NODE_GAP,
          y: boxPos.y + START_NODE_OFFSET_Y,
        }
        boxIndex++
      }
    }
    outsideOrder.forEach((issueId, index) => {
      const nodeId = `work:${issueId}`
      const col = index % 4
      const row = Math.floor(index / 4)
      positions[nodeId] = {
        x: OUTSIDE_START_X + col * OUTSIDE_STEP_X,
        y: OUTSIDE_START_Y + row * OUTSIDE_STEP_Y,
      }
    })
    return positions
  }, [childIssues, inStartBox, outsideOrder, userPositions])

  // 모달
  const [composerOpen, setComposerOpen] = useState(false)
  const [composerParentId, setComposerParentId] = useState<string | null>(null)
  const [composerAgent, setComposerAgent] = useState<AgentChoice | null>(null)
  const [composerTitle, setComposerTitle] = useState('')
  const [composerDescription, setComposerDescription] = useState('')
  const [composerAgentBusy, setComposerAgentBusy] = useState(false)

  // 잇기 상태
  const [connectingSourceId, setConnectingSourceId] = useState<string | null>(null)
  const [pointerPos, setPointerPos] = useState<{ x: number; y: number } | null>(null)
  // 카드 액션 시트
  const [actionSheetIssueId, setActionSheetIssueId] = useState<string | null>(null)
  // 화살표 삭제 확인
  const [edgeToDelete, setEdgeToDelete] = useState<{ source: string; target: string } | null>(null)
  // 엣지 삭제 중인지 표시 (로딩)
  const [deletingEdge, setDeletingEdge] = useState(false)

  // 삭제 중인 엣지가 백엔드에서 진짜 사라지면 모달 닫음
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!deletingEdge || !edgeToDelete) return
    const target = childIssues.find((i) => i.id === edgeToDelete.target)
    const stillExists = target?.blockedBy.some((b) => b.id === edgeToDelete.source) ?? false
    if (!stillExists) {
      setDeletingEdge(false)
      setEdgeToDelete(null)
    }
  }, [childIssues, deletingEdge, edgeToDelete])
  /* eslint-enable react-hooks/set-state-in-effect */

  // 안전망 — 3초 안 응답 없으면 자동 닫기
  useEffect(() => {
    if (!deletingEdge) return
    const id = setTimeout(() => {
      setDeletingEdge(false)
      setEdgeToDelete(null)
    }, 3000)
    return () => clearTimeout(id)
  }, [deletingEdge])

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

  // ── 사이클/중복/박스 가드 ──
  const wouldCreateCycle = useCallback(
    (sourceId: string, targetId: string): boolean => {
      const adj = new Map<string, string[]>()
      for (const issue of childIssues) adj.set(issue.id, [])
      for (const issue of childIssues) {
        for (const blocker of issue.blockedBy) adj.get(blocker.id)?.push(issue.id)
      }
      const seen = new Set<string>()
      const queue = [targetId]
      while (queue.length > 0) {
        const cur = queue.shift() as string
        if (cur === sourceId) return true
        if (seen.has(cur)) continue
        seen.add(cur)
        for (const n of adj.get(cur) ?? []) if (!seen.has(n)) queue.push(n)
      }
      return false
    },
    [childIssues],
  )

  const relationExists = useCallback(
    (sourceId: string, targetId: string): boolean => {
      const target = childIssues.find((issue) => issue.id === targetId)
      if (!target) return false
      return target.blockedBy.some((blocker) => blocker.id === sourceId)
    },
    [childIssues],
  )

  const canConnect = useCallback(
    (sourceId: string, targetId: string): boolean => {
      if (sourceId === targetId) return false
      // 박스 안끼리는 못 이음 (병렬 그룹이라 의미 없음)
      if (inStartBox.has(sourceId) && inStartBox.has(targetId)) return false
      if (relationExists(sourceId, targetId)) return false
      if (wouldCreateCycle(sourceId, targetId)) return false
      return true
    },
    [inStartBox, relationExists, wouldCreateCycle],
  )

  // ── 잇기 모드 — 마우스 따라오는 점선 ──
  useEffect(() => {
    if (connectingSourceId === null) return
    const handleMove = (event: MouseEvent) => {
      setPointerPos({ x: event.clientX, y: event.clientY })
    }
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setConnectingSourceId(null)
        setPointerPos(null)
      }
    }
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('keydown', handleEsc)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('keydown', handleEsc)
    }
  }, [connectingSourceId])

  // 박스 안/밖 분류는 nodes useMemo 안에서 inStartBox 확인 후 자동 위치 우선 적용함.
  // userPositions 는 박스 밖 노드일 때만 사용 — 별도 청소 불필요.

  // 카드 클릭
  const handleCardClick = useCallback(
    (issueId: string) => {
      if (connectingSourceId !== null) {
        if (canConnect(connectingSourceId, issueId)) {
          onAddRelation(connectingSourceId, issueId)
        }
        setConnectingSourceId(null)
        setPointerPos(null)
        return
      }
      setActionSheetIssueId(issueId)
    },
    [canConnect, connectingSourceId, onAddRelation],
  )

  const cancelConnecting = useCallback(() => {
    setConnectingSourceId(null)
    setPointerPos(null)
  }, [])

  // 저장 — 박스 밖 + indegree=0 (미배치) 인 노드들 위치 캐시 지움 → 박스로 자동 복귀
  const handleSave = useCallback(() => {
    setUserPositions((prev) => {
      const next = { ...prev }
      for (const issue of childIssues) {
        if (issue.blockedBy.length === 0) {
          // indegree=0 → 박스 안으로 복귀
          delete next[`work:${issue.id}`]
        }
      }
      return next
    })
  }, [childIssues])

  // 노드 변경 (드래그 실시간) — 박스 밖 노드만 위치 저장
  const handleNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      setUserPositions((prev) => {
        const next = { ...prev }
        for (const change of changes) {
          if (change.type === 'position' && change.position) {
            // 박스가 이동하면 박스 안 노드들의 캐시는 지움 → 자동 정렬로 박스 따라가게
            if (change.id === START_BOX_NODE_ID) {
              next[change.id] = { x: change.position.x, y: change.position.y }
              for (const issueId of inStartBox) {
                delete next[`work:${issueId}`]
              }
              continue
            }
            // 그 외 (팀장 / 자식) — 사용자 위치 그대로 저장
            next[change.id] = { x: change.position.x, y: change.position.y }
          }
        }
        return next
      })
    },
    [inStartBox],
  )

  // ── 모달 ──
  const openComposerForChild = () => {
    if (!selectedRoot) return
    setComposerParentId(selectedRoot.id)
    setComposerAgent(null)
    setComposerTitle('')
    setComposerDescription('')
    setComposerOpen(true)
  }

  const openComposerForRoot = () => {
    setComposerParentId(null)
    setComposerAgent({
      id: 'CEO',
      name: '팀장 에이전트',
      defaultTitle: '새 작업',
      assigneeAgentId: null,
      imageUrl: CEO_PROFILE_IMAGE,
    })
    setComposerTitle('')
    setComposerDescription('')
    setComposerOpen(true)
  }

  const closeComposer = () => {
    setComposerOpen(false)
    setComposerAgent(null)
    setComposerTitle('')
    setComposerDescription('')
  }

  const handleSelectAgent = async (agent: AgentChoice) => {
    if (agent.provided && agent.templateKey) {
      setComposerAgentBusy(true)
      try {
        const next = await onEnsureDefaultAgents()
        const matched = next.find((assignee) => assignee.templateKey === agent.templateKey) ?? null
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
    const payload = {
      assigneeAgentId: composerAgent.assigneeAgentId,
      title,
      description,
    }
    if (composerParentId === null) onCreateRootWork(payload)
    else onCreateChildWork(composerParentId, payload)
    closeComposer()
  }

  // 노드 — 팀장 + 시작 박스 + 자식들
  const nodes = useMemo<FlowNode[]>(() => {
    const autoPos = computeAutoPositions()
    const list: FlowNode[] = [
      // 팀장 노드 (드래그 + 클릭 가능)
      {
        id: CEO_NODE_ID,
        type: 'ceo',
        position: userPositions[CEO_NODE_ID] ?? { x: ceoX, y: ceoY },
        data: {
          issue: selectedRoot ?? undefined,
          onCardClick: () => selectedRoot && handleCardClick(selectedRoot.id),
        },
        draggable: true,
        style: { width: CEO_NODE_WIDTH },
        measured: { width: CEO_NODE_WIDTH, height: CEO_NODE_HEIGHT },
      },
      // 시작 박스 (배경 노드, 자식 수에 따라 width 자동)
      {
        id: START_BOX_NODE_ID,
        type: 'startBox',
        position: userPositions[START_BOX_NODE_ID] ?? { x: START_BOX_X, y: START_BOX_Y },
        data: {
          label: inStartBox.size > 0 ? `${inStartBox.size}개 동시 시작` : '병렬 시작 그룹',
        },
        draggable: true,
        style: { width: startBoxWidth, height: START_BOX_HEIGHT },
        measured: { width: startBoxWidth, height: START_BOX_HEIGHT },
      },
    ]
    for (const issue of childIssues) {
      const nodeId = `work:${issue.id}`
      const isInBox = inStartBox.has(issue.id)
      const userPos = userPositions[nodeId]
      // 박스 안 = 자동 정렬, 박스 밖 = 사용자 위치 또는 기본 자동 위치
      const position = isInBox ? autoPos[nodeId] : (userPos ?? autoPos[nodeId])
      const isSource = connectingSourceId === issue.id
      const isValid =
        connectingSourceId !== null && !isSource && canConnect(connectingSourceId, issue.id)
      const isInvalid =
        connectingSourceId !== null && !isSource && !canConnect(connectingSourceId, issue.id)
      list.push({
        id: nodeId,
        type: 'work',
        position,
        data: {
          assigneeName: assigneeLabel(issue.assigneeAgentId, assignees),
          assigneeImageUrl: assigneeImageUrl(issue.assigneeAgentId, assignees) ?? undefined,
          issue,
          onCardClick: () => handleCardClick(issue.id),
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
    childIssues,
    computeAutoPositions,
    connectingSourceId,
    handleCardClick,
    inStartBox,
    selectedRoot,
    startBoxWidth,
    userPositions,
  ])

  // 엣지 — 팀장→박스 + 자식끼리 blocks
  const edges = useMemo<Edge[]>(
    () => [
      // 팀장 → 시작 박스 (기본 엣지)
      {
        id: 'ceo-to-startbox',
        source: CEO_NODE_ID,
        target: START_BOX_NODE_ID,
        type: 'straight',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#fbbf24',
          width: 28,
          height: 28,
        },
        style: { stroke: '#fbbf24', strokeWidth: 3 },
        selectable: false,
      },
      ...childIssues.flatMap((targetIssue) =>
        targetIssue.blockedBy
          .filter((source) => childIssues.some((child) => child.id === source.id))
          .map((source) => ({
            id: `blocks:${source.id}:${targetIssue.id}`,
            source: `work:${source.id}`,
            target: `work:${targetIssue.id}`,
            type: 'blocks',
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: '#a78bfa',
              width: 18,
              height: 18,
            },
            data: { sourceIssueId: source.id, targetIssueId: targetIssue.id },
          })),
      ),
    ],
    [childIssues],
  )

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[14rem_minmax(0,1fr)] overflow-hidden">
      {/* 좌측 — 팀장 작업 목록 */}
      <aside className="border-border bg-muted/30 flex min-h-0 flex-col border-r">
        <div className="border-border flex h-12 shrink-0 items-center border-b px-4">
          <span className="text-foreground text-sm font-semibold">팀장 에이전트 작업</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            {rootIssues.map((issue, index) => (
              <button
                key={issue.id}
                type="button"
                onClick={() => setSelectedRootId(issue.id)}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                  selectedRoot?.id === issue.id
                    ? 'bg-background shadow-sm'
                    : 'hover:bg-background/60',
                )}
              >
                <StatusDot status={issue.status} />
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block truncate text-[13px] font-medium">
                    {issue.title}
                  </span>
                  <span className="text-muted-foreground mt-0.5 block truncate font-mono text-[10px]">
                    {issue.identifier}
                  </span>
                </span>
                <span className="text-muted-foreground/70 text-[10px] tabular-nums">
                  {index + 1}
                </span>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={openComposerForRoot}
            className="border-border/60 hover:border-foreground/40 text-muted-foreground hover:text-foreground mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed px-2 py-2.5 text-xs font-medium transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />새 작업
          </button>
        </div>
      </aside>

      {/* 우측 캔버스 */}
      <main className="relative min-h-0 overflow-hidden">
        {selectedRoot ? (
          <CanvasArea
            connectingSourceId={connectingSourceId}
            edges={edges}
            nodes={nodes}
            onCancelConnecting={cancelConnecting}
            onEdgeClick={(sourceIssueId, targetIssueId) =>
              setEdgeToDelete({ source: sourceIssueId, target: targetIssueId })
            }
            onNodesChange={handleNodesChange}
            onRequestAddAgent={openComposerForChild}
            onSave={handleSave}
            pointerPos={pointerPos}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ background: BG_GRADIENT }}
          >
            <div className="text-sm text-white/60">왼쪽에서 작업을 만들거나 선택하세요.</div>
          </div>
        )}
      </main>

      {composerOpen && (
        <WorkComposer
          agent={composerAgent}
          agentBusy={composerAgentBusy}
          agents={agentChoices}
          description={composerDescription}
          isRoot={composerParentId === null}
          onCancel={closeComposer}
          onChangeAgent={() => setComposerAgent(null)}
          onChangeDescription={setComposerDescription}
          onChangeTitle={setComposerTitle}
          onSelectAgent={handleSelectAgent}
          onSubmit={submitComposer}
          title={composerTitle}
        />
      )}

      {actionSheetIssueId !== null && (
        <CardActionSheet
          onCancel={() => setActionSheetIssueId(null)}
          onOpenIssue={() => {
            const id = actionSheetIssueId
            setActionSheetIssueId(null)
            onOpenIssue(id)
          }}
          onStartConnect={() => {
            setConnectingSourceId(actionSheetIssueId)
            setActionSheetIssueId(null)
          }}
        />
      )}

      {edgeToDelete !== null && (
        <EdgeDeleteSheet
          busy={deletingEdge}
          onCancel={() => {
            if (deletingEdge) return
            setEdgeToDelete(null)
          }}
          onConfirm={() => {
            if (onRemoveRelation && edgeToDelete) {
              setDeletingEdge(true)
              onRemoveRelation(edgeToDelete.source, edgeToDelete.target)
              // childIssues 가 갱신되어 관계가 사라지면 아래 effect 가 모달 닫음
            }
          }}
        />
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 캔버스
// ──────────────────────────────────────────────────────────────────────────────
function CanvasArea({
  connectingSourceId,
  edges,
  nodes,
  onCancelConnecting,
  onEdgeClick,
  onNodesChange,
  onRequestAddAgent,
  onSave,
  pointerPos,
}: {
  connectingSourceId: string | null
  edges: Edge[]
  nodes: FlowNode[]
  onCancelConnecting: () => void
  onEdgeClick: (sourceIssueId: string, targetIssueId: string) => void
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void
  onRequestAddAgent: () => void
  onSave: () => void
  pointerPos: { x: number; y: number } | null
}) {
  const rfInstance = useReactFlow()
  const [containerRect, setContainerRect] = useState<DOMRect | null>(null)
  const setContainerRef = useCallback((el: HTMLDivElement | null) => {
    if (el) setContainerRect(el.getBoundingClientRect())
  }, [])

  // 초기 마운트 시 fitView 로 화면 중앙에 정렬
  useEffect(() => {
    const id = setTimeout(() => {
      rfInstance.fitView({ padding: 0.2, maxZoom: 1, minZoom: 0.5, duration: 0 })
    }, 80)
    return () => clearTimeout(id)
  }, [rfInstance])

  // 잇기 모드 — 마우스 따라가는 점선
  const ghostLine = useMemo(() => {
    if (connectingSourceId === null || pointerPos === null || containerRect === null) return null
    const sourceNode = rfInstance.getNode(`work:${connectingSourceId}`)
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
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#a78bfa" />
          </marker>
        </defs>
        <line
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke="#a78bfa"
          strokeWidth={2}
          strokeDasharray="6 4"
          markerEnd="url(#ghost-arrow)"
          opacity={0.9}
        />
      </svg>
    )
  }, [connectingSourceId, containerRect, pointerPos, rfInstance])

  return (
    <div
      ref={setContainerRef}
      className="relative h-full w-full"
      style={{ background: BG_GRADIENT, '--xy-node-boxshadow-selected': 'none' } as CSSProperties}
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
          if (connectingSourceId !== null) onCancelConnecting()
        }}
        onEdgeClick={(_event, edge) => {
          const data = edge.data as { sourceIssueId?: string; targetIssueId?: string } | undefined
          if (data?.sourceIssueId && data?.targetIssueId) {
            onEdgeClick(data.sourceIssueId, data.targetIssueId)
          }
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={28}
          size={1.1}
          color="rgba(255,255,255,0.06)"
        />
      </ReactFlow>

      {ghostLine}

      {/* 잇기 모드 안내 */}
      {connectingSourceId !== null && (
        <div className="pointer-events-none absolute inset-x-0 top-20 z-20 flex justify-center">
          <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-violet-400/40 bg-violet-500/10 px-4 py-2 text-sm shadow-2xl backdrop-blur-xl">
            <Zap className="h-4 w-4 text-violet-300" />
            <span className="text-white">
              <span className="font-semibold text-violet-200">잇기 모드</span> · 다음 작업 클릭
            </span>
            <button
              type="button"
              onClick={onCancelConnecting}
              className="rounded-md px-2 py-0.5 text-xs text-white/60 hover:text-white"
            >
              취소 (ESC)
            </button>
          </div>
        </div>
      )}

      {/* 우상단 — 저장 */}
      <button
        type="button"
        onClick={onSave}
        className="absolute top-6 right-6 z-10 flex h-10 items-center gap-2 rounded-full border border-emerald-400/40 bg-emerald-500/20 px-4 text-sm font-semibold text-emerald-200 shadow-2xl shadow-emerald-500/30 backdrop-blur-xl transition-all hover:scale-105 hover:bg-emerald-500/30"
        aria-label="저장"
      >
        <Save className="h-4 w-4" />
        저장
      </button>

      {/* 우하단 — 추가 */}
      <button
        type="button"
        onClick={onRequestAddAgent}
        className="absolute right-6 bottom-6 z-10 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-2xl shadow-violet-500/40 transition-all hover:scale-110"
        aria-label="작업 추가"
      >
        <Plus className="h-6 w-6" />
      </button>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 팀장 노드
// ──────────────────────────────────────────────────────────────────────────────
function CeoFlowNode({ data }: NodeProps<FlowNode>) {
  const issue = data.issue as IssueBoardIssue | undefined
  const onCardClick = (data.onCardClick as () => void) ?? (() => undefined)
  // 드래그와 클릭 구분: 클릭은 5px 이내 움직임일 때만
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
          if (Math.sqrt(dx * dx + dy * dy) < 5) {
            onCardClick()
          }
        }}
        className="flex cursor-pointer items-center gap-3 rounded-2xl border border-amber-300/30 bg-amber-500/10 px-4 py-2.5 shadow-2xl backdrop-blur-xl transition-all hover:border-amber-300/60 hover:bg-amber-500/15"
      >
        <div className="h-12 w-12 shrink-0 overflow-hidden rounded-full bg-amber-50/10 ring-2 ring-amber-300/40">
          <img
            src={CEO_PROFILE_IMAGE}
            alt=""
            className="h-full w-full object-cover"
            draggable={false}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold tracking-wider text-amber-300 uppercase">
            팀장 에이전트
          </div>
          <div className="truncate text-sm font-semibold text-white">
            {issue?.title ?? '팀장 작업'}
          </div>
        </div>
        {issue && <StatusDot status={issue.status} />}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 시작 박스 (배경 노드)
// ──────────────────────────────────────────────────────────────────────────────
function StartBoxFlowNode({ data }: NodeProps<FlowNode>) {
  const label = typeof data.label === 'string' ? data.label : '병렬 시작 그룹'
  return (
    <div className="group/box relative h-full w-full">
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={false}
        className="!h-1 !w-1 !border-0 !bg-transparent"
        style={{ top: -24 }}
      />
      {/* 박스 본체 — 안 노드 hover 시에는 효과 X (안 노드는 위 z-index) */}
      <div className="pointer-events-auto h-full w-full rounded-2xl border-2 border-dashed border-violet-400/40 bg-violet-500/[0.04] transition-all hover:border-violet-400/80 hover:bg-violet-500/[0.08] hover:shadow-2xl hover:shadow-violet-500/20">
        <div className="pointer-events-none absolute -top-3 left-4 flex items-center gap-1.5 rounded-full border border-violet-400/40 bg-[#14102c] px-2.5 py-0.5 text-[10px] font-semibold tracking-wider text-violet-300 uppercase transition-all group-hover/box:border-violet-400/80 group-hover/box:text-violet-200">
          <Zap className="h-3 w-3" />
          병렬 시작 · {label}
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 노드
// ──────────────────────────────────────────────────────────────────────────────
function WorkFlowNode({ data }: NodeProps<FlowNode>) {
  const issue = data.issue as IssueBoardIssue | undefined
  if (!issue) return null
  const imageUrl = typeof data.assigneeImageUrl === 'string' ? data.assigneeImageUrl : undefined
  const assigneeName = typeof data.assigneeName === 'string' ? data.assigneeName : ''
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
          'group relative flex w-[148px] cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 p-3 shadow-xl transition-all',
          'border-violet-400/30 bg-[#1e1b4b]',
          'hover:border-violet-300 hover:shadow-2xl hover:shadow-violet-500/30',
          isSource && '!border-violet-400 ring-2 ring-violet-400',
          isValid && '!border-emerald-400 ring-2 ring-emerald-400',
          isInvalid && '!border-red-500/70 opacity-70 ring-2 ring-red-500/70',
        )}
      >
        <div className="relative">
          <div className="h-14 w-14 overflow-hidden rounded-full bg-white/5 shadow-lg ring-2 ring-white/15">
            {imageUrl ? (
              <img src={imageUrl} alt="" className="h-full w-full object-cover" draggable={false} />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-base font-semibold text-white/70">
                {assigneeName.charAt(0).toUpperCase() || '?'}
              </div>
            )}
          </div>
          <div className="absolute right-0 bottom-0 flex h-5 w-5 items-center justify-center rounded-full bg-[#1e1b4b]">
            <StatusDot status={issue.status} small />
          </div>
        </div>
        <div className="w-full text-center">
          <div className="line-clamp-2 text-[12px] leading-tight font-semibold text-white">
            {issue.title}
          </div>
          <div className="mt-1 truncate text-[10px] text-white/50">{assigneeName}</div>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 엣지
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
        stroke="#a78bfa"
        strokeWidth={2}
        fill="none"
        markerEnd={markerEnd}
        className="transition-all group-hover/edge:!stroke-[#c4b5fd] group-hover/edge:[stroke-width:3]"
        style={{ filter: 'drop-shadow(0 0 4px rgba(167, 139, 250, 0.4))' }}
      />
    </g>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 카드 액션 시트
// ──────────────────────────────────────────────────────────────────────────────
function CardActionSheet({
  onCancel,
  onOpenIssue,
  onStartConnect,
}: {
  onCancel: () => void
  onOpenIssue: () => void
  onStartConnect: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-[280px] max-w-full overflow-hidden rounded-2xl border border-white/10 bg-[#14102c]/95 shadow-2xl backdrop-blur-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="p-2">
          <button
            type="button"
            onClick={onOpenIssue}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            <Info className="h-4 w-4 text-white/60" />
            작업 정보
          </button>
          <button
            type="button"
            onClick={onStartConnect}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            <Zap className="h-4 w-4 text-violet-300" />
            다음 작업으로 잇기
          </button>
        </div>
        <div className="border-t border-white/10 p-2">
          <button
            type="button"
            onClick={onCancel}
            className="w-full rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 화살표 삭제 확인
// ──────────────────────────────────────────────────────────────────────────────
function EdgeDeleteSheet({
  busy,
  onCancel,
  onConfirm,
}: {
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={busy ? undefined : onCancel}
    >
      <div
        className="w-[320px] max-w-full overflow-hidden rounded-2xl border border-white/10 bg-[#14102c]/95 shadow-2xl backdrop-blur-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="p-5 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/20">
            {busy ? (
              <Loader2 className="h-6 w-6 animate-spin text-red-400" />
            ) : (
              <Trash2 className="h-6 w-6 text-red-400" />
            )}
          </div>
          <div className="text-base font-semibold text-white">
            {busy ? '삭제 중...' : '화살표를 삭제할까요?'}
          </div>
          <div className="mt-1 text-xs text-white/60">
            {busy ? '잠시만 기다리세요' : '작업 순서 관계가 해제됩니다.'}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 border-t border-white/10 p-3">
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-xl bg-red-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-60"
          >
            삭제
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-xl px-3 py-2 text-sm font-medium text-white/70 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// 작업 추가 모달
// ──────────────────────────────────────────────────────────────────────────────
function WorkComposer({
  agent,
  agentBusy,
  agents,
  description,
  isRoot,
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
  isRoot: boolean
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
      <div className="w-[460px] max-w-full overflow-hidden rounded-2xl border border-white/10 bg-[#14102c]/95 shadow-2xl backdrop-blur-xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h3 className="text-base font-semibold text-white">
            {isRoot ? '새 팀장 작업' : '새 자식 작업'}
          </h3>
          <button
            type="button"
            onClick={onCancel}
            className="flex h-7 w-7 items-center justify-center rounded-md text-white/60 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div>
            <label className="mb-2 block text-[11px] font-semibold tracking-wider text-white/50 uppercase">
              에이전트
            </label>
            {agent ? (
              <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5">
                <div className="h-10 w-10 shrink-0 overflow-hidden rounded-full bg-white/5 ring-2 ring-white/15">
                  {agent.imageUrl ? (
                    <img src={agent.imageUrl} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-sm text-white/70">
                      {agent.name.charAt(0).toUpperCase() || '?'}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-white">{agent.name}</div>
                  {agent.templateKey && (
                    <div className="truncate text-xs text-white/50">{agent.templateKey}</div>
                  )}
                </div>
                {!isRoot && (
                  <Button type="button" variant="ghost" size="sm" onClick={onChangeAgent}>
                    변경
                  </Button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {agents.map((choice) => (
                  <button
                    key={choice.id}
                    type="button"
                    disabled={agentBusy}
                    onClick={() => void onSelectAgent(choice)}
                    className="flex flex-col items-center gap-2 rounded-xl border border-white/10 bg-white/5 p-3 transition-colors hover:border-white/30 hover:bg-white/10 disabled:opacity-50"
                  >
                    <div className="h-11 w-11 overflow-hidden rounded-full bg-white/5 ring-2 ring-white/15">
                      {choice.imageUrl ? (
                        <img src={choice.imageUrl} alt="" className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-sm text-white/70">
                          {choice.name.charAt(0).toUpperCase() || '?'}
                        </div>
                      )}
                    </div>
                    <span className="line-clamp-1 max-w-full text-[11px] font-medium text-white">
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
                <label className="mb-2 block text-[11px] font-semibold tracking-wider text-white/50 uppercase">
                  작업 제목
                </label>
                <input
                  autoFocus
                  type="text"
                  value={title}
                  onChange={(event) => onChangeTitle(event.target.value)}
                  placeholder="예: 분기 보고서 만들기"
                  className="h-10 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white outline-none placeholder:text-white/30 focus-visible:ring-2 focus-visible:ring-violet-400/40"
                />
              </div>
              <div>
                <label className="mb-2 block text-[11px] font-semibold tracking-wider text-white/50 uppercase">
                  세부사항
                </label>
                <Textarea
                  value={description}
                  onChange={(event) => onChangeDescription(event.target.value)}
                  placeholder="에이전트에게 전달할 지시사항 (선택)"
                  className="min-h-24 resize-y rounded-lg border-white/10 bg-white/5 text-white placeholder:text-white/30"
                />
                <p className="mt-1.5 text-[11px] text-white/40">
                  비어 있으면 제목이 그대로 지시사항으로 사용됩니다.
                </p>
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-white/10 px-5 py-3">
          <Button
            type="button"
            size="sm"
            onClick={onSubmit}
            disabled={!agent || !title.trim() || agentBusy}
          >
            추가
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
function StatusDot({
  status,
  small = false,
}: {
  status: IssueBoardIssue['status']
  small?: boolean
}) {
  const sizeClass = small ? 'h-3 w-3' : 'h-4 w-4'
  if (status === 'done') {
    return <CheckCircle2 className={cn(sizeClass, 'shrink-0 text-emerald-400')} />
  }
  return (
    <Circle
      className={cn(
        sizeClass,
        'shrink-0 fill-current',
        status === 'blocked' && 'text-amber-400',
        status === 'in_progress' && 'text-blue-400',
        status !== 'blocked' && status !== 'in_progress' && 'text-white/30',
      )}
    />
  )
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

// 두 노드 사이 직선이 각 노드 사각형 테두리와 만나는 점 계산
function computeFloatingEdgePoints(
  sourceNode: InternalNode,
  targetNode: InternalNode,
): { sx: number; sy: number; tx: number; ty: number } {
  const sourceCenter = nodeCenter(sourceNode)
  const targetCenter = nodeCenter(targetNode)
  const sx = sourceCenter.x
  const sy = sourceCenter.y
  const tx = targetCenter.x
  const ty = targetCenter.y
  const sourceBorder = intersectBorder(sourceNode, sourceCenter, targetCenter)
  const targetBorder = intersectBorder(targetNode, targetCenter, sourceCenter)
  return {
    sx: sourceBorder?.x ?? sx,
    sy: sourceBorder?.y ?? sy,
    tx: targetBorder?.x ?? tx,
    ty: targetBorder?.y ?? ty,
  }
}

function nodeCenter(node: InternalNode): { x: number; y: number } {
  const w = node.measured?.width ?? 100
  const h = node.measured?.height ?? 100
  return {
    x: (node.internals.positionAbsolute?.x ?? node.position.x) + w / 2,
    y: (node.internals.positionAbsolute?.y ?? node.position.y) + h / 2,
  }
}

// node 중심에서 other 방향 직선이 node 사각형 테두리와 만나는 점
function intersectBorder(
  node: InternalNode,
  center: { x: number; y: number },
  other: { x: number; y: number },
): { x: number; y: number } | null {
  const w = node.measured?.width ?? 100
  const h = node.measured?.height ?? 100
  const halfW = w / 2
  const halfH = h / 2
  const dx = other.x - center.x
  const dy = other.y - center.y
  if (dx === 0 && dy === 0) return null
  // 사각형 테두리까지 직선 비율 t (0~1) 계산
  const tx = dx !== 0 ? halfW / Math.abs(dx) : Infinity
  const ty = dy !== 0 ? halfH / Math.abs(dy) : Infinity
  const t = Math.min(tx, ty)
  return { x: center.x + dx * t, y: center.y + dy * t }
}

function sortFlowIssues(issues: IssueBoardIssue[]) {
  return [...issues].sort((left, right) => {
    const leftOrder = left.flowOrder ?? Number.MAX_SAFE_INTEGER
    const rightOrder = right.flowOrder ?? Number.MAX_SAFE_INTEGER
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    return new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime()
  })
}
