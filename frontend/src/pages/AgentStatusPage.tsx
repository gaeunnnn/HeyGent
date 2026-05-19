import { useState, useRef, useEffect, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router'
import { Loader2 } from 'lucide-react'
import { OfficeMap } from '@/components/office/OfficeMap'
import { CeoActionMenu } from '@/components/office/CeoActionMenu'
import { CeoCommandDialog } from '@/components/office/CeoCommandDialog'
import { useAgentVisualizationStore } from '@/store/useAgentVisualizationStore'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useAuthStore } from '@/store/useAuthStore'
import { getCommandUsage } from '@/apis/aiCommandUsage'
import { agentProfilesToPanelItems } from '@/apis/agents'
import type { CommandUsageSummary } from '@/apis/aiCommandUsage'
import type {
  AgentConfig,
  AgentRuntime,
  Destination,
  UIDestination,
  SittingState,
  AgentVisualizationInfo,
  AgentActivityStatus,
  TaskStatus,
} from '@/components/office/types'
import { useVisualizationSync } from '@/hooks/useVisualizationSync'
import { useAgentInfoSync } from '@/hooks/useAgentInfoSync'
import { useBuildingMappingStore } from '@/store/useBuildingMappingStore'

const ACTIVITY_STATUS_LABEL: Record<AgentActivityStatus, string> = {
  spawning: '진입 중',
  working: '작업 중',
  resting: '휴식 중',
  inactive: '비활성',
}

const ACTIVITY_STATUS_CLASS: Record<AgentActivityStatus, string> = {
  spawning: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30',
  working: 'bg-blue-500/20 text-blue-300 border border-blue-500/30',
  resting: 'bg-green-500/20 text-green-300 border border-green-500/30',
  inactive: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
}

const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '대기 중',
  in_progress: '진행 중',
  completed: '완료',
  failed: '실패',
}

const TASK_STATUS_CLASS: Record<TaskStatus, string> = {
  pending: 'text-yellow-300',
  in_progress: 'text-blue-300',
  completed: 'text-green-300',
  failed: 'text-red-400',
}

const EMPTY_AGENT_PANELS: ReturnType<typeof agentProfilesToPanelItems> = []

function AgentInfoPanel({ info, onClose }: { info: AgentVisualizationInfo; onClose: () => void }) {
  return (
    <div className="absolute top-4 right-4 z-30 flex w-72 flex-col rounded-2xl border border-white/15 bg-black/80 shadow-2xl backdrop-blur-md">
      {/* 헤더 */}
      <div className="flex items-start justify-between border-b border-white/10 p-4">
        <div className="flex items-center gap-3">
          {info.profileImage ? (
            <img
              src={info.profileImage}
              alt={info.name}
              className="h-10 w-10 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-500/30 text-sm font-bold text-white">
              {info.name[0]}
            </div>
          )}
          <div>
            <p className="text-sm font-semibold text-white">{info.name}</p>
            <p className="text-xs text-white/50">{info.role}</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-lg leading-none text-white/30 transition-colors hover:text-white"
        >
          ×
        </button>
      </div>

      {/* 활동 상태 */}
      <div className="border-b border-white/10 px-4 py-2.5">
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ACTIVITY_STATUS_CLASS[info.activityStatus]}`}
        >
          {ACTIVITY_STATUS_LABEL[info.activityStatus]}
        </span>
      </div>

      {/* 현재 작업 */}
      {info.currentTask && (
        <div className="border-b border-white/10 px-4 py-3">
          <p className="mb-1.5 text-xs tracking-wide text-white/35 uppercase">현재 작업</p>
          <p className="text-sm font-semibold text-white">{info.currentTask.title}</p>
          {info.currentTask.description && (
            <p className="mt-1 line-clamp-2 text-xs text-white/50">
              {info.currentTask.description}
            </p>
          )}
          <span
            className={`mt-1.5 inline-block text-xs ${TASK_STATUS_CLASS[info.currentTask.status]}`}
          >
            ● {TASK_STATUS_LABEL[info.currentTask.status]}
          </span>
        </div>
      )}

      {/* 스킬 */}
      <div className="border-b border-white/10 px-4 py-3">
        <p className="mb-1.5 text-xs tracking-wide text-white/35 uppercase">스킬</p>
        <div className="flex flex-wrap gap-1">
          {info.skills.map((skill) => (
            <span key={skill} className="rounded-md bg-white/10 px-2 py-0.5 text-xs text-white/70">
              {skill}
            </span>
          ))}
        </div>
      </div>

      {/* 작업 내역 */}
      <div className="max-h-48 flex-1 overflow-y-auto px-4 py-3">
        <p className="mb-2 text-xs tracking-wide text-white/35 uppercase">작업 내역</p>
        {info.taskHistory.length === 0 ? (
          <p className="text-xs text-white/30">작업 내역 없음</p>
        ) : (
          <div className="space-y-2">
            {info.taskHistory.map((task) => (
              <div key={task.taskId} className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 text-xs text-green-400">✓</span>
                <div>
                  <p className="text-xs text-white/80">{task.title}</p>
                  {task.completedAt && (
                    <p className="text-xs text-white/30">
                      {new Date(task.completedAt).toLocaleDateString('ko-KR')}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const TOKEN_DETAIL_BARS: {
  key: keyof Pick<
    CommandUsageSummary,
    'inputTokens' | 'outputTokens' | 'cachedInputTokens' | 'reasoningTokens'
  >
  label: string
  description: string
  color: string
}[] = [
  { key: 'inputTokens', label: 'Input', description: '질문', color: '#3b82f6' },
  { key: 'outputTokens', label: 'Output', description: '답변', color: '#22c55e' },
  { key: 'cachedInputTokens', label: 'Cache', description: '재사용 질문', color: '#f59e0b' },
  { key: 'reasoningTokens', label: 'Reasoning', description: 'AI 생각 과정', color: '#a855f7' },
]

function TokenUsageModal({
  summary,
  onClose,
}: {
  summary: CommandUsageSummary
  onClose: () => void
}) {
  const maxVal = Math.max(
    summary.inputTokens,
    summary.outputTokens,
    summary.cachedInputTokens,
    summary.reasoningTokens,
    1,
  )

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* 화이트보드 본체 — 알루미늄 프레임 + 흰 보드 면 */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'relative',
          padding: 14,
          borderRadius: 8,
          background: 'linear-gradient(145deg, #d8d8dc 0%, #b8b8c0 50%, #989aa2 100%)',
          boxShadow:
            '0 24px 60px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.5), inset 0 -1px 0 rgba(0, 0, 0, 0.15)',
          width: 'min(720px, 92vw)',
          animation: 'whiteboardModalIn 0.45s cubic-bezier(0.22, 1.16, 0.36, 1)',
        }}
      >
        <style>{`
          @keyframes whiteboardModalIn {
            from { opacity: 0; transform: translateY(80vh) scale(0.95); }
            60% { opacity: 1; }
            to { opacity: 1; transform: translateY(0) scale(1); }
          }
        `}</style>
        {/* 4 모서리 나사 */}
        {[
          { top: 6, left: 6 },
          { top: 6, right: 6 },
          { bottom: 6, left: 6 },
          { bottom: 6, right: 6 },
        ].map((pos, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'radial-gradient(circle at 30% 30%, #888, #444)',
              boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.4), 0 1px 2px rgba(0,0,0,0.3)',
              ...pos,
            }}
          />
        ))}

        {/* 화이트보드 면 */}
        <div
          style={{
            position: 'relative',
            background:
              'linear-gradient(180deg, #fdfdf8 0%, #f5f5ee 100%), repeating-linear-gradient(0deg, transparent 0, transparent 2px, rgba(0,0,0,0.015) 2px, rgba(0,0,0,0.015) 3px)',
            borderRadius: 4,
            padding: '26px 32px 28px',
            boxShadow: 'inset 0 1px 3px rgba(0, 0, 0, 0.08), inset 0 -1px 2px rgba(0, 0, 0, 0.04)',
            color: '#1a1a1a',
          }}
        >
          {/* 헤더 */}
          <div className="mb-6 flex items-center justify-between">
            <h2
              style={{
                fontSize: 22,
                fontWeight: 800,
                letterSpacing: '0.02em',
                color: '#222',
                textShadow: '0 1px 0 rgba(255,255,255,0.5)',
              }}
            >
              ⊕ 토큰 사용량
            </h2>
            <button
              onClick={onClose}
              aria-label="닫기"
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: 'transparent',
                border: '2px solid #888',
                color: '#555',
                fontSize: 16,
                lineHeight: 1,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#e5e5db'
                e.currentTarget.style.borderColor = '#444'
                e.currentTarget.style.color = '#111'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.borderColor = '#888'
                e.currentTarget.style.color = '#555'
              }}
            >
              ×
            </button>
          </div>

          {/* 막대 — 보드 마커 색감 */}
          <div className="mb-6 flex flex-col gap-4">
            {TOKEN_DETAIL_BARS.map(({ key, label, description, color }) => {
              const value = summary[key]
              const pct = (value / maxVal) * 100
              return (
                <div key={key}>
                  <div className="mb-1.5 flex items-baseline justify-between">
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 700,
                        letterSpacing: '0.08em',
                        color: '#333',
                      }}
                    >
                      {label}
                      <span
                        style={{
                          marginLeft: 8,
                          fontSize: 12,
                          fontWeight: 500,
                          letterSpacing: 0,
                          color: '#777',
                        }}
                      >
                        ({description})
                      </span>
                    </span>
                    <span
                      style={{
                        fontSize: 16,
                        fontWeight: 700,
                        color: '#1a1a1a',
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {value.toLocaleString()}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 13,
                      background: 'rgba(0, 0, 0, 0.06)',
                      borderRadius: 7,
                      overflow: 'hidden',
                      boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.1)',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${pct}%`,
                        background: color,
                        borderRadius: 7,
                        boxShadow: `0 0 6px ${color}55`,
                        transition: 'width 0.7s cubic-bezier(0.34, 1.2, 0.64, 1)',
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {/* 요약 — 화이트보드 위쪽 가로선 + 손글씨 느낌 */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 16,
              paddingTop: 18,
              borderTop: '2px dashed rgba(0, 0, 0, 0.15)',
            }}
          >
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#666' }}>총 토큰</div>
              <div
                style={{
                  marginTop: 4,
                  fontSize: 22,
                  fontWeight: 800,
                  color: '#0f3a8a',
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: '-0.01em',
                }}
              >
                {summary.totalTokens.toLocaleString()}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#666' }}>예상 비용</div>
              <div
                style={{
                  marginTop: 4,
                  fontSize: 22,
                  fontWeight: 800,
                  color: '#0f8a3a',
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: '-0.01em',
                }}
              >
                ${summary.estimatedCostUsd.toFixed(4)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#666' }}>API 호출</div>
              <div
                style={{
                  marginTop: 4,
                  fontSize: 22,
                  fontWeight: 800,
                  color: '#8a3a0f',
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: '-0.01em',
                }}
              >
                {summary.recordCount.toLocaleString()}
              </div>
            </div>
          </div>
        </div>

        {/* 보드 하단 마커 트레이 */}
        <div
          style={{
            position: 'absolute',
            bottom: -6,
            left: '50%',
            transform: 'translateX(-50%)',
            width: '55%',
            height: 10,
            background: 'linear-gradient(180deg, #b8b8c0 0%, #888892 100%)',
            borderRadius: '0 0 4px 4px',
            boxShadow: '0 4px 8px rgba(0, 0, 0, 0.25)',
          }}
        />
      </div>
    </div>
  )
}

