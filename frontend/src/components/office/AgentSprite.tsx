import { useState, useLayoutEffect, useRef, useEffect } from 'react'
import type { AgentRuntime } from './types'
import type { AgentVisualizationInfo } from './types'

const SPAWN_KEYFRAMES = `
@keyframes spawnBulb {
  0%   { opacity: 0; transform: scale(0.2); }
  100% { opacity: 1; transform: scale(1); }
}
@keyframes workingPulse {
  0%, 100% { opacity: 0.95; transform: scale(1); }
  50%       { opacity: 0.5;  transform: scale(0.88); }
}
@keyframes bubbleFadeIn {
  0%   { opacity: 0; transform: translateX(-50%) translateY(4px); }
  100% { opacity: 1; transform: translateX(-50%) translateY(0); }
}
`

function injectSpawnStyles() {
  if (document.getElementById('agent-spawn-style')) return
  const el = document.createElement('style')
  el.id = 'agent-spawn-style'
  el.textContent = SPAWN_KEYFRAMES
  document.head.appendChild(el)
}

const SIZE_NORMAL = 200
const SIZE_SITTING = 260

const SITTING_SPRITES: Record<string, string> = {
  sitting_desk: 'sit_desk',
  sitting_sofa: 'sit_sofa',
  sitting_floor_lean: 'sit_floor_lean',
  sitting_meeting: 'meeting',
  sitting_calling: 'calling',
  standing_wait: 'walk_side_stand',
}

const WALK_FRAMES = ['walk_side_01', 'walk_side_stand', 'walk_side_02', 'walk_side_stand'] as const

function getSpriteSrc(agent: AgentRuntime, standingUp: boolean): string {
  if (standingUp) return `${agent.config.spritePath}/idle_front.png`
  const base = agent.config.spritePath
  const sittingMap = agent.config.sittingSprites
    ? { ...SITTING_SPRITES, ...agent.config.sittingSprites }
    : SITTING_SPRITES
  if (agent.state in sittingMap) return `${base}/${sittingMap[agent.state]}.png`
  const frames = agent.config.walkFrames ?? WALK_FRAMES
  if (agent.state === 'walking') return `${base}/${frames[agent.walkFrame]}.png`
  return `${base}/idle_front.png`
}

interface AgentSpriteProps {
  agent: AgentRuntime
  onArrived: (agentId: string) => void
  onClick?: (agentId: string, event: { clientX: number; clientY: number }) => void
  hoverInfo?: AgentVisualizationInfo
  isSelected?: boolean
  isSpawning?: boolean
}

