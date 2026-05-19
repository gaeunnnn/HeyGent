import { useEffect, useRef } from 'react'
import { MessageSquare, Info } from 'lucide-react'

interface CeoActionMenuProps {
  /** viewport 좌표 (clientX/clientY) */
  x: number
  y: number
  onSelectCommand: () => void
  onSelectInfo: () => void
  onClose: () => void
}

const MENU_WIDTH = 168
const MENU_HEIGHT = 96
const MENU_OFFSET = 18

export function CeoActionMenu({
  x,
  y,
  onSelectCommand,
  onSelectInfo,
  onClose,
}: CeoActionMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    // 메뉴를 열게 만든 클릭이 같은 frame 에 outside-click 으로 잡혀 즉시 닫히는 것을 막기 위해
    // 다음 macrotask 부터 리스너를 부착한다.
    const timer = window.setTimeout(() => {
      window.addEventListener('mousedown', handleClickOutside)
      window.addEventListener('keydown', handleEscape)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('mousedown', handleClickOutside)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  // viewport 경계를 넘지 않도록 위치 보정
  const clampedX = Math.min(Math.max(x + MENU_OFFSET, 8), window.innerWidth - MENU_WIDTH - 8)
  const clampedY = Math.min(Math.max(y - MENU_HEIGHT / 2, 8), window.innerHeight - MENU_HEIGHT - 8)

  return (
    <div
      ref={menuRef}
      role="menu"
      style={{
        position: 'fixed',
        left: clampedX,
        top: clampedY,
        width: MENU_WIDTH,
        zIndex: 60,
        animation: 'ceoMenuFadeIn 0.15s ease-out',
      }}
      className="flex flex-col gap-1 rounded-xl border border-white/15 bg-black/85 p-1.5 shadow-2xl backdrop-blur-md"
    >
      <style>{`
        @keyframes ceoMenuFadeIn {
          from { opacity: 0; transform: translateY(-4px) scale(0.96); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
      <button
        type="button"
        role="menuitem"
        onClick={onSelectCommand}
        className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-white transition-colors hover:bg-white/10"
      >
        <MessageSquare className="h-4 w-4 shrink-0 text-amber-300" />
        명령하기
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onSelectInfo}
        className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-white transition-colors hover:bg-white/10"
      >
        <Info className="h-4 w-4 shrink-0 text-sky-300" />
        정보보기
      </button>
    </div>
  )
}
