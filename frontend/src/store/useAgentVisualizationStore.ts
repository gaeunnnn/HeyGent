import { create } from 'zustand'
import type {
  AgentActivityStatus,
  AgentConfig,
  AgentRuntime,
  AgentVisualizationInfo,
  TaskStatus,
  VisualizationTask,
} from '@/components/office/types'
import { areVisualizationTasksEqual } from '@/utils/agentCurrentTask'

export type { AgentActivityStatus, AgentVisualizationInfo, TaskStatus, VisualizationTask }

interface AgentVisualizationState {
  agentInfoMap: Record<string, AgentVisualizationInfo>
  selectedAgentId: string | null
  // 페이지 이동 후 재진입 시 에이전트 위치/상태 유지용 런타임 상태
  agentRuntimes: AgentRuntime[]
  spawnedKeys: string[]
  // 현재 시각화 중인 세션 ID — 같은 세션 재진입 시 상태 보존 판단에 사용
  activeSessionId: string | null
  setAgentInfoMap: (map: Record<string, AgentVisualizationInfo>) => void
  updateAgentInfo: (agentId: string, updates: Partial<AgentVisualizationInfo>) => void
  selectAgent: (agentId: string | null) => void
  setAgentRuntimes: (updater: AgentRuntime[] | ((prev: AgentRuntime[]) => AgentRuntime[])) => void
  addSpawnedKey: (id: string) => void
  removeAgentFromVisualization: (spriteId: string) => void
  // 세션 전환 시 호출 — 이전 세션 에이전트 잔상 제거 (같은 세션 재진입이면 상태 유지)
  clearVisualizationState: (newSessionId?: string | null) => void
  startCeoWork: (taskRunId?: string, sessionId?: string | null) => void
  startSessionWork: (input: {
    taskRunId?: string
    sessionId?: string | null
    subAgentSpriteIds?: string[]
  }) => void
  settleCeoAtDesk: (taskRunId?: string) => void
  activeCeoTaskRunId: string | null
}