export function AgentSprite({
  agent,
  onArrived,
  onClick,
  hoverInfo,
  isSelected,
  isSpawning,
}: AgentSpriteProps) {
  useEffect(() => {
    injectSpawnStyles()
  }, [])

  // sitting_desk → walking 전환 시 idle_front를 브라우저 첫 페인트 전에 삽입
  // useLayoutEffect로 동기 처리 — walk 스프라이트가 한 프레임도 노출되지 않도록 한다.
  const [standingUp, setStandingUp] = useState(false)
  const prevStateRef = useRef(agent.state)
  const standingUpTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useLayoutEffect(() => {
    const prevState = prevStateRef.current
    prevStateRef.current = agent.state

    if (agent.state === 'walking' && prevState === 'sitting_desk') {
      setStandingUp(true)
      clearTimeout(standingUpTimerRef.current)
      standingUpTimerRef.current = setTimeout(() => setStandingUp(false), 150)
    } else if (agent.state !== 'walking') {
      clearTimeout(standingUpTimerRef.current)
      standingUpTimerRef.current = setTimeout(() => setStandingUp(false), 0)
    }

    return () => clearTimeout(standingUpTimerRef.current)
  }, [agent.state])

  const { config, position, state, transitionDuration } = agent
  const scale = (config.scale ?? 1) * (config.stateScales?.[state] ?? 1)
  const size = (state === 'sitting_desk' ? SIZE_SITTING : SIZE_NORMAL) * scale
  const isInteractive = !!onClick

  const [hovered, setHovered] = useState(false)
  const zIndex = isSelected ? 25 : hovered ? 20 : 10

  const [bubbleHovered, setBubbleHovered] = useState(false)

  const showBubble =
    !isSpawning &&
    hoverInfo?.activityStatus === 'working' &&
    !!hoverInfo.currentTask &&
    hoverInfo.currentTask.status === 'in_progress'

  const imgTransform =
    agent.facingRight && (state === 'walking' || state === 'standing_wait')
      ? 'scaleX(-1)'
      : undefined

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: size,
        height: size,
        transform: `translate(${position.x - size / 2}px, ${position.y - size / 2}px)`,
        transition: state === 'walking' ? `transform ${transitionDuration}s linear` : 'none',
        zIndex,
        pointerEvents: isInteractive ? 'auto' : 'none',
        cursor: isInteractive ? 'pointer' : 'default',
      }}
      onTransitionEnd={(e) => {
        if (state === 'walking' && e.propertyName === 'transform') onArrived(config.id)
      }}
      onClick={(e) => {
        e.stopPropagation()
        onClick?.(config.id, { clientX: e.clientX, clientY: e.clientY })
      }}
      onMouseEnter={() => isInteractive && setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* 스폰 전구 — 에이전트 등장 시 머리 위에 💡 아이콘이 팝업 */}
      {isSpawning && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: 6,
            pointerEvents: 'none',
            zIndex: 40,
          }}
        >
          <span
            style={{
              display: 'block',
              fontSize: 24,
              lineHeight: 1,
              animation: 'spawnBulb 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both',
              filter: 'drop-shadow(0 0 8px rgba(253, 224, 71, 0.9))',
            }}
          >
            💡
          </span>
        </div>
      )}

      {/* 작업 중 말풍선 — activityStatus가 working이고 현재 작업이 있을 때 상시 표시 */}
      {showBubble && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: 10,
            zIndex: bubbleHovered ? 50 : 40,
            pointerEvents: 'auto',
            maxWidth: bubbleHovered ? 260 : 200,
            width: 'max-content',
            animation: 'bubbleFadeIn 0.25s ease both',
          }}
          onMouseEnter={() => setBubbleHovered(true)}
          onMouseLeave={() => setBubbleHovered(false)}
        >
          {/* 말풍선 본체 */}
          <div
            style={{
              background: 'rgba(10, 10, 22, 0.92)',
              border: '1px solid rgba(255,255,255,0.15)',
              borderRadius: 10,
              padding: '7px 11px',
              backdropFilter: 'blur(12px)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.55)',
              display: 'flex',
              alignItems: bubbleHovered ? 'flex-start' : 'center',
              gap: 6,
            }}
          >
            <span
              style={{
                fontSize: 13,
                lineHeight: 1,
                flexShrink: 0,
                animation: 'workingPulse 2s ease-in-out infinite',
                filter: 'drop-shadow(0 0 5px rgba(253, 224, 71, 0.85))',
                marginTop: bubbleHovered ? 1 : 0,
              }}
            >
              💡
            </span>
            <span
              style={{
                color: 'white',
                fontSize: 11,
                fontWeight: 600,
                whiteSpace: bubbleHovered ? 'normal' : 'nowrap',
                overflow: bubbleHovered ? 'visible' : 'hidden',
                textOverflow: bubbleHovered ? 'unset' : 'ellipsis',
                maxWidth: bubbleHovered ? 220 : 155,
                wordBreak: bubbleHovered ? 'break-word' : undefined,
              }}
            >
              {hoverInfo!.currentTask!.title}
            </span>
          </div>

          {/* 말풍선 꼬리 */}
          <div
            style={{
              position: 'absolute',
              bottom: -5,
              left: '50%',
              marginLeft: -5,
              width: 10,
              height: 10,
              background: 'rgba(10, 10, 22, 0.92)',
              border: '1px solid rgba(255,255,255,0.15)',
              borderTop: 'none',
              borderLeft: 'none',
              transform: 'rotate(45deg)',
            }}
          />
        </div>
      )}

      <img
        src={getSpriteSrc(agent, standingUp)}
        alt={config.name}
        draggable={false}
        style={{
          width: '100%',
          height: '100%',
          userSelect: 'none',
          transform: [imgTransform, hovered ? 'translateY(-6px)' : null].filter(Boolean).join(' '),
          filter: hovered ? 'drop-shadow(0 6px 10px rgba(0, 0, 0, 0.45))' : undefined,
          transition: 'transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.18s ease',
        }}
      />
    </div>
  )
}
