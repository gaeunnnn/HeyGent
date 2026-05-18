import { useEffect, useRef, useState } from 'react'
import { X, Loader2 } from 'lucide-react'

interface NewSessionTitleDialogProps {
  /** mount 시점에 자동 포커스되는 입력칸의 초기값 */
  defaultTitle?: string
  /** 생성 중인지 — true 이면 입력/버튼 비활성, 스피너 표시 */
  submitting: boolean
  /** 외부에서 표시할 에러 메시지 (예: 서버 응답 실패) */
  error?: string | null
  onSubmit: (title: string) => void
  onClose: () => void
}

/**
 * 새 세션 생성 시 제목을 받는 작은 다이얼로그.
 * 입력 후 만들기 -> 부모가 세션 생성 + 시각화 페이지 이동.
 */
export function NewSessionTitleDialog({
  defaultTitle = '',
  submitting,
  error,
  onSubmit,
  onClose,
}: NewSessionTitleDialogProps) {
  const [title, setTitle] = useState(defaultTitle)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose, submitting])

  const handleSubmit = () => {
    const trimmed = title.trim()
    if (trimmed === '' || submitting) return
    onSubmit(trimmed)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      style={{ animation: 'newSessionDialogIn 0.18s ease-out' }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose()
      }}
    >
      <style>{`
        @keyframes newSessionDialogIn {
          from { opacity: 0; transform: scale(0.96); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>
      <div
        role="dialog"
        aria-label="새 세션 만들기"
        className="relative mx-4 w-full max-w-md rounded-2xl border border-white/15 bg-gradient-to-br from-zinc-900/95 to-zinc-950/95 p-5 shadow-2xl backdrop-blur-lg"
      >
        <button
          type="button"
          onClick={onClose}
          disabled={submitting}
          aria-label="닫기"
          className="absolute top-3 right-3 cursor-pointer rounded-md p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="mb-4">
          <h2 className="text-base font-bold text-white">새 세션 이름을 정해주세요</h2>
          <p className="mt-1 text-xs text-white/55">
            세션을 만들면 사무실에 에이전트들이 입장해요.
          </p>
        </div>

        <input
          ref={inputRef}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          placeholder="세션 이름을 입력하세요"
          maxLength={60}
          disabled={submitting}
          className="w-full rounded-lg border border-white/15 bg-white/5 px-4 py-2.5 text-sm text-white transition-colors outline-none placeholder:text-white/35 focus:border-amber-300/50 disabled:opacity-60"
        />

        {error !== null && error !== undefined && (
          <p className="mt-2 text-xs text-red-300" role="alert">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            disabled={title.trim() === '' || submitting}
            onClick={handleSubmit}
            className={
              title.trim() === '' || submitting
                ? 'flex cursor-not-allowed items-center gap-2 rounded-lg bg-zinc-700/60 px-4 py-2 text-sm font-semibold text-white/40'
                : 'flex cursor-pointer items-center gap-2 rounded-lg bg-amber-400 px-4 py-2 text-sm font-bold text-zinc-900 shadow-md shadow-amber-500/20 transition-colors hover:bg-amber-300'
            }
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            만들기
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="cursor-pointer rounded-lg px-4 py-2 text-sm font-medium text-white/70 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}