// mock 데이터 — 백엔드 API 연동 전 임시. spriteId(agentId)는 AGENT_CONFIGS의 id와 일치해야 함.
const MOCK_AGENTS: AgentVisualizationInfo[] = [
  {
    agentId: 'agent01',
    name: '김준혁',
    role: '백엔드 개발자',
    skills: ['Python', 'FastAPI', 'PostgreSQL', 'Docker'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-001',
      title: 'REST API 설계',
      description: '사용자 인증 및 세션 관리를 위한 API 엔드포인트 설계 및 문서화',
      status: 'in_progress',
      startedAt: '2026-05-11T09:00:00',
    },
    taskHistory: [
      {
        taskId: 'h-001',
        title: '데이터베이스 스키마 설계',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T17:00:00',
      },
      {
        taskId: 'h-002',
        title: '개발 환경 구성',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T11:00:00',
      },
      {
        taskId: 'h-003',
        title: '요구사항 분석',
        description: '',
        status: 'completed',
        completedAt: '2026-05-09T16:00:00',
      },
    ],
  },
  {
    agentId: 'agent02',
    name: '이서연',
    role: '프론트엔드 개발자',
    skills: ['React', 'TypeScript', 'Tailwind CSS', 'Zustand'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-002',
      title: '에이전트 상태 UI 개발',
      description: '실시간 에이전트 상태를 시각화하는 페이지 컴포넌트 구현',
      status: 'in_progress',
      startedAt: '2026-05-11T09:30:00',
    },
    taskHistory: [
      {
        taskId: 'h-011',
        title: '오피스 맵 컴포넌트 구현',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T18:00:00',
      },
      {
        taskId: 'h-012',
        title: '스프라이트 애니메이션 구현',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T14:00:00',
      },
    ],
  },
  {
    agentId: 'agent03',
    name: '박민준',
    role: 'AI 엔지니어',
    skills: ['LLM', 'LangChain', 'Python', 'Vector DB'],
    activityStatus: 'resting',
    currentTask: undefined,
    taskHistory: [
      {
        taskId: 'h-021',
        title: '에이전트 프롬프트 최적화',
        description: '',
        status: 'completed',
        completedAt: '2026-05-11T08:30:00',
      },
      {
        taskId: 'h-022',
        title: 'RAG 파이프라인 구축',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T17:30:00',
      },
      {
        taskId: 'h-023',
        title: '임베딩 모델 선정',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T10:00:00',
      },
    ],
  },
  {
    agentId: 'agent04',
    name: '최다은',
    role: '데이터 분석가',
    skills: ['Python', 'Pandas', 'SQL', 'Tableau'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-004',
      title: '사용자 행동 데이터 분석',
      description: '세션 로그 기반 사용자 패턴 분석 및 인사이트 도출',
      status: 'in_progress',
      startedAt: '2026-05-11T10:00:00',
    },
    taskHistory: [
      {
        taskId: 'h-031',
        title: '데이터 수집 파이프라인 구축',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T16:00:00',
      },
      {
        taskId: 'h-032',
        title: 'KPI 정의',
        description: '',
        status: 'completed',
        completedAt: '2026-05-09T15:00:00',
      },
    ],
  },
  {
    agentId: 'agent05',
    name: '정하준',
    role: 'QA 엔지니어',
    skills: ['테스트 자동화', 'Selenium', 'Jest', 'Cypress'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-005',
      title: 'E2E 테스트 작성',
      description: '에이전트 시각화 페이지 E2E 테스트 케이스 작성 및 실행',
      status: 'in_progress',
      startedAt: '2026-05-11T09:15:00',
    },
    taskHistory: [
      {
        taskId: 'h-041',
        title: '테스트 전략 수립',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T15:00:00',
      },
      {
        taskId: 'h-042',
        title: '단위 테스트 작성',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T12:00:00',
      },
    ],
  },
  {
    agentId: 'agent06',
    name: '윤지민',
    role: 'DevOps 엔지니어',
    skills: ['Kubernetes', 'Docker', 'CI/CD', 'AWS'],
    activityStatus: 'resting',
    currentTask: undefined,
    taskHistory: [
      {
        taskId: 'h-051',
        title: 'CI/CD 파이프라인 구축',
        description: '',
        status: 'completed',
        completedAt: '2026-05-11T08:00:00',
      },
      {
        taskId: 'h-052',
        title: '컨테이너 오케스트레이션 설정',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T17:00:00',
      },
      {
        taskId: 'h-053',
        title: '모니터링 시스템 구축',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T13:00:00',
      },
    ],
  },
  {
    agentId: 'agent07',
    name: '강소율',
    role: 'UX 디자이너',
    skills: ['Figma', 'UI/UX', '사용자 리서치', '프로토타이핑'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-007',
      title: '대시보드 UI 개선안',
      description: '사용자 피드백 기반 대시보드 개선 와이어프레임 제작',
      status: 'in_progress',
      startedAt: '2026-05-11T10:30:00',
    },
    taskHistory: [
      {
        taskId: 'h-061',
        title: '사용자 인터뷰 진행',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T16:00:00',
      },
      {
        taskId: 'h-062',
        title: '디자인 시스템 정의',
        description: '',
        status: 'completed',
        completedAt: '2026-05-09T17:00:00',
      },
    ],
  },
  {
    agentId: 'agent08',
    name: '임도현',
    role: '비즈니스 애널리스트',
    skills: ['비즈니스 분석', 'Excel', 'PowerPoint', '시장 조사'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-008',
      title: '경쟁사 분석 보고서',
      description: '주요 경쟁사 제품 기능 및 시장 포지션 비교 분석',
      status: 'in_progress',
      startedAt: '2026-05-11T09:45:00',
    },
    taskHistory: [
      {
        taskId: 'h-071',
        title: '시장 규모 조사',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T17:30:00',
      },
      {
        taskId: 'h-072',
        title: '고객 세그먼트 분석',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T14:00:00',
      },
    ],
  },
  {
    agentId: 'agent09',
    name: '한수빈',
    role: '프로젝트 매니저',
    skills: ['프로젝트 관리', 'Jira', 'Scrum', '이해관계자 관리'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-009',
      title: '스프린트 계획 수립',
      description: '다음 스프린트 백로그 정리 및 팀원 업무 배분',
      status: 'in_progress',
      startedAt: '2026-05-11T09:00:00',
    },
    taskHistory: [
      {
        taskId: 'h-081',
        title: '스프린트 리뷰 진행',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T16:00:00',
      },
      {
        taskId: 'h-082',
        title: '팀 회고 미팅 진행',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T15:00:00',
      },
      {
        taskId: 'h-083',
        title: '이해관계자 보고',
        description: '',
        status: 'completed',
        completedAt: '2026-05-09T17:00:00',
      },
    ],
  },
  {
    agentId: 'ceo',
    name: '팀장 에이전트',
    role: '최고경영자',
    skills: ['전략 기획', '리더십', '의사결정', '비즈니스 개발'],
    activityStatus: 'working',
    currentTask: {
      taskId: 'task-ceo',
      title: '분기 전략 검토',
      description: '각 팀의 분기별 성과 및 다음 분기 전략 방향 검토',
      status: 'in_progress',
      startedAt: '2026-05-11T08:00:00',
    },
    taskHistory: [
      {
        taskId: 'h-ceo-1',
        title: '투자자 미팅',
        description: '',
        status: 'completed',
        completedAt: '2026-05-09T17:00:00',
      },
      {
        taskId: 'h-ceo-2',
        title: '로드맵 수립',
        description: '',
        status: 'completed',
        completedAt: '2026-05-08T16:00:00',
      },
    ],
  },
  {
    agentId: 'agent10',
    name: '오채원',
    role: '리서처',
    skills: ['기술 리서치', '논문 분석', 'Python', '실험 설계'],
    activityStatus: 'resting',
    currentTask: undefined,
    taskHistory: [
      {
        taskId: 'h-091',
        title: '최신 LLM 논문 조사',
        description: '',
        status: 'completed',
        completedAt: '2026-05-11T08:00:00',
      },
      {
        taskId: 'h-092',
        title: '벤치마크 실험 설계',
        description: '',
        status: 'completed',
        completedAt: '2026-05-10T17:00:00',
      },
    ],
  },
]

