import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router'
import { Plus, Settings as SettingsIcon } from 'lucide-react'
import { toast } from 'sonner'
import { FloorAgentSprite } from '@/components/office/FloorAgentSprite'
import { BuildingFloorAssignDialog } from '@/components/office/BuildingFloorAssignDialog'
import { BuildingFloorMenu } from '@/components/office/BuildingFloorMenu'
import { useBuildingMappingStore } from '@/store/useBuildingMappingStore'
import { useChatStore } from '@/store/useChatStore'
import { useAuthStore } from '@/store/useAuthStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { agentProfilesToPanelItems } from '@/apis/agents'
import { toJsonObject, getString } from '@/components/sessionWorkspace/sessionWorkspaceUtils'
import type { RawAiSession } from '@/types/aiChat'

const IMG_W = 1586
const IMG_H = 992

const VEHICLE_CSS = `
  @keyframes heygent-bike-move {
    0%     { transform: translateX(-600px); }
    35%    { transform: translateX(2000px); }
    35.01% { transform: translateX(-600px); }
    100%   { transform: translateX(-600px); }
  }
  @keyframes heygent-car-move {
    0%,    50%    { transform: translateX(-600px); }
    85%           { transform: translateX(2000px); }
    85.01%, 100%  { transform: translateX(-600px); }
  }
`

function VehicleLayer() {
  const [bikeFrame, setBikeFrame] = useState(1)
  useEffect(() => {
    const id = setInterval(() => setBikeFrame((f) => (f === 1 ? 2 : 1)), 250)
    return () => clearInterval(id)
  }, [])
  return (
    <>
      <div
        style={{
          position: 'absolute',
          top: 893,
          left: 0,
          pointerEvents: 'none',
          zIndex: 20,
          animation: 'heygent-bike-move 30s linear infinite',
        }}
      >
        <img
          src={`/assets/maps/overview_bike_${bikeFrame}.png`}
          alt=""
          draggable={false}
          style={{ width: 135, height: 'auto', display: 'block' }}
        />
      </div>
      <div
        style={{
          position: 'absolute',
          top: 873,
          left: 0,
          pointerEvents: 'none',
          zIndex: 20,
          animation: 'heygent-car-move 30s linear infinite',
        }}
      >
        <img
          src="/assets/maps/overview_car.png"
          alt=""
          draggable={false}
          style={{ width: 170, height: 'auto', display: 'block' }}
        />
      </div>
    </>
  )
}

function getBuildingBgSrc(): string {
  const hour = new Date().getHours()
  if (hour >= 8 && hour < 16) return '/assets/maps/building_bg_day.png'
  if (hour >= 6 && hour < 8) return '/assets/maps/building_bg_sunset.png'
  if (hour >= 16 && hour < 18) return '/assets/maps/building_bg_sunset.png'
  if (hour >= 18 && hour < 20) return '/assets/maps/building_bg_dusk.png'
  return '/assets/maps/building_bg_night.png'
}

interface FloorLayout {
  floor: number
  label: string
  top: string
  left: string
  width: string
  height: string
  svgPoints: string
  /** 폴리곤의 시각적 중심 좌표 (1586x992 캔버스 기준) — + 아이콘과 카드 위치 기준점. */
  centerX: number
  centerY: number
  agentSize: number
  agentBottom: number
  agentMinX: number
  agentMaxX: number
  fallbackAgentSpriteIds: string[]
}

const FLOORS: FloorLayout[] = [
  {
    floor: 3,
    label: '3F',
    top: '13.7%',
    left: '20%',
    width: '61%',
    height: '24%',
    svgPoints: '326,178 1252,142 1293,156 1293,364 1252,359 326,375',
    // 폴리곤의 시각적 중심
    centerX: 800,
    centerY: 260,
    agentSize: 85,
    agentBottom: 0,
    agentMinX: 40,
    agentMaxX: 85,
    fallbackAgentSpriteIds: ['agent03', 'agent04', 'agent05', 'agent06'],
  },
  {
    floor: 2,
    label: '2F',
    top: '40%',
    left: '20%',
    width: '61%',
    height: '21%',
    svgPoints: '326,407 1252,395 1293,402 1293,594 1252,599 326,595',
    centerX: 800,
    centerY: 495,
    agentSize: 85,
    agentBottom: 0,
    agentMinX: 30,
    agentMaxX: 85,
    fallbackAgentSpriteIds: ['agent03', 'agent04', 'agent05', 'agent06'],
  },
  {
    floor: 1,
    label: '1F',
    top: '63%',
    left: '20%',
    width: '59%',
    height: '21%',
    svgPoints: '326,627 1254,632 1254,835 326,810',
    centerX: 790,
    centerY: 725,
    agentSize: 85,
    agentBottom: 5,
    agentMinX: 25,
    agentMaxX: 82,
    fallbackAgentSpriteIds: ['agent03', 'agent04', 'agent05', 'agent06'],
  },
]

