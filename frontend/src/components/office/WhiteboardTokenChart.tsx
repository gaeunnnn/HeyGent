import { useState } from 'react'
import type { CommandUsageSummary } from '@/apis/aiCommandUsage'

// 화이트보드 4 모서리 좌표 (맵 픽셀 공간, 1600×900 기준)
const TL = { x: 85, y: 453 }
const TR = { x: 367, y: 332 }
const BR = { x: 367, y: 492 }
const BL = { x: 85, y: 617 }

// 클립 경로 — 평행사변형 (시계 방향)
const CLIP = `polygon(${TL.x}px ${TL.y}px, ${TR.x}px ${TR.y}px, ${BR.x}px ${BR.y}px, ${BL.x}px ${BL.y}px)`

// 화이트보드 상단 엣지 기울기 — skewY 에 사용
const TILT = Math.atan2(TR.y - TL.y, TR.x - TL.x) * (180 / Math.PI) // ≈ -23.2°

// 무게 중심
const CX = (TL.x + TR.x + BR.x + BL.x) / 4 // 226
const CY = (TL.y + TR.y + BR.y + BL.y) / 4 // 473.5

const BARS: {
  key: keyof Pick<
    CommandUsageSummary,
    'inputTokens' | 'outputTokens' | 'cachedInputTokens' | 'reasoningTokens'
  >
  label: string
  color: string
}[] = [
  { key: 'inputTokens', label: 'INPUT', color: '#3b82f6' },
  { key: 'outputTokens', label: 'OUTPUT', color: '#22c55e' },
  { key: 'cachedInputTokens', label: 'CACHE', color: '#f59e0b' },
  { key: 'reasoningTokens', label: 'REASON', color: '#a855f7' },
]

interface WhiteboardTokenChartProps {
  summary: CommandUsageSummary | null
  onOpen?: () => void
}

export function WhiteboardTokenChart({ summary, onOpen }: WhiteboardTokenChartProps) {
  const [hovered, setHovered] = useState(false)
  const maxVal = summary
    ? Math.max(
        summary.inputTokens,
        summary.outputTokens,
        summary.cachedInputTokens,
        summary.reasoningTokens,
        1,
      )
    : 1

  const isInteractive = !!onOpen

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        clipPath: CLIP,
        pointerEvents: isInteractive ? 'auto' : 'none',
        cursor: isInteractive ? 'pointer' : 'default',
        zIndex: 5,
        // 호버 시 화이트보드 자체가 따뜻하게 빛난다 — 클릭 가능하다는 단서.
        background: hovered ? 'rgba(255, 240, 180, 0.45)' : 'transparent',
        boxShadow: hovered
          ? 'inset 0 0 60px rgba(255, 220, 110, 0.7), 0 0 24px rgba(255, 220, 110, 0.4)'
          : 'none',
        transition: 'background 0.2s ease, box-shadow 0.2s ease',
      }}
      onClick={onOpen}
      onMouseEnter={() => isInteractive && setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        style={{
          position: 'absolute',
          left: CX,
          top: CY,
          // skewY: 세로축(막대 쌓임)은 수직 유지, 가로선(막대)만 화이트보드 기울기에 맞게 기울어짐
          transform: `translate(-50%, -50%) skewY(${TILT}deg)`,
          width: 210,
          pointerEvents: 'none',
        }}
      >
        {/* 제목 */}
        <p
          style={{
            color: '#4b4b4b',
            fontSize: 8,
            letterSpacing: '0.14em',
            textAlign: 'center',
            marginBottom: 8,
            fontWeight: 700,
            userSelect: 'none',
          }}
        >
          TOKEN USAGE
        </p>

        {/* 막대 4개 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          {BARS.map(({ key, label, color }) => {
            const value = summary?.[key] ?? 0
            const pct = (value / maxVal) * 100
            return (
              <div key={key}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span
                    style={{
                      color: '#3d3d3d',
                      fontSize: 8,
                      letterSpacing: '0.08em',
                      fontWeight: 600,
                      userSelect: 'none',
                    }}
                  >
                    {label}
                  </span>
                  <span
                    style={{
                      color: '#1a1a1a',
                      fontSize: 8,
                      fontVariantNumeric: 'tabular-nums',
                      userSelect: 'none',
                    }}
                  >
                    {value.toLocaleString()}
                  </span>
                </div>
                <div
                  style={{
                    height: 7,
                    background: 'rgba(0,0,0,0.08)',
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${pct}%`,
                      background: color,
                      borderRadius: 4,
                      transition: 'width 0.9s ease',
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>

        {/* 데이터 없을 때 */}
        {!summary && (
          <p
            style={{
              color: '#888',
              fontSize: 8,
              textAlign: 'center',
              marginTop: 12,
              userSelect: 'none',
            }}
          >
            — 데이터 없음 —
          </p>
        )}
      </div>
    </div>
  )
}
