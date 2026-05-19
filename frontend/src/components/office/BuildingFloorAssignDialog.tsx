import { useEffect, useMemo, useState } from 'react'
import { X, Search, Check } from 'lucide-react'
import type { RawAiSession } from '@/types/aiChat'
import { toJsonObject, getString } from '@/components/sessionWorkspace/sessionWorkspaceUtils'

interface BuildingFloorAssignDialogProps {
  floor: number
  sessions: RawAiSession[]
  /** 이미 다른 층에 매핑된 세션 ID 집합 — 목록에서 제외한다. */
  assignedSessionIds: Set<string>
  onAssign: (sessionId: string) => void
  onClose: () => void
}

function getSessionTitle(session: RawAiSession): string {
  // 사이드바와 동일한 우선순위: metadata.ui.sessionName → session.title → session_id
  const metadata = toJsonObject(session.metadata)
  const uiMetadata = toJsonObject(metadata.ui)
  return getString(uiMetadata, 'sessionName') ?? session.title?.trim() ?? session.session_id
}

function getSessionSubtitle(session: RawAiSession): string | null {
  if (session.last_message && session.last_message.trim()) {
    const trimmed = session.last_message.trim()
    return trimmed.length > 80 ? `${trimmed.slice(0, 77)}...` : trimmed
  }
  return null
}

export function BuildingFloorAssignDialog({
  floor,
  sessions,
  assignedSessionIds,
  onAssign,
  onClose,
}: BuildingFloorAssignDialogProps) {
  const [query, setQuery] = useState('')
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose])

  const filteredSessions = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    const visible = sessions.filter((session) => {
      if (session.archived_at || session.deleted_at) return false
      // 이미 다른 층에 매핑된 세션은 목록에서 제외 — 한 세션이 여러 층에 매핑되지 않도록.
      if (assignedSessionIds.has(session.session_id)) return false
      return true
    })
    if (!normalized) return visible
    return visible.filter((session) => {
      const title = getSessionTitle(session).toLowerCase()
      return title.includes(normalized) || session.session_id.toLowerCase().includes(normalized)
    })
  }, [sessions, query, assignedSessionIds])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      style={{ animation: 'assignDialogFadeIn 0.18s ease-out' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <style>{`
        @keyframes assignDialogFadeIn {
          from { opacity: 0; transform: scale(0.96); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>
      <div
        role="dialog"
        aria-label={`${floor}층에 세션 매핑`}
        className="relative mx-4 w-full max-w-md rounded-2xl border border-white/15 bg-gradient-to-br from-zinc-900/95 to-zinc-950/95 p-5 shadow-2xl backdrop-blur-lg"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="absolute top-3 right-3 rounded-md p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="mb-4">
          <h2 className="text-base font-bold text-white">
            <span className="text-amber-300">{floor}F</span>에 매핑할 세션을 골라주세요
          </h2>
          <p className="mt-1 text-xs text-white/55">기존 채팅 세션 중 하나를 선택하면 됩니다.</p>
        </div>

        <div className="relative mb-3">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="세션 검색"
            className="w-full rounded-lg border border-white/15 bg-white/5 py-2 pr-3 pl-9 text-sm text-white transition-colors outline-none placeholder:text-white/35 focus:border-amber-300/50"
            autoFocus
          />
        </div>

        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-[10px] font-bold tracking-wider text-white/50 uppercase">
            최근 대화
          </span>
          <span className="text-[10px] text-white/35">{filteredSessions.length}</span>
        </div>
        <div className="max-h-72 overflow-y-auto pr-1">
          {filteredSessions.length === 0 ? (
            <div className="py-10 text-center text-sm text-white/45">
              {query ? '검색 결과가 없어요.' : '매핑 가능한 세션이 없어요.'}
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {filteredSessions.map((session) => {
                const isSelected = selectedSessionId === session.session_id
                const subtitle = getSessionSubtitle(session)
                return (
                  <li key={session.session_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedSessionId(session.session_id)}
                      className={`flex w-full cursor-pointer flex-col gap-0.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                        isSelected
                          ? 'border-amber-300/60 bg-amber-300/10'
                          : 'border-white/10 bg-white/5 hover:border-white/25 hover:bg-white/10'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex-1 truncate text-sm font-medium text-white">
                          {getSessionTitle(session)}
                        </span>
                        {isSelected && <Check className="h-4 w-4 shrink-0 text-amber-300" />}
                      </div>
                      {subtitle && (
                        <span className="truncate text-xs text-white/45">{subtitle}</span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            disabled={selectedSessionId === null}
            onClick={() => selectedSessionId !== null && onAssign(selectedSessionId)}
            className={
              selectedSessionId === null
                ? 'cursor-not-allowed rounded-lg bg-zinc-700/60 px-4 py-2 text-sm font-semibold text-white/40'
                : 'cursor-pointer rounded-lg bg-amber-400 px-4 py-2 text-sm font-bold text-zinc-900 shadow-md shadow-amber-500/20 transition-colors hover:bg-amber-300'
            }
          >
            매핑하기
          </button>
          <button
            type="button"
            onClick={onClose}
            className="cursor-pointer rounded-lg px-4 py-2 text-sm font-medium text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}