// 새 에이전트 추가 시 이 배열에 항목만 추가하면 됩니다.
const AGENT_CONFIGS: AgentConfig[] = [
  {
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
  {
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
  {
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
  {
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
  {
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
      floorLean: { x: 1090, y: 415 },
      meeting: { x: 415, y: 130 },
      calling: { x: 1334, y: 665 },
    },
  },
  {
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
  {
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
  {
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
  {
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
  {
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
  {
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
  },
]

// ── 격자 A* 경로탐색 ─────────────────────────────────────────────────────────
// OBSTACLE_RECTS에 장애물 사각형(맵 픽셀 좌표)을 추가하면 에이전트가 자동으로 피해서 이동합니다.
// 좌표 확인은 맵 클릭 시 나타나는 노란색 디버그 좌표를 활용하세요.
const CELL = 32 // 격자 셀 크기(px) — 32 → 맵을 50×29 격자로 분할
const GRID_W = Math.ceil(1600 / CELL) // 50
const GRID_H = Math.ceil(900 / CELL) // 29
// 에이전트 스프라이트 중심 기준으로 발 위치까지의 오프셋 — 장애물 충돌을 발 기준으로 판정
const FOOT_OFFSET_Y = 70
const NAVMESH_SRC = '/assets/maps/navmesh.png'
const WALKABLE_THRESHOLD = 128

// 두 점 사이의 직선을 격자 셀로 래스터화 (Bresenham's line)
function rasterizeLine(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): { gx: number; gy: number }[] {
  let gx0 = Math.floor(x0 / CELL),
    gy0 = Math.floor(y0 / CELL)
  const gx1 = Math.floor(x1 / CELL),
    gy1 = Math.floor(y1 / CELL)
  const cells: { gx: number; gy: number }[] = []
  const dx = Math.abs(gx1 - gx0),
    dy = Math.abs(gy1 - gy0)
  const sx = gx0 < gx1 ? 1 : -1,
    sy = gy0 < gy1 ? 1 : -1
  let err = dx - dy
  for (;;) {
    cells.push({ gx: gx0, gy: gy0 })
    if (gx0 === gx1 && gy0 === gy1) break
    const e2 = 2 * err
    if (e2 > -dy) {
      err -= dy
      gx0 += sx
    }
    if (e2 < dx) {
      err += dx
      gy0 += sy
    }
  }
  return cells
}

// 책상 장애물 — 목적지가 'desk'일 때는 통과 허용
const DESK_OBSTACLE_RECTS = [
  { x1: 439, y1: 320, x2: 601, y2: 459 },
  { x1: 628, y1: 380, x2: 781, y2: 522 },
  { x1: 808, y1: 451, x2: 961, y2: 602 },
  { x1: 446, y1: 531, x2: 599, y2: 677 },
  { x1: 629, y1: 607, x2: 781, y2: 728 },
]

// 소파·벽 외곽 폴리곤 — 목적지가 'sofa' 또는 'floorLean'일 때는 통과 허용
const SOFA_WALL_OBSTACLE_LINES = [
  { x1: 899, y1: 307, x2: 899, y2: 376 },
  { x1: 1167, y1: 114, x2: 901, y2: 309 },
  { x1: 897, y1: 379, x2: 926, y2: 390 },
  { x1: 928, y1: 390, x2: 1062, y2: 284 },
  { x1: 1062, y1: 284, x2: 1126, y2: 310 },
  { x1: 1127, y1: 307, x2: 1280, y2: 183 },
  { x1: 1280, y1: 179, x2: 1166, y2: 114 },
]

// 테이블 외곽 폴리곤 — 항상 통행 불가
const TABLE_OBSTACLE_LINES = [
  { x1: 742, y1: 89, x2: 673, y2: 139 },
  { x1: 674, y1: 136, x2: 674, y2: 211 },
  { x1: 674, y1: 211, x2: 844, y2: 278 },
  { x1: 841, y1: 276, x2: 916, y2: 220 },
  { x1: 916, y1: 218, x2: 916, y2: 157 },
  { x1: 743, y1: 85, x2: 917, y2: 153 },
]

// 장애물 사각형 목록
const OBSTACLE_RECTS: { x1: number; y1: number; x2: number; y2: number }[] = [
  ...DESK_OBSTACLE_RECTS,
  { x1: 77, y1: 351, x2: 379, y2: 579 }, // 왼쪽 벽
  { x1: 1415, y1: 467, x2: 1559, y2: 703 }, // 엘리베이터
]

const OBSTACLE_GRID: boolean[][] = (() => {
  const g: boolean[][] = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(false))
  for (const r of OBSTACLE_RECTS)
    for (let gy = Math.floor(r.y1 / CELL); gy <= Math.floor(r.y2 / CELL); gy++)
      for (let gx = Math.floor(r.x1 / CELL); gx <= Math.floor(r.x2 / CELL); gx++)
        if (gy >= 0 && gy < GRID_H && gx >= 0 && gx < GRID_W) g[gy][gx] = true
  for (const l of [...SOFA_WALL_OBSTACLE_LINES, ...TABLE_OBSTACLE_LINES])
    for (const cell of rasterizeLine(l.x1, l.y1, l.x2, l.y2))
      if (cell.gy >= 0 && cell.gy < GRID_H && cell.gx >= 0 && cell.gx < GRID_W)
        g[cell.gy][cell.gx] = true
  return g
})()

function imageToObstacleGrid(img: HTMLImageElement): boolean[][] {
  const canvas = document.createElement('canvas')
  canvas.width = 1600
  canvas.height = 900

  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return OBSTACLE_GRID

  ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
  const grid: boolean[][] = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(true))
  const sampleOffsets = [
    [0.5, 0.5],
    [0.25, 0.25],
    [0.75, 0.25],
    [0.25, 0.75],
    [0.75, 0.75],
  ] as const

  for (let gy = 0; gy < GRID_H; gy++) {
    for (let gx = 0; gx < GRID_W; gx++) {
      let walkableSamples = 0

      for (const [ox, oy] of sampleOffsets) {
        const px = Math.min(canvas.width - 1, Math.round((gx + ox) * CELL))
        const py = Math.min(canvas.height - 1, Math.round((gy + oy) * CELL))
        const [r, g, b, a] = ctx.getImageData(px, py, 1, 1).data
        const brightness = (r + g + b) / 3
        if (a > 0 && brightness >= WALKABLE_THRESHOLD) walkableSamples++
      }

      grid[gy][gx] = walkableSamples < 3
    }
  }

  return grid
}

function isWalkableCell(grid: boolean[][], gx: number, gy: number): boolean {
  return gy >= 0 && gy < GRID_H && gx >= 0 && gx < GRID_W && !grid[gy][gx]
}

function findNearestWalkableCell(
  grid: boolean[][],
  gx: number,
  gy: number,
): { x: number; y: number } {
  if (isWalkableCell(grid, gx, gy)) return { x: gx, y: gy }

  for (let radius = 1; radius < Math.max(GRID_W, GRID_H); radius++) {
    let best: { x: number; y: number; dist: number } | null = null

    for (let y = gy - radius; y <= gy + radius; y++) {
      for (let x = gx - radius; x <= gx + radius; x++) {
        if (Math.abs(x - gx) !== radius && Math.abs(y - gy) !== radius) continue
        if (!isWalkableCell(grid, x, y)) continue

        const dist = (x - gx) * (x - gx) + (y - gy) * (y - gy)
        if (!best || dist < best.dist) best = { x, y, dist }
      }
    }

    if (best) return { x: best.x, y: best.y }
  }

  return { x: gx, y: gy }
}

function cellToMapPoint(cell: { x: number; y: number }): { x: number; y: number } {
  return {
    x: cell.x * CELL + CELL / 2,
    y: cell.y * CELL + CELL / 2 - FOOT_OFFSET_Y,
  }
}

function samePoint(a: { x: number; y: number }, b: { x: number; y: number }): boolean {
  return Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) < 1
}

function canWalkStraight(
  from: { x: number; y: number },
  to: { x: number; y: number },
  grid: boolean[][],
): boolean {
  const cells = rasterizeLine(from.x, from.y + FOOT_OFFSET_Y, to.x, to.y + FOOT_OFFSET_Y)
  return cells.every(({ gx, gy }) => isWalkableCell(grid, gx, gy))
}

function smoothPath(
  pts: { x: number; y: number }[],
  grid: boolean[][],
  from: { x: number; y: number },
  to: { x: number; y: number },
): { x: number; y: number }[] {
  const route = [from, ...pts, to]
  const out: { x: number; y: number }[] = []
  let anchor = 0

  while (anchor < route.length - 1) {
    let next = route.length - 1
    while (next > anchor + 1 && !canWalkStraight(route[anchor], route[next], grid)) next--
    out.push(route[next])
    anchor = next
  }

  return out
}

function findPath(
  from: { x: number; y: number },
  to: { x: number; y: number },
  passableRects?: { x1: number; y1: number; x2: number; y2: number }[],
  baseGrid?: boolean[][],
  passableLines?: { x1: number; y1: number; x2: number; y2: number }[],
): { x: number; y: number }[] {
  const sx = Math.floor(from.x / CELL)
  const sy = Math.floor((from.y + FOOT_OFFSET_Y) / CELL)
  const ex = Math.floor(to.x / CELL)
  const ey = Math.floor((to.y + FOOT_OFFSET_Y) / CELL)
  const baseG = baseGrid ?? OBSTACLE_GRID
  const grid = baseG.map((r) => [...r])

  // 목적지 셀은 항상 통과 가능 — navmesh에서 목적지가 장애물 내부여도 도달 가능

  if (passableRects?.length) {
    for (const r of passableRects)
      for (let gy = Math.floor(r.y1 / CELL); gy <= Math.floor(r.y2 / CELL); gy++)
        for (let gx = Math.floor(r.x1 / CELL); gx <= Math.floor(r.x2 / CELL); gx++)
          if (gy >= 0 && gy < GRID_H && gx >= 0 && gx < GRID_W) grid[gy][gx] = false
  }
  if (passableLines?.length) {
    for (const l of passableLines)
      for (const cell of rasterizeLine(l.x1, l.y1, l.x2, l.y2))
        if (cell.gy >= 0 && cell.gy < GRID_H && cell.gx >= 0 && cell.gx < GRID_W)
          grid[cell.gy][cell.gx] = false
  }

  const start = findNearestWalkableCell(grid, sx, sy)
  const end = findNearestWalkableCell(grid, ex, ey)
  const pathTarget = cellToMapPoint(end)
  if (start.x === end.x && start.y === end.y) return samePoint(pathTarget, to) ? [] : [pathTarget]

  type N = { x: number; y: number; g: number; h: number; prev: N | null }
  const key = (x: number, y: number) => y * GRID_W + x
  const open = new Map<number, N>()
  const closed = new Set<number>()
  open.set(key(start.x, start.y), {
    x: start.x,
    y: start.y,
    g: 0,
    h: Math.hypot(start.x - end.x, start.y - end.y),
    prev: null,
  })

  const DIRS = [
    [0, 1],
    [0, -1],
    [1, 0],
    [-1, 0],
    [1, 1],
    [1, -1],
    [-1, 1],
    [-1, -1],
  ]
  const COST = [1, 1, 1, 1, 1.41, 1.41, 1.41, 1.41]

  let iters = 0
  while (open.size > 0 && iters++ < 10000) {
    let cur: N | null = null
    for (const n of open.values()) if (!cur || n.g + n.h < cur.g + cur.h) cur = n
    if (!cur) break
    open.delete(key(cur.x, cur.y))
    closed.add(key(cur.x, cur.y))

    if (cur.x === end.x && cur.y === end.y) {
      const pts: { x: number; y: number }[] = []
      // cur(목적지 셀 중심)는 제외 — allStops에서 실제 목적지 좌표가 추가되므로 여분 걸음 방지
      let n: N | null = cur.prev
      while (n?.prev) {
        pts.push({ x: n.x * CELL + CELL / 2, y: n.y * CELL + CELL / 2 - FOOT_OFFSET_Y })
        n = n.prev
      }
      return smoothPath(pts.reverse(), grid, from, pathTarget)
    }

    for (let d = 0; d < 8; d++) {
      const nx = cur.x + DIRS[d][0]
      const ny = cur.y + DIRS[d][1]
      if (nx < 0 || nx >= GRID_W || ny < 0 || ny >= GRID_H) continue
      if (grid[ny][nx]) continue
      if (DIRS[d][0] !== 0 && DIRS[d][1] !== 0 && (grid[cur.y][nx] || grid[ny][cur.x])) continue
      const k = key(nx, ny)
      if (closed.has(k)) continue
      const ng = cur.g + COST[d]
      const existing = open.get(k)
      if (!existing || ng < existing.g) {
        const dx1 = nx - end.x
        const dy1 = ny - end.y
        // 타이브레이킹: 시작→목적지 직선 방향에 가까운 경로를 우선 선택해 지그재그 억제
        const cross = Math.abs(dx1 * (start.y - end.y) - (start.x - end.x) * dy1)
        open.set(k, { x: nx, y: ny, g: ng, h: Math.hypot(dx1, dy1) + cross * 0.001, prev: cur })
      }
    }
  }
  return []
}

const WALK_SPEED = 100
const FRAME_DURATIONS = [300, 120, 300, 120] as const
const AGENT_BLOCK_RADIUS_CELLS = 1
const AGENT_COLLISION_RADIUS = 90
const SPOT_OCCUPIED_RADIUS = 40 // 자리 점유 판정 반경 (소파 두 자리 간격 ~51px보다 작아야 함)

// 책상 대기 줄 — 책상이 점유 중일 때 (880, 640)부터 순서대로 80px 간격으로 줄서기
const DESK_WAIT_QUEUE: { x: number; y: number }[] = Array.from({ length: 10 }, (_, i) => ({
  x: 880 + i * 80,
  y: 640,
}))

// 맵 상의 소파 자리 2곳 — 휴식 버튼 클릭 시 빈 자리부터 배정
const SOFA_SPOTS: { x: number; y: number }[] = [
  { x: 1185, y: 205 },
  { x: 1140, y: 230 },
]

const DESTINATION_MAP: Record<UIDestination, { targetState: SittingState; label: string }> = {
  desk: { targetState: 'sitting_desk', label: '책상' },
  rest: { targetState: 'sitting_sofa', label: '휴식' }, // 런타임에 sofa/floorLean 으로 오버라이드
  meeting: { targetState: 'sitting_meeting', label: '회의' },
  calling: { targetState: 'sitting_calling', label: '전화' },
  work: { targetState: 'sitting_work', label: '작업' },
}

function calcDuration(from: { x: number; y: number }, to: { x: number; y: number }): number {
  const dx = to.x - from.x
  const dy = to.y - from.y
  return Math.max(1, Math.sqrt(dx * dx + dy * dy) / WALK_SPEED)
}

function pointToFootCell(point: { x: number; y: number }): { x: number; y: number } {
  return {
    x: Math.floor(point.x / CELL),
    y: Math.floor((point.y + FOOT_OFFSET_Y) / CELL),
  }
}

function withAgentBlockers(
  baseGrid: boolean[][],
  agents: AgentRuntime[],
  movingAgentId: string,
): boolean[][] {
  const grid = baseGrid.map((row) => [...row])

  for (const agent of agents) {
    if (agent.config.id === movingAgentId) continue

    const foot = pointToFootCell(agent.position)
    for (
      let gy = foot.y - AGENT_BLOCK_RADIUS_CELLS;
      gy <= foot.y + AGENT_BLOCK_RADIUS_CELLS;
      gy++
    ) {
      for (
        let gx = foot.x - AGENT_BLOCK_RADIUS_CELLS;
        gx <= foot.x + AGENT_BLOCK_RADIUS_CELLS;
        gx++
      ) {
        if (gy >= 0 && gy < GRID_H && gx >= 0 && gx < GRID_W) grid[gy][gx] = true
      }
    }
  }

  return grid
}

function isOccupiedByAnotherAgent(
  point: { x: number; y: number },
  agents: AgentRuntime[],
  movingAgentId: string,
): boolean {
  return agents.some((agent) => {
    if (agent.config.id === movingAgentId) return false
    return (
      Math.hypot(agent.position.x - point.x, agent.position.y - point.y) < AGENT_COLLISION_RADIUS
    )
  })
}

// 해당 자리가 점유 중인지 확인
// — 이미 정착한 에이전트 OR 동일 자리를 향해 이동 중인 에이전트 모두 점유로 간주
function isSpotOccupied(
  spot: { x: number; y: number },
  agents: AgentRuntime[],
  excludeId: string,
): boolean {
  return agents.some((a) => {
    if (a.config.id === excludeId) return false
    // 정착(앉거나 대기) 에이전트
    if (
      a.state !== 'idle' &&
      a.state !== 'walking' &&
      Math.hypot(a.position.x - spot.x, a.position.y - spot.y) < SPOT_OCCUPIED_RADIUS
    )
      return true
    // 동시에 같은 자리로 이동 중인 에이전트 — 중복 배정 방지
    if (
      a.state === 'walking' &&
      a.targetPosition != null &&
      Math.hypot(a.targetPosition.x - spot.x, a.targetPosition.y - spot.y) < SPOT_OCCUPIED_RADIUS
    )
      return true
    return false
  })
}

const ALL_AGENT_SLOT_IDS = [
  'agent01',
  'agent02',
  'agent03',
  'agent04',
  'agent05',
  'agent06',
  'agent07',
  'agent08',
  'agent09',
  'agent10',
]

function buildProfileIdSpriteMap(
  panels: Array<{ agent: { profileId?: string; spriteId?: string } }>,
): Record<string, string> {
  const map: Record<string, string> = {}
  const usedSlots = new Set<string>()

  for (const panel of panels) {
    if (panel.agent.profileId && panel.agent.spriteId) {
      map[panel.agent.profileId] = panel.agent.spriteId
      usedSlots.add(panel.agent.spriteId)
    }
  }

  for (const panel of panels) {
    if (!panel.agent.profileId || map[panel.agent.profileId]) continue
    const slot = ALL_AGENT_SLOT_IDS.find((s) => !usedSlots.has(s))
    if (!slot) break
    map[panel.agent.profileId] = slot
    usedSlots.add(slot)
  }

  return map
}

function playSpawnSound() {
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
    // 페이지 내 이동으로 진입한 경우 AudioContext가 이미 running 상태이므로 즉시 재생됨
    // 직접 URL 접근 시 브라우저가 차단하면 소리 없이 무시
    void ctx.resume().then(play)
  } catch {
    // AudioContext 미지원 환경 무시
  }
}

export function AgentStatusPage() {
  const { sessionId } = useParams()
  const agents = useAgentVisualizationStore((s) => s.agentRuntimes)
  const setAgents = useAgentVisualizationStore((s) => s.setAgentRuntimes)
  const addSpawnedKey = useAgentVisualizationStore((s) => s.addSpawnedKey)
  const [navmeshGrid, setNavmeshGrid] = useState<boolean[][] | null>(null)
  // 세션 에이전트 패널이 로드 완료되었는지 — 로딩 스피너 표시와 일괄 spawn 시점 판단에 사용
  const [agentsLoaded, setAgentsLoaded] = useState(false)
  const [spawningIds, setSpawningIds] = useState<ReadonlySet<string>>(new Set())
  const [tokenUsageSummary, setTokenUsageSummary] = useState<CommandUsageSummary | null>(null)
  const [tokenModalOpen, setTokenModalOpen] = useState(false)
  // 팀장(CEO) 클릭 시 화면에 띄우는 라디얼 메뉴 — clientX/clientY 는 viewport 좌표
  const [ceoMenu, setCeoMenu] = useState<{ x: number; y: number } | null>(null)
  // 명령하기 다이얼로그 열림 여부 — 라디얼 메뉴에서 "명령하기" 선택 시 true
  const [commandDialogOpen, setCommandDialogOpen] = useState(false)

  // 층 이동 — 건물 매핑 기반
  const navigate = useNavigate()
  const location = useLocation()
  const mappingsByFloor = useBuildingMappingStore((s) => s.mappingsByFloor)
  const fetchMappings = useBuildingMappingStore((s) => s.fetchMappings)
  const [floorNavHovered, setFloorNavHovered] = useState(false)

  useEffect(() => {
    void fetchMappings()
  }, [fetchMappings])

  // [디버깅용 임시] store 노출
  useEffect(() => {
    if (typeof window !== 'undefined') {
      ;(window as unknown as { __vizStore?: unknown }).__vizStore = useAgentVisualizationStore
      ;(window as unknown as { __taskStore?: unknown }).__taskStore = useTaskRunStore
    }
  }, [])

  useEffect(() => {
    void getCommandUsage({})
      .then((d) => setTokenUsageSummary(d.summary))
      .catch(() => {
        // 임시 mock — API 연동 전 화이트보드 차트 미리보기용
        setTokenUsageSummary({
          inputTokens: 8400,
          outputTokens: 3200,
          cachedInputTokens: 1500,
          reasoningTokens: 900,
          totalTokens: 11600,
          estimatedCostUsd: 0.0842,
          currency: 'USD',
          recordCount: 47,
        })
      })
  }, [])
  const runtimeGridRef = useRef<boolean[][]>(OBSTACLE_GRID)
  const walkTimersRef = useRef<Record<string, ReturnType<typeof setTimeout> | undefined>>({})

  const initialSessionAgentProfileIdsRef = useRef<Set<string>>(new Set())
  const capturedInitialAgentPanelsRef = useRef(false)

  const { agentInfoMap, selectedAgentId, selectAgent } = useAgentVisualizationStore()
  const accessToken = useAuthStore((s) => s.accessToken)
  const setAgentPanelsForSession = useSessionStore((s) => s.setAgentPanelsForSession)

  // 세션 전환(sessionId 변경) 시에만 에이전트 상태를 초기화한다.
  // 같은 세션 재진입이면 clearVisualizationState 내부에서 no-op 처리되어 위치가 보존된다.
  // 언마운트 시에는 walk 타이머만 정리하고 상태는 유지 — 돌아왔을 때 그대로 표시된다.
  useEffect(() => {
    Object.values(walkTimersRef.current).forEach((t) => clearTimeout(t))
    walkTimersRef.current = {}
    initialSessionAgentProfileIdsRef.current = new Set()
    capturedInitialAgentPanelsRef.current = false
    // sessionId 가 바뀐 외부 트리거에 동기화하기 위한 reset — listSessionAgents 다시 호출되어
    // 응답 오면 true 가 된다. 다른 setState 가 아니라 sessionId 변화에 정확히 1회만 발생.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAgentsLoaded(false)
    useAgentVisualizationStore.getState().clearVisualizationState(sessionId ?? null)
    return () => {
      Object.values(walkTimersRef.current).forEach((t) => clearTimeout(t))
      walkTimersRef.current = {}
    }
  }, [sessionId])

  useEffect(() => {
    if (!sessionId || sessionId.startsWith('pending_session_') || accessToken === null) return

    let cancelled = false
    void useAgentCacheStore
      .getState()
      .fetchSessionAgents(sessionId)
      .then((profiles) => {
        if (cancelled) return
        const panels = agentProfilesToPanelItems(profiles)
        const spawnedKeys = useAgentVisualizationStore.getState().spawnedKeys
        const hasSpawnedSubAgent = spawnedKeys.some((id) => id !== 'ceo')
        const fetchedProfileIdMap = buildProfileIdSpriteMap(panels)
        const initialProfileIds = hasSpawnedSubAgent
          ? profiles
              .map((profile) => profile.profileId)
              .filter((profileId) => spawnedKeys.includes(fetchedProfileIdMap[profileId]))
          : profiles.map((profile) => profile.profileId)
        initialSessionAgentProfileIdsRef.current = new Set(initialProfileIds)
        capturedInitialAgentPanelsRef.current = true
        setAgentPanelsForSession(sessionId, panels)
        setAgentsLoaded(true)
      })
      .catch(() => {
        // 사이드바/서브에이전트 패널에서도 동일 데이터를 불러오므로 실패 시 기존 캐시를 유지한다.
        // 다만 시각화는 빈 상태에서 무한 로딩하면 안 되므로 로딩 플래그는 풀어준다.
        if (!cancelled) setAgentsLoaded(true)
      })

    return () => {
      cancelled = true
    }
  }, [accessToken, sessionId, setAgentPanelsForSession])

  useEffect(() => {
    let cancelled = false
    const img = new Image()

    img.onload = () => {
      if (!cancelled) setNavmeshGrid(imageToObstacleGrid(img))
    }
    img.onerror = () => {
      if (!cancelled) setNavmeshGrid(null)
    }
    img.src = NAVMESH_SRC

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    runtimeGridRef.current = (navmeshGrid ?? OBSTACLE_GRID).map((r) => [...r])
    if (navmeshGrid === null) return
    // navmesh 로드 완료 — OBSTACLE_GRID로 이미 이동 중이던 에이전트가 있으면
    // navmesh 기준으로 경로를 재계산해 장애물 회피를 정확히 적용한다.
    setAgents((prev) => {
      if (!prev.some((a) => a.state === 'walking')) return prev
      return prev.map((a) => {
        if (a.state !== 'walking' || !a.targetPosition) return a
        const pathGrid = withAgentBlockers(runtimeGridRef.current, prev, a.config.id)
        const newWaypoints = findPath(a.position, a.targetPosition, undefined, pathGrid, undefined)
        const first = newWaypoints[0]
        if (!first) return a
        return {
          ...a,
          position: { ...first },
          transitionDuration: calcDuration(a.position, first),
          pendingWaypoints: newWaypoints.slice(1),
        }
      })
    })
  }, [navmeshGrid, setAgents])

  const clearWalkTimer = (agentId: string) => {
    const timer = walkTimersRef.current[agentId]
    if (timer !== undefined) {
      clearTimeout(timer)
      delete walkTimersRef.current[agentId]
    }
  }

  // 세션의 서브에이전트 패널 목록 — 추가·삭제 시 자동으로 스폰/연동 트리거
  const agentPanels = useSessionStore((s) =>
    sessionId ? (s.agentPanelsBySessionId[sessionId] ?? EMPTY_AGENT_PANELS) : EMPTY_AGENT_PANELS,
  )

  useEffect(() => {
    if (capturedInitialAgentPanelsRef.current) return
    const profileIds = agentPanels
      .map((panel) => panel.agent.profileId)
      .filter((profileId): profileId is string => typeof profileId === 'string')
    if (profileIds.length === 0) return
    const spawnedKeys = useAgentVisualizationStore.getState().spawnedKeys
    const hasSpawnedSubAgent = spawnedKeys.some((id) => id !== 'ceo')
    const currentProfileIdMap = buildProfileIdSpriteMap(agentPanels)
    initialSessionAgentProfileIdsRef.current = new Set(
      hasSpawnedSubAgent
        ? profileIds.filter((profileId) => spawnedKeys.includes(currentProfileIdMap[profileId]))
        : profileIds,
    )
    capturedInitialAgentPanelsRef.current = true
  }, [agentPanels])

  // profileId → spriteId(agentXX) 매핑 — task run의 actorAgent.profileId로 시각화 ID 조회
  const profileIdMap = useMemo<Record<string, string>>(() => {
    return buildProfileIdSpriteMap(agentPanels)
  }, [agentPanels])

  const currentFloor = useMemo(() => {
    for (const [floor, sid] of Object.entries(mappingsByFloor)) {
      if (sid === sessionId) return Number(floor)
    }
    return null
  }, [mappingsByFloor, sessionId])

  // 세션의 모든 에이전트가 준비되면 한 번에 spawn 한다.
  // - listSessionAgents 응답 완료 (agentsLoaded=true)
  // - navmesh 로드 완료
  // - 아직 아무도 spawn 되지 않은 상태 (와리가리 후 재진입 시 중복 spawn 방지)
  // CEO 는 책상에, 서브에이전트는 소파(최대 2명) / 바닥 휴식 자리에 sitting 상태로 즉시 배치한다.
  // 한 번에 모두 sitting 으로 mount 되므로 CSS transition 의 from 좌표 없음 문제(walking 박힘)가 발생하지 않는다.
  // 이후 useVisualizationSync 가 task 를 감지하면 그제야 walking 으로 전환 — 그건 update 라서 transition 정상 동작.
  useEffect(() => {
    if (!agentsLoaded || navmeshGrid === null) return
    if (useAgentVisualizationStore.getState().agentRuntimes.length > 0) return

    const subSpriteIds = Object.values(profileIdMap).filter((spriteId) =>
      AGENT_CONFIGS.some((c) => c.id === spriteId && c.id !== 'ceo'),
    )

    const ceoConfig = AGENT_CONFIGS.find((c) => c.id === 'ceo')
    if (!ceoConfig) return
    const ceoDeskPos = ceoConfig.destinations.desk ?? ceoConfig.initialPosition

    const newAgents: AgentRuntime[] = [
      {
        config: ceoConfig,
        position: { ...ceoDeskPos },
        state: 'sitting_desk',
        targetState: 'sitting_desk',
        walkFrame: 0,
        transitionDuration: 0,
        pendingWaypoints: [],
        targetPosition: null,
        standWaitTarget: null,
        facingRight: false,
      },
    ]

    for (const spriteId of subSpriteIds) {
      const config = AGENT_CONFIGS.find((c) => c.id === spriteId)
      if (!config) continue
      const freeSofa = SOFA_SPOTS.find((spot) => !isSpotOccupied(spot, newAgents, spriteId))
      const position = freeSofa ?? config.destinations.floorLean ?? config.initialPosition
      const state = (freeSofa ? 'sitting_sofa' : 'sitting_floor_lean') as SittingState
      newAgents.push({
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
      })
    }

    setAgents(newAgents)
    addSpawnedKey('ceo')
    for (const spriteId of subSpriteIds) {
      addSpawnedKey(spriteId)
    }
  }, [agentsLoaded, navmeshGrid, profileIdMap, setAgents, addSpawnedKey])

  const handleMove = (agentId: string, rawDestination: UIDestination) => {
    // 팀장 전용 목적지 매핑
    //   작업 중(desk)       → work 좌표에서 ceo_work 스프라이트
    //   완료/실패(rest/calling) → desk 좌표에서 ceo_desk 스프라이트
    //   meeting             → explain 좌표로 걸어 이동 (서브 2명 이상 작업 시 랜덤 타이머로 호출)
    //   그 외               → work (안전 폴백 — ceo는 work/desk/meeting만 허용)
    const destination: UIDestination =
      agentId === 'ceo' && rawDestination === 'desk'
        ? 'work'
        : agentId === 'ceo' && (rawDestination === 'rest' || rawDestination === 'calling')
          ? 'desk'
          : agentId === 'ceo' && rawDestination !== 'meeting' && rawDestination !== 'work'
            ? 'work'
            : rawDestination

    // 미등록 에이전트 자동 스폰
    const spawnedKeys = useAgentVisualizationStore.getState().spawnedKeys
    if (!spawnedKeys.includes(agentId) && AGENT_CONFIGS.some((c) => c.id === agentId)) {
      addSpawnedKey(agentId)

      if (agentId === 'ceo' && rawDestination === 'desk') {
        // 팀장 첫 등장(작업 중): ceo_work에 직접 배치 + 세션 서브에이전트 휴게공간 동시 배치
        const unspawnedSubs = Object.entries(profileIdMap).filter(
          ([, spriteId]) =>
            !spawnedKeys.includes(spriteId) && AGENT_CONFIGS.some((c) => c.id === spriteId),
        )
        unspawnedSubs.forEach(([, spriteId]) => addSpawnedKey(spriteId))
        setAgents((prev) => {
          const ceoConfig = AGENT_CONFIGS.find((c) => c.id === 'ceo')!
          const workPos = ceoConfig.destinations.work!
          const ceoRuntime: AgentRuntime = {
            config: ceoConfig,
            position: { ...workPos },
            state: 'sitting_work',
            targetState: 'sitting_work',
            walkFrame: 0,
            transitionDuration: 0,
            pendingWaypoints: [],
            targetPosition: null,
            standWaitTarget: null,
            facingRight: false,
          }
          const subRuntimes: AgentRuntime[] = []
          for (const [, spriteId] of unspawnedSubs) {
            const config = AGENT_CONFIGS.find((c) => c.id === spriteId)
            if (!config || prev.some((a) => a.config.id === spriteId)) continue
            const all = [...prev, ceoRuntime, ...subRuntimes]
            const freeSofa = SOFA_SPOTS.find((spot) => !isSpotOccupied(spot, all, spriteId))
            const position = freeSofa ?? config.destinations.floorLean ?? config.initialPosition
            const state = (freeSofa ? 'sitting_sofa' : 'sitting_floor_lean') as SittingState
            subRuntimes.push({
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
            })
          }
          return [...prev, ceoRuntime, ...subRuntimes]
        })
        // 팀장만 전구 표시 + 효과음
        setSpawningIds((s) => new Set([...s, 'ceo']))
        setTimeout(() => {
          setSpawningIds((s) => {
            const n = new Set(s)
            n.delete('ceo')
            return n
          })
        }, 2500)
        playSpawnSound()
        return
      }

      // 서브에이전트('+' 버튼) 첫 등장: 엘리베이터 입장 + 전구
      setSpawningIds((s) => new Set([...s, agentId]))
      setTimeout(() => {
        setSpawningIds((s) => {
          const n = new Set(s)
          n.delete(agentId)
          return n
        })
      }, 2500)
    }

    setAgents((prevAgents) => {
      // 아직 agents 배열에 없으면 initialPosition에 먼저 렌더링한 뒤 다음 프레임에서 이동 시작
      // — 같은 렌더에서 spawn + walk를 동시에 처리하면 CSS transform 전환의 "from" 상태가 없어
      //   onTransitionEnd가 발화하지 않아 walking 애니메이션이 멈추지 않는다.
      if (!prevAgents.some((a) => a.config.id === agentId)) {
        const config = AGENT_CONFIGS.find((c) => c.id === agentId)
        if (!config) return prevAgents
        if (agentId === 'ceo' && rawDestination === 'rest') {
          const deskPosition = config.destinations.desk
          if (!deskPosition) return prevAgents
          return [
            ...prevAgents,
            {
              config,
              position: { ...deskPosition },
              state: 'sitting_desk' as const,
              targetState: 'sitting_desk' as const,
              walkFrame: 0 as const,
              transitionDuration: 0,
              pendingWaypoints: [],
              targetPosition: null,
              standWaitTarget: null,
              facingRight: false,
            },
          ]
        }
        if (agentId === 'ceo') {
          // CEO는 절대 initialPosition에서 걸어 들어오지 않는다 — 직접 work에 배치
          const workPos = config.destinations.work ?? config.destinations.desk
          if (!workPos) return prevAgents
          return [
            ...prevAgents,
            {
              config,
              position: { ...workPos },
              state: 'sitting_work' as const,
              targetState: 'sitting_work' as const,
              walkFrame: 0 as const,
              transitionDuration: 0,
              pendingWaypoints: [],
              targetPosition: null,
              standWaitTarget: null,
              facingRight: false,
            },
          ]
        }
        // idle 상태로 추가만 한다 — 별도 idleAgentIds useEffect 가 다음 paint 사이클(RAF 2회)에 handleMove 를
        // 호출해 walking 으로 전환한다. 보통은 일괄 spawn (위 useEffect) 가 먼저 발화해 이 분기 자체에 들어오지 않지만,
        // race condition 으로 미리 spawn 안 된 채 useVisualizationSync 등 외부 호출이 먼저 일어나면 fallback 으로 동작.
        return [
          ...prevAgents,
          {
            config,
            position: { ...config.initialPosition },
            state: 'idle' as const,
            targetState: 'sitting_desk' as const,
            walkFrame: 0 as const,
            transitionDuration: 3,
            pendingWaypoints: [],
            targetPosition: null,
            standWaitTarget: null,
            facingRight: false,
          },
        ]
      }
      const prev = prevAgents

      const agent = prev.find((a) => a.config.id === agentId)
      if (!agent) return prev
      if (agentId === 'ceo' && rawDestination === 'rest') {
        const deskPosition = agent.config.destinations.desk
        if (!deskPosition) return prev
        const alreadyAtDesk =
          agent.state === 'sitting_desk' &&
          agent.targetState === 'sitting_desk' &&
          Math.abs(agent.position.x - deskPosition.x) < 1 &&
          Math.abs(agent.position.y - deskPosition.y) < 1
        clearWalkTimer('ceo')
        if (!alreadyAtDesk) playSpawnSound()
        return prev.map((a) =>
          a.config.id === 'ceo'
            ? {
                ...a,
                position: { ...deskPosition },
                state: 'sitting_desk',
                targetState: 'sitting_desk',
                walkFrame: 0,
                transitionDuration: 0,
                pendingWaypoints: [],
                targetPosition: null,
                standWaitTarget: null,
                facingRight: false,
              }
            : a,
        )
      }
      // CEO work/desk 전환은 현재 상태·이동 중 여부와 무관하게 항상 즉시 텔레포트
      if (agentId === 'ceo' && (destination === 'desk' || destination === 'work')) {
        const nextPosition = agent.config.destinations[destination as Destination]
        const nextState = DESTINATION_MAP[destination as UIDestination]?.targetState
        if (!nextPosition || !nextState) return prev
        const alreadyThere =
          agent.state === nextState && !agent.targetPosition && agent.pendingWaypoints.length === 0
        clearWalkTimer('ceo')
        if (alreadyThere) return prev
        return prev.map((a) =>
          a.config.id === 'ceo'
            ? {
                ...a,
                position: { ...nextPosition },
                state: nextState,
                targetState: nextState,
                walkFrame: 0,
                transitionDuration: 0,
                pendingWaypoints: [],
                targetPosition: null,
                standWaitTarget: null,
              }
            : a,
        )
      }

      if (agent.state === 'walking') {
        // 이동 중 목적지 변경: 경로는 유지하고 도착 시 전환할 targetState만 갱신
        // rest는 소파 빈 자리 탐색이 필요해 mid-walk 갱신 불가 — 나머지만 처리
        // 휴게 목적지(소파/플로어)로 이동 중에는 targetState 덮어쓰기 금지 — sitting_desk가 소파 좌표에 배치되는 문제 방지
        if (destination !== 'rest') {
          const isWalkingToRest =
            agent.targetState === 'sitting_sofa' || agent.targetState === 'sitting_floor_lean'
          if (!isWalkingToRest) {
            const newTargetState = DESTINATION_MAP[destination as UIDestination]?.targetState
            if (newTargetState && agent.targetState !== newTargetState) {
              return prev.map((a) =>
                a.config.id === agentId ? { ...a, targetState: newTargetState } : a,
              )
            }
          }
        }
        return prev
      }

      // 이미 휴게 상태면 아무것도 하지 않음 — 페이지 재진입 시 불필요한 걷기 방지
      if (
        destination === 'rest' &&
        (agent.state === 'sitting_sofa' || agent.state === 'sitting_floor_lean')
      ) {
        return prev
      }

      // ── rest → 소파 빈 자리 우선 배정, 둘 다 차면 floorLean ──────────────
      let internalDest: Destination
      let destPoint: { x: number; y: number }
      if (destination === 'rest') {
        const freeSofaSpot = SOFA_SPOTS.find((spot) => !isSpotOccupied(spot, prev, agentId))
        if (freeSofaSpot) {
          internalDest = 'sofa'
          destPoint = { ...freeSofaSpot }
        } else {
          internalDest = 'floorLean'
          destPoint = { ...agent.config.destinations.floorLean! }
        }
      } else {
        internalDest = destination
        const rawPoint = agent.config.destinations[internalDest]
        if (!rawPoint) return prev
        destPoint = { ...rawPoint }

        // 책상 자리가 점유된 경우 대기 줄 대신 회의 목적지로 바로 전환
        if (internalDest === 'desk' && isSpotOccupied(destPoint, prev, agentId)) {
          internalDest = 'meeting'
          destPoint = { ...agent.config.destinations.meeting! }
        }
      }

      const destConfig = agent.config.destinations[internalDest]!

      // internalDest 에 맞는 실제 앉기 상태
      const resolvedTargetState: SittingState =
        internalDest === 'sofa'
          ? 'sitting_sofa'
          : internalDest === 'floorLean'
            ? 'sitting_floor_lean'
            : DESTINATION_MAP[internalDest as UIDestination].targetState

      // 목적지 자리가 이미 점유 중이면 옆에 서 있는 상태로 전환
      const targetState: SittingState = isSpotOccupied(destPoint, prev, agentId)
        ? 'standing_wait'
        : resolvedTargetState

      const passableRects =
        !navmeshGrid && internalDest === 'desk' ? DESK_OBSTACLE_RECTS : undefined
      const passableLines =
        !navmeshGrid && (internalDest === 'sofa' || internalDest === 'floorLean')
          ? SOFA_WALL_OBSTACLE_LINES
          : undefined

      const pathGrid = withAgentBlockers(runtimeGridRef.current, prev, agentId)

      // standing_wait: 책상이 차 있으면 고정 대기 줄에 순서대로 배정
      let standWaitOrigin: { x: number; y: number } | null = null
      if (targetState === 'standing_wait') {
        standWaitOrigin = { ...destPoint }
        const freeSlot =
          DESK_WAIT_QUEUE.find((spot) => !isSpotOccupied(spot, prev, agentId)) ??
          DESK_WAIT_QUEUE[DESK_WAIT_QUEUE.length - 1]
        destPoint = { ...freeSlot }
      }

      // rest·standing_wait 는 커스텀 waypoints 미사용
      const waypoints =
        (destination !== 'rest' && targetState !== 'standing_wait'
          ? destConfig.waypoints
          : undefined) ??
        findPath(agent.position, destPoint, passableRects, pathGrid, passableLines)

      const lastStop = waypoints[waypoints.length - 1]
      // 소파는 SOFA_SPOTS의 고정 좌표를 항상 사용 — isOccupiedByAnotherAgent 반경(90px)이 소파 두 자리 간격(~51px)보다 커서 좌표가 셀 중심으로 벗어나는 문제 방지
      const finalPosition =
        internalDest !== 'sofa' && lastStop && isOccupiedByAnotherAgent(destPoint, prev, agentId)
          ? lastStop
          : destPoint
      const allStops = waypoints
      const firstStop = allStops[0]
      if (!firstStop) {
        clearWalkTimer(agentId)
        // standing_wait 즉시 배치 시 점유된 자리 방향으로 바라봄
        const arrivalFacing = standWaitOrigin
          ? Math.abs(standWaitOrigin.x - finalPosition.x) > 5
            ? standWaitOrigin.x > finalPosition.x
            : agent.facingRight
          : agent.facingRight
        return prev.map((a) =>
          a.config.id === agentId
            ? {
                ...a,
                position: { ...finalPosition },
                state: targetState,
                targetState,
                walkFrame: 0,
                pendingWaypoints: [],
                targetPosition: null,
                standWaitTarget: standWaitOrigin,
                facingRight: arrivalFacing,
              }
            : a,
        )
      }
      const remaining = allStops.slice(1)
      // 최종 목적지 방향으로 facing 결정 — 웨이포인트마다 좌우 반전 방지
      const overallDx = finalPosition.x - agent.position.x
      const facingRight = Math.abs(overallDx) > CELL ? overallDx > 0 : agent.facingRight

      clearWalkTimer(agentId)

      const scheduleWalkStep = (frame: 0 | 1 | 2 | 3) => {
        walkTimersRef.current[agentId] = setTimeout(() => {
          const next = ((frame + 1) % 4) as 0 | 1 | 2 | 3
          setAgents((p) => p.map((a) => (a.config.id === agentId ? { ...a, walkFrame: next } : a)))
          scheduleWalkStep(next)
        }, FRAME_DURATIONS[frame])
      }
      scheduleWalkStep(0)

      return prev.map((a) =>
        a.config.id === agentId
          ? {
              ...a,
              state: 'walking' as const,
              targetState,
              position: { ...firstStop },
              transitionDuration: calcDuration(agent.position, firstStop),
              pendingWaypoints: remaining,
              targetPosition: { ...finalPosition },
              // standing_wait 도착 시 점유된 자리 방향을 바라보기 위해 원본 좌표 저장
              standWaitTarget: standWaitOrigin,
              facingRight,
            }
          : a,
      )
    })
  }

  useVisualizationSync(handleMove, sessionId, profileIdMap)
  useAgentInfoSync(sessionId, profileIdMap, agentPanels)

  // handleMove는 매 렌더마다 새로 생성되므로 타이머 콜백에서는 항상 최신 버전을 참조
  const handleMoveRef = useRef(handleMove)
  useEffect(() => {
    handleMoveRef.current = handleMove
  })

  // 팀장이 스폰된 상태에서 profileIdMap이 갱신될 때 미스폰 서브에이전트를 휴게공간에 보완 배치
  // — profileIdMap이 늦게 로드되거나(listSessionAgents 지연) '+' 버튼으로 패널이 추가될 때 처리
  // — ceoInSpawnedKeys를 의존성에 두지 않음: addSpawnedKey('ceo')가 동기 리렌더를 유발해
  //   setAgents(팀장) 실행 전에 이 이펙트가 먼저 실행되어 서브에이전트가 팀장보다 먼저 등장하는 문제 방지
  useEffect(() => {
    const store = useAgentVisualizationStore.getState()
    if (!store.spawnedKeys.includes('ceo')) return
    const unspawnedSubs = Object.entries(profileIdMap).filter(
      ([, spriteId]) =>
        !store.spawnedKeys.includes(spriteId) && AGENT_CONFIGS.some((c) => c.id === spriteId),
    )
    if (unspawnedSubs.length === 0) return

    const directRestSubs = unspawnedSubs.filter(
      ([profileId]) =>
        !capturedInitialAgentPanelsRef.current ||
        initialSessionAgentProfileIdsRef.current.has(profileId),
    )
    const elevatorSubs = unspawnedSubs.filter(
      ([profileId]) =>
        capturedInitialAgentPanelsRef.current &&
        !initialSessionAgentProfileIdsRef.current.has(profileId),
    )

    if (directRestSubs.length > 0) {
      directRestSubs.forEach(([, spriteId]) => addSpawnedKey(spriteId))
      setAgents((prev) => {
        const newAgents: AgentRuntime[] = []
        for (const [, spriteId] of directRestSubs) {
          const config = AGENT_CONFIGS.find((c) => c.id === spriteId)
          if (!config || prev.some((a) => a.config.id === spriteId)) continue
          const all = [...prev, ...newAgents]
          const freeSofa = SOFA_SPOTS.find((spot) => !isSpotOccupied(spot, all, spriteId))
          const position = freeSofa ?? config.destinations.floorLean ?? config.initialPosition
          const state = (freeSofa ? 'sitting_sofa' : 'sitting_floor_lean') as SittingState
          newAgents.push({
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
          })
        }
        return [...prev, ...newAgents]
      })
    }

    // 엘리베이터 입장 케이스: 먼저 initialPosition 에 idle 상태로 spawn 만 한다.
    // 같은 commit 에서 walking 까지 시작하면 mount 시점부터 transform 이 목표 좌표라
    // CSS transition 의 from 값이 없고 onTransitionEnd 가 영원히 발화하지 않는다.
    // 별도 useEffect 가 다음 paint 사이클에 handleMove 를 호출해 walking 을 시작한다.
    if (elevatorSubs.length > 0) {
      elevatorSubs.forEach(([, spriteId]) => addSpawnedKey(spriteId))
      setAgents((prev) => {
        const newAgents: AgentRuntime[] = []
        for (const [, spriteId] of elevatorSubs) {
          const config = AGENT_CONFIGS.find((c) => c.id === spriteId)
          if (!config || prev.some((a) => a.config.id === spriteId)) continue
          newAgents.push({
            config,
            position: { ...config.initialPosition },
            state: 'idle',
            targetState: 'sitting_sofa',
            walkFrame: 0,
            transitionDuration: 0,
            pendingWaypoints: [],
            targetPosition: null,
            standWaitTarget: null,
            facingRight: false,
          })
        }
        return [...prev, ...newAgents]
      })
    }
  }, [profileIdMap, setAgents, addSpawnedKey])

  // idle 상태로 spawn 된 에이전트는 브라우저가 실제로 paint 한 후에 walking 으로 전환한다.
  // useEffect 만으로는 React 가 idle commit 과 walking commit 을 한 paint 로 묶을 수 있다.
  // requestAnimationFrame 두 번으로 paint 한 번을 사이에 끼워 CSS transition 의 from 좌표를 보장한다.
  const idleAgentIds = useAgentVisualizationStore((s) =>
    s.agentRuntimes
      .filter((a) => a.state === 'idle')
      .map((a) => a.config.id)
      .join(','),
  )
  useEffect(() => {
    if (idleAgentIds === '') return
    let inner: number | null = null
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        for (const agentId of idleAgentIds.split(',')) {
          handleMoveRef.current(agentId, 'rest')
        }
      })
    })
    return () => {
      cancelAnimationFrame(outer)
      if (inner !== null) cancelAnimationFrame(inner)
    }
  }, [idleAgentIds])

  // 팀장 상태 구독 — explain 타이머 조건 판단에 사용
  const ceoState = useAgentVisualizationStore(
    (s) => s.agentRuntimes.find((a) => a.config.id === 'ceo')?.state,
  )

  // 책상에 있거나 책상으로 이동 중인 서브에이전트 수
  const workingSubCount = useAgentVisualizationStore(
    (s) =>
      s.agentRuntimes.filter(
        (a) =>
          a.config.id !== 'ceo' &&
          (a.state === 'sitting_desk' ||
            (a.state === 'walking' && a.targetState === 'sitting_desk')),
      ).length,
  )

  // 서브 2명 이상 작업 중 + CEO sitting_work → 40~80초 후 explain 좌표로 걸어 이동
  useEffect(() => {
    if (workingSubCount < 2 || ceoState !== 'sitting_work') return
    const delay = 40_000 + Math.random() * 40_000
    const timer = setTimeout(() => {
      const store = useAgentVisualizationStore.getState()
      const ceo = store.agentRuntimes.find((a) => a.config.id === 'ceo')
      const currentSubCount = store.agentRuntimes.filter(
        (a) =>
          a.config.id !== 'ceo' &&
          (a.state === 'sitting_desk' ||
            (a.state === 'walking' && a.targetState === 'sitting_desk')),
      ).length
      if (ceo?.state === 'sitting_work' && currentSubCount >= 2) {
        handleMoveRef.current('ceo', 'meeting')
      }
    }, delay)
    return () => clearTimeout(timer)
  }, [workingSubCount, ceoState])

  // CEO explain 도착 후 15~25초 뒤 work로 즉시 복귀
  useEffect(() => {
    if (ceoState !== 'sitting_meeting') return
    const delay = 15_000 + Math.random() * 10_000
    const timer = setTimeout(() => {
      const ceo = useAgentVisualizationStore
        .getState()
        .agentRuntimes.find((a) => a.config.id === 'ceo')
      if (ceo?.state === 'sitting_meeting') {
        handleMoveRef.current('ceo', 'desk')
      }
    }, delay)
    return () => clearTimeout(timer)
  }, [ceoState])

  const handleAgentArrived = (agentId: string) => {
    setAgents((prev) => {
      const agent = prev.find((a) => a.config.id === agentId)
      if (!agent) return prev

      if (agent.pendingWaypoints.length > 0) {
        const [next, ...rest] = agent.pendingWaypoints
        // facingRight는 워크 시작 시점에 확정 — 경유 웨이포인트마다 재계산 시 방향 좌우 반전 발생
        return prev.map((a) =>
          a.config.id === agentId
            ? {
                ...a,
                position: { ...next },
                transitionDuration: calcDuration(a.position, next),
                pendingWaypoints: rest,
              }
            : a,
        )
      }

      clearWalkTimer(agentId)
      return prev.map((a) => {
        if (a.config.id !== agentId) return a
        // standing_wait 도착 시 저장해둔 목적지 좌표 방향으로 바라봄
        const finalFacing =
          a.targetState === 'standing_wait' && a.standWaitTarget
            ? a.standWaitTarget.x > (a.targetPosition?.x ?? a.position.x)
            : a.facingRight
        return {
          ...a,
          position: a.targetPosition ? { ...a.targetPosition } : a.position,
          state: a.targetState,
          walkFrame: 0,
          pendingWaypoints: [],
          targetPosition: null,
          standWaitTarget: null,
          facingRight: finalFacing,
        }
      })
    })
  }

  const handleFloorNavigate = (floor: number) => {
    const targetSessionId = mappingsByFloor[floor]
    if (!targetSessionId || targetSessionId === sessionId) return
    if (location.pathname.startsWith('/session/')) {
      navigate(`/session/${targetSessionId}/workspace/visualization`)
    } else {
      navigate(`/agent-status/${targetSessionId}`)
    }
  }

  const selectedInfo = selectedAgentId ? agentInfoMap[selectedAgentId] : null

  const isInitializing = !agentsLoaded || navmeshGrid === null

  // 팀장(CEO)은 클릭 시 라디얼 메뉴를 띄우고, 서브에이전트는 기존처럼 즉시 정보 패널을 연다.
  const handleAgentClickWithMenu = (
    agentId: string,
    event: { clientX: number; clientY: number },
  ) => {
    if (agentId === 'ceo') {
      setCeoMenu({ x: event.clientX, y: event.clientY })
      return
    }
    selectAgent(agentId)
  }

  const ceoProfileImage = agentInfoMap.ceo?.profileImage ?? '/assets/agents/ceo/ceo_profile.png'
  const ceoName = agentInfoMap.ceo?.name ?? '팀장 에이전트'

  return (
    <div className="relative flex flex-1 overflow-hidden">
      <OfficeMap
        agents={agents}
        onAgentArrived={handleAgentArrived}
        ceoMode={null}
        onAgentClick={handleAgentClickWithMenu}
        onEmptyClick={() => selectAgent(null)}
        agentInfoMap={agentInfoMap}
        selectedAgentId={selectedAgentId}
        spawningIds={spawningIds}
        tokenUsageSummary={tokenUsageSummary}
        onTokenChartClick={() => setTokenModalOpen(true)}
      />
      {isInitializing && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-black/70 px-6 py-5 shadow-2xl">
            <Loader2 className="h-8 w-8 animate-spin text-white" />
            <p className="text-sm font-medium text-white/90">에이전트를 불러오는 중...</p>
          </div>
        </div>
      )}
      {ceoMenu && (
        <CeoActionMenu
          x={ceoMenu.x}
          y={ceoMenu.y}
          onSelectCommand={() => {
            setCeoMenu(null)
            setCommandDialogOpen(true)
          }}
          onSelectInfo={() => {
            setCeoMenu(null)
            selectAgent('ceo')
          }}
          onClose={() => setCeoMenu(null)}
        />
      )}
      {commandDialogOpen && sessionId !== undefined && (
        <CeoCommandDialog
          sessionId={sessionId}
          ceoName={ceoName}
          ceoProfileImage={ceoProfileImage}
          onClose={() => setCommandDialogOpen(false)}
        />
      )}
      {selectedInfo && <AgentInfoPanel info={selectedInfo} onClose={() => selectAgent(null)} />}
      {tokenModalOpen && tokenUsageSummary && (
        <TokenUsageModal summary={tokenUsageSummary} onClose={() => setTokenModalOpen(false)} />
      )}
      {/* 층 이동 버튼 — 엘리베이터 옆 우측 */}
      {Object.keys(mappingsByFloor).length > 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: '28%',
            right: '2%',
            zIndex: 20,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 4,
          }}
          onMouseEnter={() => setFloorNavHovered(true)}
          onMouseLeave={() => setFloorNavHovered(false)}
        >
          {/* 항상 보이는 트리거 버튼 */}
          <button
            style={{
              width: 34,
              height: 22,
              borderRadius: 6,
              border: '1px solid rgba(255,255,255,0.15)',
              background: floorNavHovered ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.55)',
              color: 'rgba(255,255,255,0.5)',
              fontSize: 9,
              fontWeight: 600,
              letterSpacing: '0.04em',
              cursor: 'default',
              backdropFilter: 'blur(8px)',
              transition: 'background 0.15s ease',
            }}
          >
            층이동
          </button>
          {/* 호버 시 아래로 나타나는 층 버튼 */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 3,
              opacity: floorNavHovered ? 1 : 0,
              transform: floorNavHovered ? 'translateY(0)' : 'translateY(-6px)',
              pointerEvents: floorNavHovered ? 'auto' : 'none',
              transition: 'opacity 0.18s ease, transform 0.18s ease',
            }}
          >
            {([3, 2, 1] as const).map((floor) => {
              const mapped = mappingsByFloor[floor]
              const isCurrent = currentFloor === floor
              const hasSession = !!mapped
              return (
                <button
                  key={floor}
                  disabled={!hasSession || isCurrent}
                  onClick={() => handleFloorNavigate(floor)}
                  style={{
                    width: 34,
                    height: 28,
                    borderRadius: 6,
                    border: isCurrent
                      ? '1px solid rgba(129,140,248,0.8)'
                      : hasSession
                        ? '1px solid rgba(255,255,255,0.18)'
                        : '1px solid rgba(255,255,255,0.06)',
                    background: isCurrent
                      ? 'rgba(99,102,241,0.75)'
                      : hasSession
                        ? 'rgba(0,0,0,0.65)'
                        : 'rgba(0,0,0,0.4)',
                    color: isCurrent
                      ? 'white'
                      : hasSession
                        ? 'rgba(255,255,255,0.8)'
                        : 'rgba(255,255,255,0.2)',
                    fontSize: 10,
                    fontWeight: 700,
                    cursor: hasSession && !isCurrent ? 'pointer' : 'default',
                    boxShadow: isCurrent ? '0 0 10px rgba(99,102,241,0.5)' : 'none',
                    backdropFilter: 'blur(8px)',
                    transition: 'background 0.12s ease',
                  }}
                >
                  {floor}F
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
