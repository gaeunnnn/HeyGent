import {
  BarChart2,
  FileImage,
  ImageIcon,
  ListTodo,
  Loader2,
  Mic,
  Paperclip,
  Plus,
  Send,
  Square,
  X,
} from 'lucide-react'
import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
} from 'react'
import { getCommandUsage, type CommandUsageSummary } from '@/apis/aiCommandUsage'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { VoiceWaveform } from './VoiceWaveform'

export type ChatAttachmentPayload = {
  id: string
  name: string
  type: string
  size: number
  lastModified: number
  isImage: boolean
  dataUrl?: string
  text?: string
  textTruncated?: boolean
  error?: string
}

type ChatComposerProps = {
  disabled?: boolean
  isSending?: boolean
  placeholder?: string
  onSend: (content: string, attachments?: ChatAttachmentPayload[]) => void | Promise<void>
  onClearSelectedWork?: () => void
  onSelectWorkClick?: () => void
  onStop?: () => void
  draftValue?: string | null
  statusMessage?: string | null
  selectedWorkLabel?: string | null
  sessionId?: string
}

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
const MAX_TEXT_CHARS = 12_000

export function ChatComposer({
  disabled = false,
  isSending = false,
  placeholder = '무엇이든 물어보세요...',
  onSend,
  onClearSelectedWork,
  onSelectWorkClick,
  onStop,
  draftValue = null,
  statusMessage = null,
  selectedWorkLabel = null,
  sessionId,
}: ChatComposerProps) {
  const [value, setValue] = useState(draftValue ?? '')
  const [isRecording, setIsRecording] = useState(false)
  const [attachOpen, setAttachOpen] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)
  const [usageSummary, setUsageSummary] = useState<CommandUsageSummary | null>(null)
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<File[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const [isPreparingAttachments, setIsPreparingAttachments] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const dragDepthRef = useRef(0)

  const appendAttachments = useCallback((files: FileList | File[]) => {
    const next = Array.from(files)
    if (next.length === 0) return
    setAttachments((prev) => [...prev, ...next])
  }, [])

  const fetchSessionUsage = useCallback(async () => {
    if (!sessionId) return
    setUsageLoading(true)
    setUsageError(null)
    try {
      const result = await getCommandUsage({ sessionId })
      setUsageSummary(result.summary)
    } catch {
      setUsageError('사용량을 불러오지 못했습니다.')
    } finally {
      setUsageLoading(false)
    }
  }, [sessionId])

  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (textarea === null) return

    textarea.style.height = '0px'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`
  }, [value])

  const openFilePicker = () => {
    if (disabled || isSending || isPreparingAttachments) return
    fileInputRef.current?.click()
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  const handleUsageOpen = (open: boolean) => {
    setUsageOpen(open)
    if (open && !usageSummary && !usageLoading) void fetchSessionUsage()
  }

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    dragDepthRef.current += 1
    setIsDragOver(true)
  }

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setIsDragOver(false)
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    dragDepthRef.current = 0
    setIsDragOver(false)
    if (event.dataTransfer.files.length > 0) appendAttachments(event.dataTransfer.files)
  }

  const submit = async () => {
    const trimmed = value.trim()
    if ((!trimmed && attachments.length === 0) || disabled || isSending || isPreparingAttachments) {
      return
    }

    setIsPreparingAttachments(true)
    try {
      const attachmentPayloads = await Promise.all(attachments.map(readAttachmentPayload))
      await onSend(trimmed || '첨부 파일을 확인해 주세요.', attachmentPayloads)
      setValue('')
      setAttachments([])
    } finally {
      setIsPreparingAttachments(false)
    }
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
    }
  }

  const canSend = value.trim() !== '' || attachments.length > 0

  return (
    <div className="bg-background px-4 pt-2 pb-8 sm:pb-10">
      <div className="mx-auto max-w-3xl">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) appendAttachments(event.target.files)
            event.target.value = ''
          }}
        />
        <div
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-border bg-card relative overflow-hidden rounded-2xl border shadow-sm transition-shadow duration-200 hover:shadow-md ${
            isDragOver ? 'ring-primary/60 ring-2' : ''
          }`}
        >
          {isDragOver && (
            <div className="bg-primary/10 text-primary pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-sm font-medium">
              사진과 파일을 여기에 놓아 첨부
            </div>
          )}
          {attachments.length > 0 && (
            <div className="border-border/60 flex flex-wrap gap-2 border-b px-5 py-2">
              {attachments.map((file, index) => (
                <span
                  key={`${file.name}-${file.lastModified}-${index}`}
                  className="bg-muted/40 text-foreground inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
                >
                  {file.type.startsWith('image/') ? (
                    <ImageIcon className="text-muted-foreground h-3 w-3 shrink-0" />
                  ) : (
                    <Paperclip className="text-muted-foreground h-3 w-3 shrink-0" />
                  )}
                  <span className="max-w-[16ch] truncate" title={file.name}>
                    {file.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(index)}
                    aria-label={`${file.name} 첨부 제거`}
                    className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          {selectedWorkLabel && (
            <div className="border-border/60 bg-muted/20 flex items-center gap-2 border-b px-5 py-2 text-xs">
              <ListTodo className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              <span className="text-muted-foreground">연결된 작업</span>
              <span className="text-foreground min-w-0 flex-1 truncate font-medium">
                {selectedWorkLabel}
              </span>
              <button
                type="button"
                onClick={onClearSelectedWork}
                aria-label="연결된 작업 해제"
                className="text-muted-foreground hover:text-foreground rounded-sm p-1"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          <div className="flex items-center gap-3 px-5 py-2">
            <Popover open={attachOpen} onOpenChange={setAttachOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  aria-label="사진 또는 파일 추가"
                  className="bg-muted text-muted-foreground hover:bg-muted/80 shrink-0 rounded-full p-1 transition-colors disabled:opacity-40"
                  disabled={disabled || isSending || isPreparingAttachments}
                >
                  <Plus className="h-4 w-4" />
                </button>
              </PopoverTrigger>
              <PopoverContent
                side="top"
                align="start"
                sideOffset={8}
                className="w-52 rounded-2xl p-1.5"
              >
                <button
                  type="button"
                  onClick={() => {
                    setAttachOpen(false)
                    openFilePicker()
                  }}
                  className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors"
                >
                  <FileImage className="text-muted-foreground h-4 w-4 shrink-0" />
                  <span className="text-foreground flex-1 text-sm">PC에서 파일 선택</span>
                </button>
                {onSelectWorkClick && (
                  <>
                    <div className="border-border/60 my-1 border-t" />
                    <button
                      type="button"
                      onClick={() => {
                        setAttachOpen(false)
                        onSelectWorkClick()
                      }}
                      className="hover:bg-muted flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors"
                    >
                      <ListTodo className="text-muted-foreground h-4 w-4 shrink-0" />
                      <span className="text-foreground flex-1 text-sm">기존 작업 선택</span>
                    </button>
                  </>
                )}
              </PopoverContent>
            </Popover>
            {sessionId && (
              <Popover open={usageOpen} onOpenChange={handleUsageOpen}>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    aria-label="토큰 사용량 보기"
                    className="bg-muted text-muted-foreground hover:bg-muted/80 shrink-0 rounded-full p-1 transition-colors"
                  >
                    <BarChart2 className="h-4 w-4" />
                  </button>
                </PopoverTrigger>
                <PopoverContent
                  side="top"
                  align="start"
                  sideOffset={8}
                  className="w-64 rounded-2xl p-4"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-foreground text-sm font-semibold">세션 토큰 사용량</p>
                    <button
                      type="button"
                      onClick={() => void fetchSessionUsage()}
                      disabled={usageLoading}
                      className="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                      aria-label="새로고침"
                    >
                      <Loader2
                        className={`h-3.5 w-3.5 ${usageLoading ? 'animate-spin' : 'hidden'}`}
                      />
                    </button>
                  </div>
                  {usageLoading && !usageSummary && (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
                    </div>
                  )}
                  {usageError && <p className="text-destructive text-xs">{usageError}</p>}
                  {usageSummary && (
                    <div className="space-y-2">
                      {[
                        { label: '총 토큰', value: usageSummary.totalTokens.toLocaleString() },
                        { label: '입력', value: usageSummary.inputTokens.toLocaleString() },
                        { label: '출력', value: usageSummary.outputTokens.toLocaleString() },
                        {
                          label: '예상 비용',
                          value: `$${usageSummary.estimatedCostUsd.toFixed(4)}`,
                        },
                      ].map(({ label, value: usageValue }) => (
                        <div key={label} className="flex items-center justify-between">
                          <span className="text-muted-foreground text-xs">{label}</span>
                          <span className="text-foreground text-xs font-semibold tabular-nums">
                            {usageValue}
                          </span>
                        </div>
                      ))}
                      <p className="text-muted-foreground border-border mt-2 border-t pt-2 text-xs">
                        {usageSummary.recordCount}건의 기록
                      </p>
                    </div>
                  )}
                </PopoverContent>
              </Popover>
            )}
            {isRecording ? (
              <VoiceWaveform active={isRecording} onError={() => setIsRecording(false)} />
            ) : (
              <textarea
                ref={textareaRef}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                disabled={disabled}
                rows={1}
                className="text-foreground placeholder:text-muted-foreground max-h-36 min-h-6 flex-1 resize-none bg-transparent py-0 text-[15px] outline-none disabled:opacity-60"
              />
            )}
            <button
              type="button"
              onClick={() => setIsRecording((recording) => !recording)}
              aria-label={isRecording ? '음성 입력 중지' : '음성 입력 시작'}
              aria-pressed={isRecording}
              className={`shrink-0 rounded-2xl p-2.5 transition-colors ${
                isRecording
                  ? 'bg-red-500 text-white hover:bg-red-500/90'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              }`}
            >
              <Mic className="h-4 w-4" />
            </button>
            {isSending ? (
              <button
                type="button"
                onClick={onStop}
                aria-label="응답 중지"
                title="응답 중지"
                className="border-foreground bg-background text-foreground hover:bg-muted shrink-0 rounded-2xl border-2 p-2.5 transition-colors"
              >
                <Square className="h-4 w-4 fill-current" />
              </button>
            ) : canSend ? (
              <button
                type="button"
                onClick={() => void submit()}
                disabled={disabled || isPreparingAttachments}
                aria-label="메시지 보내기"
                className="bg-foreground text-background hover:bg-foreground/85 shrink-0 rounded-2xl p-2.5 transition-colors disabled:opacity-40"
              >
                {isPreparingAttachments ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            ) : null}
          </div>
          {statusMessage && (
            <p className="text-muted-foreground border-border/60 border-t px-5 py-2 text-xs">
              {statusMessage}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

async function readAttachmentPayload(file: File): Promise<ChatAttachmentPayload> {
  const base = {
    id: `${file.name}-${file.lastModified}-${file.size}`,
    name: file.name,
    type: file.type || 'application/octet-stream',
    size: file.size,
    lastModified: file.lastModified,
    isImage: file.type.startsWith('image/'),
  }

  if (file.size > MAX_ATTACHMENT_BYTES) {
    return {
      ...base,
      error: `File is larger than ${Math.round(MAX_ATTACHMENT_BYTES / 1024 / 1024)}MB.`,
    }
  }

  const [dataUrl, text] = await Promise.all([
    readFileAsDataUrl(file),
    shouldReadAsText(file) ? readFileAsText(file) : Promise.resolve(undefined),
  ])

  return {
    ...base,
    dataUrl,
    ...(text === undefined
      ? {}
      : {
          text: text.length > MAX_TEXT_CHARS ? text.slice(0, MAX_TEXT_CHARS) : text,
          textTruncated: text.length > MAX_TEXT_CHARS,
        }),
  }
}

function shouldReadAsText(file: File) {
  if (file.type.startsWith('text/')) return true
  return /\.(csv|json|log|md|txt|xml|yaml|yml)$/i.test(file.name)
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '')
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read attachment.'))
    reader.readAsDataURL(file)
  })
}

function readFileAsText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '')
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read attachment text.'))
    reader.readAsText(file)
  })
}
