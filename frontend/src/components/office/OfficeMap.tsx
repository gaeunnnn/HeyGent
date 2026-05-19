import { useRef, useEffect, useState } from 'react'
import { AgentSprite } from './AgentSprite'
import { WhiteboardTokenChart } from './WhiteboardTokenChart'
import type { AgentRuntime, AgentVisualizationInfo } from './types'
import type { CommandUsageSummary } from '@/apis/aiCommandUsage'

const MAP_WIDTH = 1600
const MAP_HEIGHT = 900

function getOfficeMapSrc(): string {
  const hour = new Date().getHours()
  if (hour >= 8 && hour < 16) return '/assets/maps/office_map_day.png'
  if (hour >= 16 && hour < 18) return '/assets/maps/office_map_sunset.png'
  if (hour >= 6 && hour < 8) return '/assets/maps/office_map_sunset.png'
  if (hour >= 18 && hour < 20) return '/assets/maps/office_map_dusk.png'
  return '/assets/maps/office_map_night.png'
}

const CEO_SPRITES = {
  desk: { src: '/assets/agents/ceo/ceo_desk.png', x: 310, y: 215, size: 230 },
  explain: { src: '/assets/agents/ceo/ceo_explain.png', x: 383, y: 493, size: 210 },
}

type Rect = { x1: number; y1: number; x2: number; y2: number }

interface OfficeMapProps {
  agents: AgentRuntime[]
  onAgentArrived: (agentId: string) => void
  ceoMode: 'desk' | 'explain' | null
  mapOverride?: string
  obstacleMode?: boolean
  obstacleRects?: Rect[]
  onNewRect?: (rect: Rect) => void
  obstacleLineMode?: boolean
  obstacleLines?: Rect[]
  onNewLine?: (line: Rect) => void
  onAgentClick?: (agentId: string, event: { clientX: number; clientY: number }) => void
  onEmptyClick?: () => void
  agentInfoMap?: Record<string, AgentVisualizationInfo>
  selectedAgentId?: string | null
  spawningIds?: ReadonlySet<string>
  tokenUsageSummary?: CommandUsageSummary | null
  onTokenChartClick?: () => void
}

