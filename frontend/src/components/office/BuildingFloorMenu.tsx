import { useEffect, useRef } from 'react'
import { ArrowRightLeft, Trash2 } from 'lucide-react'

interface BuildingFloorMenuProps {
  x: number
  y: number
  onChange: () => void
  onClear: () => void
  onClose: () => void
}

const MENU_WIDTH = 200
const MENU_HEIGHT = 96
const MENU_OFFSET = 12

export function BuildingFloorMenu({ x, y, onChange, onClear, onClose }: BuildingFloorMenuProps) {
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

  const clampedX = Math.min(
    Math.max(x - MENU_WIDTH - MENU_OFFSET, 8),
    window.innerWidth - MENU_WIDTH - 8,
  )
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
        animation: 'buildingFloorMenuIn 0.15s ease-out',
      }}
      className="flex flex-col gap-1 rounded-xl border border-white/15 bg-black/85 p-1.5 shadow-2xl backdrop-blur-md"
    >
      <style>{`
        @keyframes buildingFloorMenuIn {
          from { opacity: 0; transform: translateY(-4px) scale(0.96); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
      <button
        type="button"
        role="menuitem"
        onClick={onChange}
        className="group/item flex cursor-pointer items-center gap-2.5 rounded-lg bg-transparent px-3 py-2.5 text-left text-sm font-medium text-white/85 transition-all hover:translate-x-0.5 hover:bg-amber-300/15 hover:text-white"
      >
        <ArrowRightLeft className="h-4 w-4 shrink-0 text-white/60 transition-colors group-hover/item:text-amber-300" />
        다른 세션으로 바꾸기
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onClear}
        className="group/item flex cursor-pointer items-center gap-2.5 rounded-lg bg-transparent px-3 py-2.5 text-left text-sm font-medium text-white/85 transition-all hover:translate-x-0.5 hover:bg-red-500/15 hover:text-white"
      >
        <Trash2 className="h-4 w-4 shrink-0 text-white/60 transition-colors group-hover/item:text-red-300" />
        층 비우기
      </button>
    </div>
  )
}