export function createMockAgentInfoMap(): Record<string, AgentVisualizationInfo> {
  return Object.fromEntries(MOCK_AGENTS.map((info) => [info.agentId, info]))
}

const CEO_CONFIG: AgentConfig = {
  id: 'ceo',
  name: '팀장 에이전트',
  spritePath: '/assets/agents/ceo',
  scale: 1.05,
  stateScales: { walking: 0.85, standing_wait: 0.85, sitting_work: 0.7 },
  sittingSprites: {
    sitting_desk: 'ceo_desk',
    sitting_meeting: 'ceo_explain',
    sitting_work: 'ceo_work',
    standing_wait: 'walk_side_stand',
  },
  allowedUIDestinations: ['desk', 'meeting', 'work'],
  destinationLabels: { meeting: '화이트보드', work: '작업' },
  initialPosition: { x: 1460, y: 700 },
  destinations: {
    desk: { x: 310, y: 215 },
    meeting: { x: 383, y: 493 },
    work: { x: 275, y: 195 },
    sofa: { x: 310, y: 215 },
    floorLean: { x: 310, y: 215 },
    calling: { x: 310, y: 215 },
  },
}

const SESSION_SUB_AGENT_CONFIGS: Record<string, AgentConfig> = {
  agent01: {
    id: 'agent01',
    name: 'Agent 01',
    spritePath: '/assets/agents/agent01',
    stateScales: { sitting_meeting: 0.85, sitting_calling: 0.85, sitting_floor_lean: 0.85 },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 470, y: 395 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1545, y: 285 },
      meeting: { x: 415, y: 130 },
      calling: { x: 1110, y: 660 },
    },
  },
  agent02: {
    id: 'agent02',
    name: 'Agent 02',
    spritePath: '/assets/agents/agent02',
    stateScales: { sitting_meeting: 0.85, sitting_floor_lean: 0.85, sitting_calling: 0.85 },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 650, y: 458 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1070, y: 285 },
      meeting: { x: 925, y: 90 },
      calling: { x: 840, y: 350 },
    },
  },
  agent03: {
    id: 'agent03',
    name: 'Agent 03',
    spritePath: '/assets/agents/agent03',
    scale: 0.85,
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 470, y: 395 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1215, y: 370 },
      meeting: { x: 715, y: 215 },
      calling: { x: 990, y: 750 },
    },
  },
  agent04: {
    id: 'agent04',
    name: 'Agent 04',
    spritePath: '/assets/agents/agent04',
    scale: 0.87,
    stateScales: { sitting_desk: 1.1, sitting_floor_lean: 0.85 },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 465, y: 595 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1415, y: 360 },
      meeting: { x: 920, y: 220 },
      calling: { x: 1110, y: 655 },
    },
  },
  agent05: {
    id: 'agent05',
    name: 'Agent 05',
    spritePath: '/assets/agents/agent05',
    stateScales: {
      sitting_desk: 0.92,
      sitting_meeting: 0.85,
      sitting_floor_lean: 0.8,
      sitting_calling: 0.9,
    },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 825, y: 520 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1535, y: 425 },
      meeting: { x: 415, y: 130 },
      calling: { x: 1334, y: 665 },
    },
  },
  agent06: {
    id: 'agent06',
    name: 'Agent 06',
    spritePath: '/assets/agents/agent06',
    stateScales: {
      sitting_floor_lean: 0.85,
      sitting_meeting: 0.85,
      sitting_calling: 0.85,
      sitting_sofa: 0.85,
    },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 825, y: 520 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1290, y: 260 },
      meeting: { x: 925, y: 90 },
      calling: { x: 1070, y: 658 },
    },
  },
  agent07: {
    id: 'agent07',
    name: 'Agent 07',
    spritePath: '/assets/agents/agent07',
    stateScales: {
      sitting_meeting: 0.8,
      sitting_sofa: 0.85,
      sitting_floor_lean: 0.85,
      sitting_calling: 0.85,
    },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 465, y: 595 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1340, y: 280 },
      meeting: { x: 850, y: 75 },
      calling: { x: 1430, y: 840 },
    },
  },
  agent08: {
    id: 'agent08',
    name: 'Agent 08',
    spritePath: '/assets/agents/agent08',
    scale: 0.85,
    stateScales: { sitting_sofa: 1.1, sitting_desk: 0.95, sitting_calling: 1.1 },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 650, y: 458 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 995, y: 340 },
      meeting: { x: 670, y: 105 },
      calling: { x: 240, y: 710 },
    },
  },
  agent09: {
    id: 'agent09',
    name: 'Agent 09',
    spritePath: '/assets/agents/agent09',
    scale: 0.85,
    stateScales: { sitting_desk: 1.1 },
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 650, y: 685 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1380, y: 490 },
      meeting: { x: 785, y: 245 },
      calling: { x: 1200, y: 658 },
    },
  },
  agent10: {
    id: 'agent10',
    name: 'Agent 10',
    spritePath: '/assets/agents/agent10',
    scale: 0.85,
    initialPosition: { x: 1460, y: 700 },
    destinations: {
      desk: { x: 650, y: 685 },
      sofa: { x: 1185, y: 205 },
      floorLean: { x: 1310, y: 460 },
      meeting: { x: 920, y: 220 },
      calling: { x: 1250, y: 660 },
    },
  },
}