export function OfficeMap({
  agents,
  onAgentArrived,
  ceoMode,
  mapOverride,
  obstacleMode,
  obstacleRects,
  onNewRect,
  obstacleLineMode,
  obstacleLines,
  onNewLine,
  onAgentClick,
  onEmptyClick,
  agentInfoMap,
  selectedAgentId,
  spawningIds,
  tokenUsageSummary,
  onTokenChartClick,
}: OfficeMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [mapSrc, setMapSrc] = useState(getOfficeMapSrc)
  const [drag, setDrag] = useState<{ sx: number; sy: number; ex: number; ey: number } | null>(null)
  const [linePending, setLinePending] = useState<{ x: number; y: number } | null>(null)
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    function scheduleNext() {
      const now = new Date()
      const boundaries = [6, 8, 16, 18, 20]
      const totalMinutes = now.getHours() * 60 + now.getMinutes()
      const nextBoundaryMinutes =
        boundaries.map((h) => h * 60).find((m) => m > totalMinutes) ?? 6 * 60 + 24 * 60
      const msUntilNext = (nextBoundaryMinutes - totalMinutes) * 60_000 - now.getSeconds() * 1000

      return setTimeout(() => {
        setMapSrc(getOfficeMapSrc())
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
      const s = Math.min(width / MAP_WIDTH, height / MAP_HEIGHT)
      setScale(s)
      setOffset({
        x: (width - MAP_WIDTH * s) / 2,
        y: (height - MAP_HEIGHT * s) / 2,
      })
    })

    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const toMapCoords = (clientX: number, clientY: number) => {
    const el = containerRef.current?.getBoundingClientRect()
    if (!el) return null
    return {
      x: Math.round((clientX - el.left - offset.x) / scale),
      y: Math.round((clientY - el.top - offset.y) / scale),
    }
  }

  const handleMapClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (obstacleMode) return
    const pos = toMapCoords(e.clientX, e.clientY)
    if (!pos) return

    if (obstacleLineMode) {
      if (!linePending) {
        setLinePending(pos)
      } else {
        onNewLine?.({ x1: linePending.x, y1: linePending.y, x2: pos.x, y2: pos.y })
        setLinePending(null)
        setHoverPos(null)
      }
      return
    }

    onEmptyClick?.()
  }

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!obstacleMode) return
    const pos = toMapCoords(e.clientX, e.clientY)
    if (!pos) return
    e.preventDefault()
    setDrag({ sx: pos.x, sy: pos.y, ex: pos.x, ey: pos.y })
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (obstacleMode && drag) {
      const pos = toMapCoords(e.clientX, e.clientY)
      if (!pos) return
      setDrag((d) => (d ? { ...d, ex: pos.x, ey: pos.y } : null))
      return
    }
    if (obstacleLineMode && linePending) {
      const pos = toMapCoords(e.clientX, e.clientY)
      if (pos) setHoverPos(pos)
    }
  }

  const handleMouseUp = () => {
    if (!obstacleMode || !drag) return
    if (Math.abs(drag.ex - drag.sx) > 10 && Math.abs(drag.ey - drag.sy) > 10) {
      onNewRect?.({
        x1: Math.min(drag.sx, drag.ex),
        y1: Math.min(drag.sy, drag.ey),
        x2: Math.max(drag.sx, drag.ex),
        y2: Math.max(drag.sy, drag.ey),
      })
    }
    setDrag(null)
  }

  return (
    <div
      ref={containerRef}
      className={`relative flex-1 overflow-hidden bg-gray-900 ${obstacleMode || obstacleLineMode ? 'cursor-crosshair' : 'cursor-default'}`}
      onClick={handleMapClick}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: MAP_WIDTH,
          height: MAP_HEIGHT,
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center center',
        }}
      >
        <img
          src={mapOverride ?? mapSrc}
          alt="Office Map"
          draggable={false}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            display: 'block',
          }}
        />
        <WhiteboardTokenChart summary={tokenUsageSummary ?? null} onOpen={onTokenChartClick} />
        {agents.map((agent) => (
          <AgentSprite
            key={agent.config.id}
            agent={agent}
            onArrived={onAgentArrived}
            onClick={onAgentClick}
            hoverInfo={agentInfoMap?.[agent.config.id]}
            isSelected={selectedAgentId === agent.config.id}
            isSpawning={spawningIds?.has(agent.config.id) ?? false}
          />
        ))}
        {ceoMode &&
          (() => {
            const sprite = CEO_SPRITES[ceoMode]
            return (
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: sprite.size,
                  height: sprite.size,
                  transform: `translate(${sprite.x - sprite.size / 2}px, ${sprite.y - sprite.size / 2}px)`,
                  zIndex: 10,
                  pointerEvents: 'none',
                }}
              >
                <img
                  src={sprite.src}
                  alt="팀장 에이전트"
                  draggable={false}
                  style={{ width: '100%', height: '100%', userSelect: 'none' }}
                />
              </div>
            )
          })()}

        {/* 장애물 사각형 오버레이 */}
        {obstacleRects?.map((r, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: r.x1,
              top: r.y1,
              width: r.x2 - r.x1,
              height: r.y2 - r.y1,
              background: 'rgba(239,68,68,0.25)',
              border: '2px solid rgba(239,68,68,0.8)',
              pointerEvents: 'none',
              zIndex: 20,
            }}
          />
        ))}

        {/* 드래그 중 미리보기 */}
        {drag && (
          <div
            style={{
              position: 'absolute',
              left: Math.min(drag.sx, drag.ex),
              top: Math.min(drag.sy, drag.ey),
              width: Math.abs(drag.ex - drag.sx),
              height: Math.abs(drag.ey - drag.sy),
              background: 'rgba(239,68,68,0.15)',
              border: '2px dashed rgba(239,68,68,0.9)',
              pointerEvents: 'none',
              zIndex: 20,
            }}
          />
        )}

        {/* 선 장애물 오버레이 */}
        {(obstacleLines?.length || (obstacleLineMode && linePending)) && (
          <svg
            style={{
              position: 'absolute',
              inset: 0,
              width: MAP_WIDTH,
              height: MAP_HEIGHT,
              pointerEvents: 'none',
              zIndex: 21,
              overflow: 'visible',
            }}
          >
            {obstacleLines?.map((l, i) => (
              <line
                key={i}
                x1={l.x1}
                y1={l.y1}
                x2={l.x2}
                y2={l.y2}
                stroke="rgba(251,146,60,0.9)"
                strokeWidth={4}
                strokeLinecap="round"
              />
            ))}
            {obstacleLineMode && linePending && (
              <circle cx={linePending.x} cy={linePending.y} r={6} fill="rgba(251,146,60,1)" />
            )}
            {obstacleLineMode && linePending && hoverPos && (
              <line
                x1={linePending.x}
                y1={linePending.y}
                x2={hoverPos.x}
                y2={hoverPos.y}
                stroke="rgba(251,146,60,0.6)"
                strokeWidth={3}
                strokeDasharray="10 5"
                strokeLinecap="round"
              />
            )}
          </svg>
        )}
      </div>
    </div>
  )
}
