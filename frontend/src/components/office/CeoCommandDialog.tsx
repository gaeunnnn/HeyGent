import { useEffect, useRef, useState } from 'react'
import { Send, X, Loader2 } from 'lucide-react'
import { useChatStore } from '@/store/useChatStore'

interface CeoCommandDialogProps {
  sessionId: string
  ceoName: string
  ceoProfileImage: string
  onClose: () => void
}

/**
 * 미연시 스타일 명령 다이얼로그.
 * 화면 전체를 흐리게 가리고 하단에 가로로 긴 대화창을 띄운다.
 * 왼쪽에 팀장 얼굴, 오른쪽에 메시지 입력칸.
 */
export function CeoCommandDialog({
  sessionId,
  ceoName,
  ceoProfileImage,
  onClose,
}: CeoCommandDialogProps) {
  const sendMessage = useChatStore((state) => state.sendMessage)
  const [content, setContent] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    // mount 시 입력칸에 자동 포커스
    textareaRef.current?.focus()
  }, [])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !sending) onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose, sending])

  const handleSubmit = async () => {
    const trimmed = content.trim()
    if (trimmed === '' || sending) return
    setSending(true)
    setError(null)
    try {
      await sendMessage({ sessionId, content: trimmed })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '명령 전송에 실패했습니다.')
      setSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/55 backdrop-blur-md"
      style={{ animation: 'ceoDialogFadeIn 0.2s ease-out' }}
      onClick={(e) => {
        // 배경 클릭 시 닫기 — 단 입력 중 (sending) 이면 무시
        if (e.target === e.currentTarget && !sending) onClose()
      }}
    >
      <style>{`
        @keyframes ceoDialogFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes ceoDialogSlideUp {
          from { opacity: 0; transform: translateY(24px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div
        role="dialog"
        aria-labelledby="ceo-command-dialog-title"
        style={{ animation: 'ceoDialogSlideUp 0.3s cubic-bezier(0.34, 1.2, 0.64, 1)' }}
        className="relative mx-4 mb-6 w-full max-w-3xl rounded-2xl border border-white/15 bg-gradient-to-br from-zinc-900/95 to-zinc-950/95 p-5 shadow-2xl backdrop-blur-lg"
      >
        <button
          type="button"
          onClick={onClose}
          disabled={sending}
          aria-label="닫기"
          className="absolute top-3 right-3 rounded-md p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex gap-4">
          {/* 팀장 얼굴 */}
          <div className="flex shrink-0 flex-col items-center gap-2">
            <div className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-2xl border-2 border-amber-300/40 bg-zinc-800 shadow-lg">
              <img
                src={ceoProfileImage}
                alt={ceoName}
                className="h-full w-full object-contain"
                draggable={false}
              />
            </div>
            <p className="text-xs font-semibold text-amber-200/90">{ceoName}</p>
          </div>

          {/* 대화 영역 */}
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            <div>
              <p
                id="ceo-command-dialog-title"
                className="text-sm leading-relaxed font-medium text-white/95"
              >
                시키실 일 말씀해주세요.
              </p>
              <p className="mt-1 text-xs leading-relaxed text-white/55">
                팀장에게 명령을 내리면 적절한 에이전트에게 위임합니다.
              </p>
            </div>

            <div className="relative">
              <textarea
                ref={textareaRef}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="예: 부산 오늘 날씨 알려줘"
                rows={3}
                disabled={sending}
                className="w-full resize-none rounded-xl border border-white/15 bg-white/5 px-4 py-3 pr-12 text-sm text-white transition-colors outline-none placeholder:text-white/35 focus:border-amber-300/50 disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={content.trim() === '' || sending}
                aria-label="전송"
                className="absolute right-3 bottom-3 flex h-8 w-8 items-center justify-center rounded-lg bg-amber-300 text-black transition-colors hover:bg-amber-200 disabled:bg-white/15 disabled:text-white/40"
              >
                {sending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>

            {error !== null && (
              <p className="text-xs text-red-300" role="alert">
                {error}
              </p>
            )}
            <p className="text-[11px] text-white/35">
              Enter 로 전송 · Shift+Enter 로 줄바꿈 · ESC 로 닫기
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