const SESSION_SOFA_SPOTS = [
  { x: 1185, y: 205 },
  { x: 1140, y: 230 },
]
const SESSION_SPOT_OCCUPIED_RADIUS = 40

function isRestSpotOccupied(
  spot: { x: number; y: number },
  agents: AgentRuntime[],
  excludeId: string,
) {
  return agents.some(
    (agent) =>
      agent.config.id !== excludeId &&
      agent.state !== 'idle' &&
      Math.hypot(agent.position.x - spot.x, agent.position.y - spot.y) <
        SESSION_SPOT_OCCUPIED_RADIUS,
  )
}

function buildRestingSubAgentRuntime(
  spriteId: string,
  agents: AgentRuntime[],
): AgentRuntime | null {
  const config = SESSION_SUB_AGENT_CONFIGS[spriteId]
  if (!config) return null

  const freeSofa = SESSION_SOFA_SPOTS.find((spot) => !isRestSpotOccupied(spot, agents, spriteId))
  const position = freeSofa ?? config.destinations.floorLean ?? config.initialPosition
  const state = freeSofa ? 'sitting_sofa' : 'sitting_floor_lean'

  return {
    config,
    position: { ...position },
    state,
    targetState: state,
    walkFrame: 0,
    transitionDuration: 0,
    pendingWaypoints: [],
    targetPosition: null,
    standWaitTarget: null,
    facingRight: false,
  }
}

export function playAgentChime() {
  try {
    const ctx = new AudioContext()
    const play = () => {
      ;[1318.51, 1567.98].forEach((freq, i) => {
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.type = 'sine'
        osc.frequency.value = freq
        const t = ctx.currentTime + i * 0.12
        gain.gain.setValueAtTime(0.18, t)
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.45)
        osc.start(t)
        osc.stop(t + 0.45)
      })
    }
    void ctx.resume().then(play)
  } catch {
    // AudioContext 미지원 환경에서는 소리 없이 상태만 갱신한다.
  }
}