export function BuildingOverviewPage() {
  const navigate = useNavigate()
  const accessToken = useAuthStore((s) => s.accessToken)
  const sessionsById = useChatStore((s) => s.sessionsById)
  const fetchSessions = useChatStore((s) => s.fetchSessions)
  const mappingsByFloor = useBuildingMappingStore((s) => s.mappingsByFloor)
  const fetchMappings = useBuildingMappingStore((s) => s.fetchMappings)
  const assignFloor = useBuildingMappingStore((s) => s.assignFloor)
  const clearFloor = useBuildingMappingStore((s) => s.clearFloor)
  const agentPanelsBySessionId = useSessionStore((s) => s.agentPanelsBySessionId)
  const setAgentPanelsForSession = useSessionStore((s) => s.setAgentPanelsForSession)

  const [hoveredFloor, setHoveredFloor] = useState<number | null>(null)
  const [bgSrc, setBgSrc] = useState(getBuildingBgSrc)
  const containerRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  const [assignDialogFloor, setAssignDialogFloor] = useState<number | null>(null)
  const [floorMenu, setFloorMenu] = useState<{ floor: number; x: number; y: number } | null>(null)

  // 진입 시 매핑/세션 동시 fetch
  useEffect(() => {
    if (!accessToken) return
    void fetchMappings().catch(() => undefined)
    void fetchSessions().catch(() => undefined)
  }, [accessToken, fetchMappings, fetchSessions])

  // 매핑된 세션들의 agentPanels 를 미리 받아둔다 (호버 인포 카드에서 사용).
  useEffect(() => {
    const cache = useAgentCacheStore.getState()
    for (const sessionId of Object.values(mappingsByFloor)) {
      if (agentPanelsBySessionId[sessionId] !== undefined) continue
      void cache
        .fetchSessionAgents(sessionId)
        .then((profiles) => {
          setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
        })
        .catch(() => undefined)
    }
  }, [mappingsByFloor, agentPanelsBySessionId, setAgentPanelsForSession])

  // 시간대별 배경 자동 갱신
  useEffect(() => {
    function scheduleNext(): ReturnType<typeof setTimeout> {
      const now = new Date()
      const boundaries = [6, 8, 16, 18, 20]
      const totalMinutes = now.getHours() * 60 + now.getMinutes()
      const nextBoundaryMinutes =
        boundaries.map((h) => h * 60).find((m) => m > totalMinutes) ?? 6 * 60 + 24 * 60
      const msUntilNext = (nextBoundaryMinutes - totalMinutes) * 60_000 - now.getSeconds() * 1000
      return setTimeout(() => {
        setBgSrc(getBuildingBgSrc())
        scheduleNext()
      }, msUntilNext)
    }
    const timer = scheduleNext()
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setScale(Math.min(width / IMG_W, height / IMG_H))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // 사용자가 매핑한 sessionId 중 더 이상 세션 목록에 없는 게 있으면 자동으로 매핑 해제 + 토스트
  useEffect(() => {
    if (Object.keys(sessionsById).length === 0) return
    for (const [floorStr, sessionId] of Object.entries(mappingsByFloor)) {
      if (sessionsById[sessionId] === undefined) {
        const floor = Number(floorStr)
        void clearFloor(floor).catch(() => undefined)
        toast.info(`${floor}층의 세션이 삭제되어 빈 상태가 됐어요.`)
      }
    }
  }, [sessionsById, mappingsByFloor, clearFloor])

  const handleFloorClick = (floor: number) => {
    const sessionId = mappingsByFloor[floor]
    if (sessionId === undefined) {
      // 빈 층 → 세션 선택 다이얼로그
      setAssignDialogFloor(floor)
      return
    }
    // 매핑된 층 → 그 세션의 시각화로 이동
    navigate(`/session/${sessionId}/workspace/visualization`)
  }

  const handleGearClick = (e: React.MouseEvent<SVGElement | HTMLButtonElement>, floor: number) => {
    e.stopPropagation()
    setFloorMenu({ floor, x: e.clientX, y: e.clientY })
  }

  const handleAssignSubmit = async (sessionId: string) => {
    if (assignDialogFloor === null) return
    try {
      await assignFloor(assignDialogFloor, sessionId)
      setAssignDialogFloor(null)
      toast.success(`${assignDialogFloor}층에 세션을 매핑했어요.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '매핑에 실패했어요.')
    }
  }

  const handleClearFloor = async (floor: number) => {
    try {
      await clearFloor(floor)
      setFloorMenu(null)
      toast.success(`${floor}층 매핑을 해제했어요.`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '매핑 해제에 실패했어요.')
    }
  }

  const assignedSessionIds = useMemo(
    () => new Set(Object.values(mappingsByFloor)),
    [mappingsByFloor],
  )

  return (
    <div ref={containerRef} className="relative flex-1 overflow-hidden">
      {/* 배경 */}
      <img
        src={bgSrc}
        alt=""
        draggable={false}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          objectPosition: 'center',
        }}
      />

      {/* 전경: 건물 + 층별 영역 */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: IMG_W,
          height: IMG_H,
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center center',
        }}
      >
        <img
          src="/assets/maps/building_overview.png"
          alt="Building Overview"
          draggable={false}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            display: 'block',
          }}
        />

        <img
          src="/assets/maps/logo.png"
          alt="Logo"
          draggable={false}
          style={{
            position: 'absolute',
            top: 48,
            left: 1070,
            width: 180,
            height: 'auto',
            pointerEvents: 'none',
          }}
        />

        {/* 매핑된 층의 에이전트 스프라이트 — 빈 층은 spriteIdsForFloor 가 [] 라 아무도 안 돌아다님 */}
        {FLOORS.map((floor) => {
          const sessionId = mappingsByFloor[floor.floor]
          const isEmpty = sessionId === undefined
          const panels = sessionId ? (agentPanelsBySessionId[sessionId] ?? []) : []

          // 매핑된 층은 그 세션의 서브에이전트 spriteId, 없으면 fallback 으로 진행
          const spriteIdsForFloor = (() => {
            if (isEmpty) return []
            const fromSession = panels
              .map((panel) => panel.agent.spriteId)
              .filter((id): id is string => typeof id === 'string' && id.length > 0)
            return fromSession.length > 0 ? fromSession : floor.fallbackAgentSpriteIds
          })()

          return (
            <div
              key={floor.floor}
              style={{
                position: 'absolute',
                top: floor.top,
                left: floor.left,
                width: floor.width,
                height: floor.height,
                overflow: 'hidden',
                pointerEvents: 'none',
              }}
            >
              {spriteIdsForFloor.map((spriteId, index) => (
                <FloorAgentSprite
                  key={`${spriteId}-${index}`}
                  agentId={spriteId}
                  initialXPct={
                    floor.agentMinX +
                    ((floor.agentMaxX - floor.agentMinX) * (index + 1)) /
                      (spriteIdsForFloor.length + 1)
                  }
                  size={floor.agentSize}
                  bottomPct={floor.agentBottom}
                  minXPct={floor.agentMinX}
                  maxXPct={floor.agentMaxX}
                />
              ))}
            </div>
          )
        })}

        {/* 호버 outline 용 SVG — 빈 층도 기존 이미지 그대로 두고, 에이전트만 안 돌아다니게 한다. */}
        <svg
          viewBox={`0 0 ${IMG_W} ${IMG_H}`}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            pointerEvents: 'none',
          }}
        >
          {/* 호버 시 층 경계선 — 실제 유리창 모양(사다리꼴)과 동일한 polygon. 색은 빈/매핑 상태에 따라 다르게. */}
          {FLOORS.map((floor) => {
            if (hoveredFloor !== floor.floor) return null
            const sessionId = mappingsByFloor[floor.floor]
            const isEmpty = sessionId === undefined
            return (
              <polygon
                key={`hover-outline-${floor.floor}`}
                points={floor.svgPoints}
                fill="none"
                stroke={isEmpty ? 'rgba(255, 235, 150, 0.85)' : 'rgba(255, 255, 255, 0.7)'}
                strokeWidth={3}
                strokeLinejoin="miter"
              />
            )
          })}
        </svg>

        {/* 층 인터랙션 레이어 — 호버 / 클릭 영역을 폴리곤이 아닌 박스로 한 번에 처리 */}
        {FLOORS.map((floor) => {
          const sessionId = mappingsByFloor[floor.floor]
          const isEmpty = sessionId === undefined
          const hovered = hoveredFloor === floor.floor
          const session = sessionId ? sessionsById[sessionId] : undefined
          const sessionTitle = resolveSessionTitle(session) ?? sessionId ?? '미매핑'

          return (
            <div
              key={`floor-${floor.floor}`}
              onMouseEnter={() => setHoveredFloor(floor.floor)}
              onMouseLeave={() => setHoveredFloor(null)}
              style={{
                position: 'absolute',
                top: floor.top,
                left: floor.left,
                width: floor.width,
                height: floor.height,
                cursor: 'pointer',
                zIndex: 15,
              }}
              onClick={() => handleFloorClick(floor.floor)}
            >
              {/* 빈 층 라벨 — 오른쪽 상단 */}
              {isEmpty && hovered && (
                <div
                  style={{
                    position: 'absolute',
                    top: '12px',
                    right: '24px',
                  }}
                  className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 shadow-lg backdrop-blur-sm"
                >
                  <span className="text-sm font-bold tracking-wider text-amber-300 uppercase">
                    {floor.label}
                  </span>
                  <span className="ml-2 text-sm font-semibold text-white/90">빈 사무실</span>
                </div>
              )}

              {/* 빈 층 + 버튼만 정가운데. 호버 시 살짝 커지고 ring 강조 */}
              {isEmpty && hovered && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleFloorClick(floor.floor)
                  }}
                  style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    cursor: 'pointer',
                  }}
                  className="group flex h-14 w-14 cursor-pointer items-center justify-center rounded-full bg-amber-300 text-black shadow-2xl ring-4 ring-amber-300/30 transition-all hover:scale-110 hover:bg-amber-200 hover:ring-amber-200/60"
                  aria-label={`${floor.label}에 세션 추가`}
                >
                  <Plus
                    className="h-7 w-7 transition-transform group-hover:rotate-90"
                    strokeWidth={3}
                  />
                </button>
              )}

              {/* 매핑된 층의 호버 카드 — 층 오른쪽 안쪽 위로 배치, 박스 자체는 반투명 */}
              {!isEmpty && hovered && (
                <div
                  style={{
                    position: 'absolute',
                    top: '28%',
                    right: '24px',
                    transform: 'translateY(-50%)',
                  }}
                  className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 shadow-lg backdrop-blur-sm"
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-bold tracking-wider text-amber-300 uppercase">
                      {floor.label}
                    </span>
                    <span className="max-w-[240px] truncate text-sm font-semibold text-white">
                      {sessionTitle}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => handleGearClick(e, floor.floor)}
                    style={{ cursor: 'pointer' }}
                    className="group/gear flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg bg-white/5 text-white/80 transition-all hover:scale-110 hover:bg-amber-300 hover:text-zinc-900"
                    aria-label={`${floor.label} 설정`}
                  >
                    <SettingsIcon className="h-4 w-4 transition-transform group-hover/gear:rotate-90" />
                  </button>
                </div>
              )}
            </div>
          )
        })}

        <style>{VEHICLE_CSS}</style>
        <VehicleLayer />
      </div>

      {/* 세션 선택 다이얼로그 */}
      {assignDialogFloor !== null && (
        <BuildingFloorAssignDialog
          floor={assignDialogFloor}
          sessions={Object.values(sessionsById)}
          assignedSessionIds={assignedSessionIds}
          onAssign={handleAssignSubmit}
          onClose={() => setAssignDialogFloor(null)}
        />
      )}

      {/* 매핑된 층의 ⚙️ 컨텍스트 메뉴 */}
      {floorMenu && (
        <BuildingFloorMenu
          x={floorMenu.x}
          y={floorMenu.y}
          onChange={() => {
            setAssignDialogFloor(floorMenu.floor)
            setFloorMenu(null)
          }}
          onClear={() => void handleClearFloor(floorMenu.floor)}
          onClose={() => setFloorMenu(null)}
        />
      )}
    </div>
  )
}

/**
 * 세션 제목 우선순위:
 *   1. metadata.ui.sessionName (사용자가 수정한 표시명)
 *   2. session.title (백엔드 원본)
 * 둘 다 없으면 null 반환 — 호출 측에서 sessionId 등 fallback 으로 처리한다.
 */
function resolveSessionTitle(session: RawAiSession | undefined): string | null {
  if (!session) return null
  const metadata = toJsonObject(session.metadata)
  const uiMetadata = toJsonObject(metadata.ui)
  return getString(uiMetadata, 'sessionName') ?? session.title?.trim() ?? null
}