function areAgentVisualizationInfoEqual(
  left: AgentVisualizationInfo,
  right: AgentVisualizationInfo,
): boolean {
  return (
    left.agentId === right.agentId &&
    left.name === right.name &&
    left.role === right.role &&
    left.profileImage === right.profileImage &&
    left.activityStatus === right.activityStatus &&
    areStringArraysEqual(left.skills, right.skills) &&
    areVisualizationTasksEqual(left.currentTask, right.currentTask) &&
    areVisualizationTaskArraysEqual(left.taskHistory, right.taskHistory)
  )
}

function areVisualizationTaskArraysEqual(
  left: VisualizationTask[],
  right: VisualizationTask[],
): boolean {
  if (left === right) return true
  if (left.length !== right.length) return false
  return left.every((task, index) => areVisualizationTasksEqual(task, right[index]))
}

function areStringArraysEqual(left: string[], right: string[]): boolean {
  if (left === right) return true
  if (left.length !== right.length) return false
  return left.every((value, index) => value === right[index])
}

export const useAgentVisualizationStore = create<AgentVisualizationState>((set) => ({
  agentInfoMap: {},
  selectedAgentId: null,
  agentRuntimes: [],
  spawnedKeys: [],
  activeSessionId: null,
  activeCeoTaskRunId: null,

  setAgentInfoMap: (map) => set({ agentInfoMap: map }),

  updateAgentInfo: (agentId, updates) =>
    set((state) => {
      const existing = state.agentInfoMap[agentId] ?? {
        agentId,
        name: agentId,
        role: '',
        skills: [],
        activityStatus: 'inactive' as AgentActivityStatus,
        currentTask: undefined,
        taskHistory: [],
      }
      const next = { ...existing, ...updates }
      if (areAgentVisualizationInfoEqual(existing, next)) return state
      return { agentInfoMap: { ...state.agentInfoMap, [agentId]: next } }
    }),

  selectAgent: (agentId) => set({ selectedAgentId: agentId }),

  setAgentRuntimes: (updater) =>
    set((state) => ({
      agentRuntimes: typeof updater === 'function' ? updater(state.agentRuntimes) : updater,
    })),

  addSpawnedKey: (id) =>
    set((state) => ({
      spawnedKeys: state.spawnedKeys.includes(id) ? state.spawnedKeys : [...state.spawnedKeys, id],
    })),

  removeAgentFromVisualization: (spriteId) =>
    set((state) => {
      const nextInfoMap = { ...state.agentInfoMap }
      delete nextInfoMap[spriteId]
      return {
        agentInfoMap: nextInfoMap,
        agentRuntimes: state.agentRuntimes.filter((agent) => agent.config.id !== spriteId),
        spawnedKeys: state.spawnedKeys.filter((key) => key !== spriteId),
      }
    }),

  clearVisualizationState: (newSessionId) =>
    set((state) => {
      if (newSessionId !== undefined && newSessionId === state.activeSessionId) return state
      return {
        agentRuntimes: [],
        spawnedKeys: [],
        activeCeoTaskRunId: null,
        selectedAgentId: null,
        activeSessionId: newSessionId ?? null,
      }
    }),

  startCeoWork: (taskRunId, sessionId) =>
    set((state) => {
      if (taskRunId !== undefined && state.activeCeoTaskRunId === taskRunId) {
        return {
          agentRuntimes: state.agentRuntimes,
          activeSessionId: sessionId ?? state.activeSessionId,
        }
      }

      const workPosition = CEO_CONFIG.destinations.work!
      const existingCeo = state.agentRuntimes.find((agent) => agent.config.id === 'ceo')
      const nextCeo: AgentRuntime = {
        ...(existingCeo ?? {
          config: CEO_CONFIG,
          facingRight: false,
        }),
        config: existingCeo?.config ?? CEO_CONFIG,
        position: { ...workPosition },
        state: 'sitting_work',
        targetState: 'sitting_work',
        walkFrame: 0,
        transitionDuration: 0,
        pendingWaypoints: [],
        targetPosition: null,
        standWaitTarget: null,
        facingRight: existingCeo?.facingRight ?? false,
      }

      return {
        activeSessionId: sessionId ?? state.activeSessionId,
        activeCeoTaskRunId: taskRunId ?? state.activeCeoTaskRunId,
        spawnedKeys: state.spawnedKeys.includes('ceo')
          ? state.spawnedKeys
          : [...state.spawnedKeys, 'ceo'],
        agentInfoMap: {
          ...state.agentInfoMap,
          ceo: {
            ...(state.agentInfoMap.ceo ?? {
              agentId: 'ceo',
              name: '팀장 에이전트',
              role: '',
              skills: [],
              taskHistory: [],
            }),
            activityStatus: 'working',
            currentTask: {
              taskId: taskRunId ?? 'ceo-active-task',
              title: '작업 진행 중',
              description: '',
              status: 'in_progress',
              startedAt: new Date().toISOString(),
            },
          },
        },
        agentRuntimes:
          existingCeo === undefined
            ? [...state.agentRuntimes, nextCeo]
            : state.agentRuntimes.map((agent) => (agent.config.id === 'ceo' ? nextCeo : agent)),
      }
    }),

  startSessionWork: ({ taskRunId, sessionId, subAgentSpriteIds = [] }) =>
    set((state) => {
      const shouldResetSession =
        sessionId !== undefined && sessionId !== null && state.activeSessionId !== sessionId
      const baseAgents = shouldResetSession ? [] : state.agentRuntimes
      const baseSpawnedKeys = shouldResetSession ? [] : state.spawnedKeys
      const existingCeo = baseAgents.find((agent) => agent.config.id === 'ceo')
      const workPosition = CEO_CONFIG.destinations.work!

      const nextCeo: AgentRuntime = {
        ...(existingCeo ?? {
          config: CEO_CONFIG,
          facingRight: false,
        }),
        config: existingCeo?.config ?? CEO_CONFIG,
        position: { ...workPosition },
        state: 'sitting_work',
        targetState: 'sitting_work',
        walkFrame: 0,
        transitionDuration: 0,
        pendingWaypoints: [],
        targetPosition: null,
        standWaitTarget: null,
        facingRight: existingCeo?.facingRight ?? false,
      }

      let nextAgents =
        existingCeo === undefined
          ? [...baseAgents, nextCeo]
          : baseAgents.map((agent) => (agent.config.id === 'ceo' ? nextCeo : agent))
      const nextSpawnedKeys = new Set(baseSpawnedKeys)
      nextSpawnedKeys.add('ceo')

      for (const spriteId of subAgentSpriteIds) {
        if (
          nextSpawnedKeys.has(spriteId) ||
          nextAgents.some((agent) => agent.config.id === spriteId)
        ) {
          continue
        }
        const runtime = buildRestingSubAgentRuntime(spriteId, nextAgents)
        if (runtime === null) continue
        nextAgents = [...nextAgents, runtime]
        nextSpawnedKeys.add(spriteId)
      }

      return {
        activeSessionId: sessionId ?? state.activeSessionId,
        activeCeoTaskRunId: taskRunId ?? state.activeCeoTaskRunId,
        spawnedKeys: [...nextSpawnedKeys],
        agentInfoMap: {
          ...state.agentInfoMap,
          ceo: {
            ...(state.agentInfoMap.ceo ?? {
              agentId: 'ceo',
              name: '팀장 에이전트',
              role: '',
              skills: [],
              taskHistory: [],
            }),
            activityStatus: 'working',
            currentTask: {
              taskId: taskRunId ?? 'ceo-active-task',
              title: '작업 진행 중',
              description: '',
              status: 'in_progress',
              startedAt: new Date().toISOString(),
            },
          },
        },
        agentRuntimes: nextAgents,
      }
    }),

  settleCeoAtDesk: (taskRunId) =>
    set((state) => {
      return {
        activeCeoTaskRunId:
          taskRunId !== undefined &&
          state.activeCeoTaskRunId !== null &&
          state.activeCeoTaskRunId !== taskRunId
            ? state.activeCeoTaskRunId
            : null,
        agentInfoMap: {
          ...state.agentInfoMap,
          ceo: {
            ...(state.agentInfoMap.ceo ?? {
              agentId: 'ceo',
              name: '팀장 에이전트',
              role: '',
              skills: [],
              taskHistory: [],
            }),
            activityStatus: 'resting',
            currentTask: undefined,
          },
        },
        agentRuntimes: state.agentRuntimes.map((agent) => {
          if (agent.config.id !== 'ceo') return agent
          if (
            taskRunId !== undefined &&
            state.activeCeoTaskRunId !== null &&
            state.activeCeoTaskRunId !== taskRunId
          ) {
            return agent
          }
          const nextDeskPosition = agent.config.destinations.desk
          if (!nextDeskPosition) return agent
          return {
            ...agent,
            position: { ...nextDeskPosition },
            state: 'sitting_desk',
            targetState: 'sitting_desk',
            walkFrame: 0,
            transitionDuration: 0,
            pendingWaypoints: [],
            targetPosition: null,
            standWaitTarget: null,
            facingRight: false,
          }
        }),
      }
    }),
}))
