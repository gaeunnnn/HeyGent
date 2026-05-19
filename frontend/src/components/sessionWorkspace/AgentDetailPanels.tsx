import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  FolderOpen,
  GripVertical,
  HelpCircle,
  Loader2,
  MoreHorizontal,
  Pause,
  Plus,
  Search,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { HelpHint } from '@/components/ui/help-hint'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { AgentRunItemData } from '@/components/sessionWorkspace/agentRuns/types'
import { parseServerTimestamp } from '@/components/sessionWorkspace/agentUsageDisplay'
import {
  createCustomSkill,
  generateCustomSkillDraft,
  importCustomSkillFromUrl,
  type CustomSkillDraft,
  type SkillCatalogItem,
} from '@/apis/agents'

export interface AgentSummaryItemData {
  label: string
  value: ReactNode
  onSelect?: () => void
}

export interface AgentMetricItem {
  icon?: LucideIcon
  label: string
  value: ReactNode
  description?: ReactNode
  chart?: ReactNode
}

export interface AgentUsageMetricRecord {
  createdAt?: string
  totalTokens?: number
  estimatedCostUsd?: number
}

export interface AgentUsageRowData {
  cost: ReactNode
  date: ReactNode
  input: ReactNode
  output: ReactNode
  run: ReactNode
}

export interface AgentSkillRowData {
  key: string
  name: string
  description?: ReactNode
  detail?: ReactNode
  locationLabel?: string
  originLabel?: string
  linkLabel?: string
  readOnly?: boolean
  required?: boolean
  requiredReason?: string
  checked?: boolean
  disabled?: boolean
}

export interface AgentBudgetSummaryData {
  amountLabel: string
  observedLabel: string
  remainingLabel: string
  scopeName: string
  scopeType: string
  status: 'healthy' | 'warning' | 'hard_stop'
  utilizationPercent: number
  warnPercent: number
  windowLabel: string
  paused?: boolean
  pauseReason?: string
}

export interface AgentSelectOption {
  value: string
  label: string
  description?: string
  disabled?: boolean
  badge?: string
}

export function AgentDetailHeader({
  actionsMenu,
  name,
  profile,
  savedIndicator,
  status,
  subtitle,
}: {
  actionsMenu?: ReactNode
  name: string
  profile: ReactNode
  savedIndicator?: ReactNode
  status: string
  subtitle: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-3">
        {profile}
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="truncate text-2xl font-bold">{name}</h2>
            {savedIndicator}
          </div>
          <p className="text-muted-foreground mt-1 truncate text-sm">{subtitle}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 sm:gap-2">
        <Button variant="outline" size="sm" disabled title="작업 배정 기능은 준비 중입니다.">
          <Plus className="h-3.5 w-3.5 sm:mr-1" />
          <span className="hidden sm:inline">작업 배정</span>
        </Button>
        <Button variant="outline" size="sm" disabled title="일시정지 기능은 준비 중입니다.">
          <Pause className="h-3.5 w-3.5 sm:mr-1" />
          <span className="hidden sm:inline">일시정지</span>
        </Button>
        <span className="border-border bg-muted/40 hidden rounded-full border px-2 py-0.5 text-xs sm:inline">
          {status}
        </span>
        {actionsMenu ?? (
          <Button variant="ghost" size="icon-xs" disabled title="추가 작업은 준비 중입니다.">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  )
}

export function AgentDashboardPanel({
  costs,
  latestRun,
  metrics,
  onLatestRunOpen,
  onRecentOpen,
  recentEmptyText,
  recentItems,
  recentTitle,
  usageRows,
}: {
  costs: AgentSummaryItemData[]
  latestRun?: AgentRunItemData | null
  metrics: AgentMetricItem[]
  onLatestRunOpen?: () => void
  onRecentOpen?: () => void
  recentEmptyText: string
  recentItems: AgentSummaryItemData[]
  recentTitle: string
  usageRows?: AgentUsageRowData[]
}) {
  const recentLimit = 10
  const visibleRecentItems = recentItems.slice(0, recentLimit)
  const hiddenRecentCount = Math.max(0, recentItems.length - visibleRecentItems.length)
  const isLive = latestRun ? isLiveRunStatus(latestRun.status) : false
  const visibleUsageRows = (usageRows ?? []).slice(0, 10)

  return (
    <div className="space-y-8 pt-2">
      <section className="space-y-3">
        <div className="flex w-full items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            {isLive ? (
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-pulse rounded-full bg-cyan-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-400" />
              </span>
            ) : null}
            {isLive ? '실시간 실행' : '최근 실행'}
          </h3>
          {latestRun && onLatestRunOpen ? (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground shrink-0 text-xs transition-colors"
              onClick={onLatestRunOpen}
            >
              상세 보기 &rarr;
            </button>
          ) : null}
        </div>
        {latestRun ? (
          <AgentRunSummaryCard run={latestRun} onSelect={onLatestRunOpen} />
        ) : (
          <p className="text-muted-foreground text-sm">아직 실행 기록이 없습니다.</p>
        )}
      </section>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {metrics.map((metric) => (
          <AgentMetricCard key={metric.label} metric={metric} />
        ))}
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-medium">{recentTitle}</h3>
          {onRecentOpen ? (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground text-xs transition-colors"
              onClick={onRecentOpen}
            >
              전체 보기 &rarr;
            </button>
          ) : null}
        </div>
        {recentItems.length === 0 ? (
          <p className="text-muted-foreground text-sm">{recentEmptyText}</p>
        ) : (
          <div className="divide-border divide-y rounded-md border">
            {visibleRecentItems.map((item) => (
              <div key={item.label} className="px-3 py-0">
                <AgentRecentSummaryItem
                  label={item.label}
                  onSelect={item.onSelect}
                  value={item.value}
                />
              </div>
            ))}
            {hiddenRecentCount > 0 ? (
              <div className="text-muted-foreground px-4 py-2 text-center text-xs">
                +{hiddenRecentCount}개 더 있음
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-medium">사용량</h3>
        <div className="space-y-4">
          <div className="border-border rounded-lg border p-4">
            <AgentSummaryGrid items={costs} columns="four" />
          </div>
          <div className="border-border overflow-hidden rounded-lg border">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-accent/20 border-border border-b">
                  <th className="text-muted-foreground px-3 py-2 text-left font-medium">날짜</th>
                  <th className="text-muted-foreground px-3 py-2 text-left font-medium">실행</th>
                  <th className="text-muted-foreground px-3 py-2 text-right font-medium">입력</th>
                  <th className="text-muted-foreground px-3 py-2 text-right font-medium">출력</th>
                  <th className="text-muted-foreground px-3 py-2 text-right font-medium">비용</th>
                </tr>
              </thead>
              <tbody>
                {visibleUsageRows.length > 0 ? (
                  visibleUsageRows.map((row, index) => (
                    <tr key={index} className="border-border border-b last:border-b-0">
                      <td className="px-3 py-2">{row.date}</td>
                      <td className="px-3 py-2 font-mono">{row.run}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.input}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.output}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.cost}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="text-muted-foreground px-3 py-4 text-center" colSpan={5}>
                      아직 사용량 기록이 없습니다.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  )
}

export function AgentInstructionsPanel({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-5xl space-y-6 pt-2">
      <InstructionsHelp />
      {children}
    </div>
  )
}

function InstructionsHelp() {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-border bg-muted/30 rounded-lg border">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="hover:bg-muted/50 flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-colors"
      >
        <HelpCircle className="text-muted-foreground h-4 w-4 shrink-0" />
        <span className="text-foreground flex-1 font-medium">지침이란?</span>
        <ChevronDown
          className={`text-muted-foreground h-4 w-4 shrink-0 transition-transform ${
            open ? 'rotate-180' : ''
          }`}
        />
      </button>
      {open && (
        <div className="border-border space-y-4 border-t px-4 py-3 text-sm leading-relaxed break-keep">
          <div className="space-y-2.5">
            <p className="text-muted-foreground">
              에이전트에게 주는 <span className="text-foreground">업무 안내서</span>예요.
            </p>
            <p className="text-muted-foreground">
              역할·말투·해야 할 일을 적어두면, 매번 다시 설명하지 않아도 그대로 따라줍니다.
            </p>
            <p className="text-muted-foreground">
              <span className="text-foreground font-mono">.md</span> 파일은 메모장처럼 글을 적는
              파일이에요. 한국어 문장 그대로 편하게 적으시면 됩니다.
            </p>
            <p className="text-muted-foreground">
              왼쪽 목록의 <span className="text-foreground">대표</span> 파일이 표지 안내서, 나머지는
              주제별 부록입니다.
            </p>
          </div>

          <div className="border-border/70 space-y-2.5 border-t pt-3">
            <p className="text-foreground font-semibold">자주 쓰는 마크다운 문법</p>
            <p className="text-muted-foreground">
              <span className="text-foreground underline">한국어로만 적어도 충분합니다.</span> 글을
              더 보기 좋게 정리하고 싶을 때만 아래 표기를 섞어 쓰세요.
            </p>
            <ul className="text-muted-foreground space-y-1.5">
              <li>
                <span className="text-foreground font-mono">#</span> 큰 제목 ·{' '}
                <span className="text-foreground font-mono">##</span> 작은 제목 — 줄 맨 앞에
                <span className="font-mono"> # </span>을 붙이고 한 칸 띄운 뒤 제목을 적어요.
                <span className="font-mono"> # </span>이 많을수록 작은 제목이 됩니다.
              </li>
              <li>
                <span className="text-foreground font-mono">-</span> 또는{' '}
                <span className="text-foreground font-mono">*</span> 목록 — 줄 맨 앞에
                <span className="font-mono"> - </span>를 적고 한 칸 띄운 뒤 항목을 쓰면 글머리표가
                생깁니다.
              </li>
              <li>
                <span className="text-foreground font-mono">&gt;</span> 인용문 — 줄 맨 앞에{' '}
                <span className="font-mono">&gt; </span>를 붙이면 들여쓰기된 인용 영역이 됩니다.
                중요한 규칙이나 예시 강조에 좋아요.
              </li>
            </ul>
            <p className="text-muted-foreground">
              예) <span className="text-foreground font-mono"># 우리 팀 안내</span> 줄을 만들고 그
              아래에 <span className="text-foreground font-mono">- 정중한 말투 사용</span> 같은
              식으로 항목을 적으시면 됩니다.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export function AgentSkillsPanel({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-4xl space-y-5 pt-2">
      <div className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
        <span>스킬이란?</span>
        <HelpHint label="스킬 도움말">
          <p className="text-foreground font-medium">스킬</p>
          <p>
            에이전트가 쓸 수 있는 <span className="text-foreground">도구</span>예요.
          </p>
          <p>
            오른쪽 목록의 항목을 <span className="text-foreground">왼쪽으로 옮기면</span> 에이전트가
            그 스킬을 사용할 수 있게 됩니다. 다시 오른쪽으로 옮기면 사용을 멈춥니다.
          </p>
          <p>
            예) <span className="text-foreground">노션</span>을 왼쪽으로 옮기면 노션 문서를 읽고
            페이지를 만들거나 정리할 수 있어요.
          </p>
        </HelpHint>
      </div>
      {children}
    </div>
  )
}

export function AgentConfigurationPanel({ children }: { children: ReactNode }) {
  return <div className="max-w-6xl space-y-4 pt-2">{children}</div>
}

export function AgentInstructionsBundlePanel({
  compact = false,
  content,
  entryFile,
  files = {},
  onContentChange,
  onFilesChange,
}: {
  compact?: boolean
  content: string
  entryFile: string
  files?: Record<string, string>
  mode: 'managed' | 'external'
  rootPath: string
  onContentChange: (value: string) => void
  onEntryFileChange: (value: string) => void
  onFilesChange?: (files: Record<string, string>) => void
  onModeChange: (value: 'managed' | 'external') => void
  onRootPathChange: (value: string) => void
}) {
  const [newFilePath, setNewFilePath] = useState('')
  const [selectedFile, setSelectedFile] = useState('')
  const [showFilesMobile, setShowFilesMobile] = useState(false)
  const normalizedEntryFile = entryFile.trim() || 'AGENTS.md'
  const visibleFiles = Array.from(new Set([normalizedEntryFile, ...Object.keys(files)])).sort(
    (left, right) =>
      left === normalizedEntryFile
        ? -1
        : right === normalizedEntryFile
          ? 1
          : left.localeCompare(right),
  )
  const selectedOrEntryFile = visibleFiles.includes(selectedFile)
    ? selectedFile
    : normalizedEntryFile
  const selectedContent =
    selectedOrEntryFile === normalizedEntryFile ? content : (files[selectedOrEntryFile] ?? '')

  const updateSelectedContent = (value: string) => {
    if (selectedOrEntryFile === normalizedEntryFile) {
      onContentChange(value)
      return
    }
    onFilesChange?.({ ...files, [selectedOrEntryFile]: value })
  }

  const addFile = () => {
    const nextPath = normalizeInstructionPath(newFilePath)
    if (!nextPath || visibleFiles.includes(nextPath)) return
    onFilesChange?.({ ...files, [nextPath]: '' })
    setSelectedFile(nextPath)
    setNewFilePath('')
  }

  const deleteFile = (filePath: string) => {
    if (filePath === normalizedEntryFile) return
    const nextFiles = { ...files }
    delete nextFiles[filePath]
    onFilesChange?.(nextFiles)
    if (selectedOrEntryFile === filePath) setSelectedFile(normalizedEntryFile)
  }

  return (
    <div className={compact ? 'space-y-4' : 'space-y-6'}>
      <div
        className={`grid min-w-0 gap-3 ${
          compact ? 'lg:grid-cols-[220px_minmax(0,1fr)]' : 'lg:grid-cols-[260px_minmax(0,1fr)]'
        }`}
      >
        <div
          className={`border-border min-w-0 rounded-lg border ${compact ? 'p-2.5' : 'p-3'} ${
            showFilesMobile ? 'block' : 'hidden lg:block'
          }`}
        >
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-medium">지침 문서</h4>
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-7 w-7 lg:hidden"
              onClick={() => setShowFilesMobile(false)}
              aria-label="파일 목록 닫기"
            >
              x
            </Button>
          </div>
          <div className="mb-3 flex gap-2">
            <input
              value={newFilePath}
              onChange={(event) => setNewFilePath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  addFile()
                }
              }}
              className={`${agentTextInputClass} min-w-0`}
              placeholder="NOTES.md"
            />
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-8 w-8 shrink-0"
              onClick={addFile}
              disabled={!normalizeInstructionPath(newFilePath)}
              aria-label="지침 파일 추가"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="border-border overflow-hidden rounded-md border">
            {visibleFiles.map((filePath) => (
              <button
                key={filePath}
                type="button"
                className={`hover:bg-accent/40 flex w-full items-center justify-between gap-2 border-b px-2 py-2 text-left text-sm last:border-b-0 ${
                  selectedOrEntryFile === filePath ? 'bg-accent/40' : ''
                }`}
                onClick={() => setSelectedFile(filePath)}
              >
                <span className="min-w-0 truncate font-mono">{filePath}</span>
                <span className="flex shrink-0 items-center gap-1">
                  {filePath === normalizedEntryFile ? (
                    <span className="border-border text-muted-foreground rounded border px-1.5 py-0.5 text-[10px] tracking-wide uppercase">
                      대표
                    </span>
                  ) : null}
                  {filePath !== normalizedEntryFile ? (
                    <span
                      role="button"
                      tabIndex={0}
                      className="text-muted-foreground hover:bg-background hover:text-destructive inline-flex h-6 w-6 items-center justify-center rounded"
                      onClick={(event) => {
                        event.stopPropagation()
                        deleteFile(filePath)
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          event.stopPropagation()
                          deleteFile(filePath)
                        }
                      }}
                      aria-label={`${filePath} 삭제`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div
          className={`border-border min-w-0 overflow-hidden rounded-lg border ${
            compact ? 'p-3' : 'p-4'
          }`}
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="h-7 w-7 shrink-0 lg:hidden"
                onClick={() => setShowFilesMobile(true)}
                aria-label="파일 목록 열기"
              >
                <FolderOpen className="h-3.5 w-3.5" />
              </Button>
              <div className="min-w-0">
                <h4 className="truncate font-mono text-sm font-medium">{selectedOrEntryFile}</h4>
                <p className="text-muted-foreground text-xs">지침 문서</p>
              </div>
            </div>
            <button
              type="button"
              className="text-muted-foreground hover:bg-accent hover:text-foreground inline-flex h-8 w-8 items-center justify-center rounded-md border"
              onClick={() => void navigator.clipboard.writeText(selectedContent)}
              aria-label="지침 파일 복사"
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
          <textarea
            value={selectedContent}
            onChange={(event) => updateSelectedContent(event.target.value)}
            className={`${agentTextInputClass} ${
              compact ? 'min-h-[300px] resize-none' : 'min-h-[420px] resize-y'
            } leading-6 whitespace-pre-wrap`}
            placeholder="# 지침"
          />
        </div>
      </div>
    </div>
  )
}

export function AgentBudgetPanel({
  summary,
  onBudgetChange,
}: {
  summary: AgentBudgetSummaryData
  onBudgetChange?: (value: string) => void
}) {
  const [draftBudget, setDraftBudget] = useState('')
  const [savedBudgetLabel, setSavedBudgetLabel] = useState(summary.amountLabel)
  const progress = Math.max(0, Math.min(100, summary.utilizationPercent))
  const parsedBudget = parseBudgetInput(draftBudget)
  const canSaveBudget = parsedBudget !== null && draftBudget.trim() !== ''
  return (
    <div className="max-w-3xl space-y-6 pt-2">
      <div className="flex items-start justify-between gap-6">
        <div>
          <div className="text-muted-foreground text-[11px] tracking-[0.22em] uppercase">
            {summary.scopeType}
          </div>
          <div className="mt-2 text-xl font-semibold">{summary.scopeName}</div>
          <div className="text-muted-foreground mt-2 text-sm">{summary.windowLabel}</div>
        </div>
        <div
          className={`inline-flex items-center gap-2 text-[11px] tracking-[0.18em] uppercase ${
            summary.status === 'hard_stop'
              ? 'text-red-600'
              : summary.status === 'warning'
                ? 'text-amber-600'
                : 'text-muted-foreground'
          }`}
        >
          {summary.paused ? '일시 중지' : statusLabel(summary.status)}
        </div>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <div className="text-muted-foreground text-[11px] tracking-[0.18em] uppercase">
            사용액
          </div>
          <div className="mt-2 text-xl font-semibold tabular-nums">{summary.observedLabel}</div>
          <div className="text-muted-foreground mt-1 text-xs">
            한도의 {summary.utilizationPercent}%
          </div>
        </div>
        <div>
          <div className="text-muted-foreground text-[11px] tracking-[0.18em] uppercase">예산</div>
          <div className="mt-2 text-xl font-semibold tabular-nums">{savedBudgetLabel}</div>
          <div className="text-muted-foreground mt-1 text-xs">
            {summary.warnPercent}%에서 알림
            {summary.paused && summary.pauseReason ? ` · ${summary.pauseReason} 중지` : ''}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-muted-foreground flex items-center justify-between text-xs">
          <span>남은 예산</span>
          <span>{summary.remainingLabel}</span>
        </div>
        <div className="bg-border/70 h-2 overflow-hidden rounded-full">
          <div
            className={`h-full rounded-full transition-[width,background-color] duration-200 ${
              summary.status === 'hard_stop'
                ? 'bg-red-400'
                : summary.status === 'warning'
                  ? 'bg-amber-300'
                  : 'bg-emerald-300'
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {summary.paused ? (
        <div className="border-border bg-destructive/10 text-destructive rounded-xl border px-3 py-2 text-sm">
          예산을 올리거나 중지 사유를 해제할 때까지 이 범위의 실행이 멈춥니다.
        </div>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 space-y-2">
          <span className="text-muted-foreground text-[11px] tracking-[0.18em] uppercase">
            예산 (USD)
          </span>
          <input
            value={draftBudget}
            className={agentTextInputClass}
            inputMode="decimal"
            placeholder="0.00"
            onChange={(event) => setDraftBudget(event.target.value)}
          />
        </label>
        <Button
          type="button"
          disabled={!canSaveBudget}
          onClick={() => {
            if (parsedBudget === null) return
            const nextLabel = parsedBudget === 0 ? '사용 안 함' : `$${parsedBudget.toFixed(2)}`
            setSavedBudgetLabel(nextLabel)
            onBudgetChange?.(draftBudget)
          }}
        >
          {savedBudgetLabel === '사용 안 함' || savedBudgetLabel === 'Disabled'
            ? '예산 설정'
            : '예산 변경'}
        </Button>
      </div>
      {parsedBudget === null ? (
        <p className="text-destructive text-xs">0 이상의 올바른 금액을 입력하세요.</p>
      ) : null}
    </div>
  )
}

export function AgentSkillsLibraryPanel({
  adapterLabel,
  applicationLabel,
  missingSkills = [],
  onSkillCreated,
  onSkillOpen,
  onSkillReorder,
  onSkillToggle,
  rows,
  saving,
  selectedCount,
  unsupportedMessage,
  warnings = [],
}: {
  adapterLabel: string
  applicationLabel: string
  missingSkills?: string[]
  onSkillCreated?: (skill: SkillCatalogItem) => void
  onSkillOpen?: (key: string) => void
  onSkillReorder?: (orderedSkillIds: string[]) => void
  onSkillToggle?: (key: string, checked: boolean) => void
  rows: AgentSkillRowData[]
  saving?: boolean
  selectedCount: number
  unsupportedMessage?: string | null
  warnings?: string[]
}) {
  const optionalRows = rows.filter((row) => !row.required && !row.readOnly)
  const requiredRows = rows.filter((row) => row.required)
  const unmanagedRows = rows.filter((row) => row.readOnly)
  const enabledRows = optionalRows.filter((row) => row.checked)
  const disabledRows = optionalRows.filter((row) => !row.checked)
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor))
  const [selectedSkillKey, setSelectedSkillKey] = useState<string | null>(null)
  const [draggingSkillKey, setDraggingSkillKey] = useState<string | null>(null)
  const [skillSearch, setSkillSearch] = useState('')
  const [unmanagedOpen, setUnmanagedOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const saveStatusLabel = saving ? 'Saving changes...' : null
  const normalizedSkillSearch = normalizeSkillSearch(skillSearch)
  const filteredEnabledRows = filterSkillRows(enabledRows, normalizedSkillSearch)
  const filteredDisabledRows = filterSkillRows(disabledRows, normalizedSkillSearch)
  const selectedRow = optionalRows.find((row) => row.key === selectedSkillKey)
  const selectedSide =
    selectedRow === undefined
      ? null
      : enabledRows.some((row) => row.key === selectedRow.key)
        ? 'enabled'
        : 'disabled'

  const openSkill = (key: string) => {
    setSelectedSkillKey(key)
    onSkillOpen?.(key)
  }

  const moveSelectedSkill = (checked: boolean) => {
    if (selectedRow === undefined || selectedRow.disabled) return
    onSkillToggle?.(selectedRow.key, checked)
  }

  const handleDragStart = (event: DragStartEvent) => {
    setDraggingSkillKey(String(event.active.id))
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setDraggingSkillKey(null)
    const target = getSkillTransferTarget(event.over?.id, optionalRows)
    if (target === null) return
    const key = String(event.active.id)
    const row = optionalRows.find((item) => item.key === key)
    if (row === undefined || row.disabled) return
    setSelectedSkillKey(key)

    if (target.side === 'enabled') {
      const currentEnabledKeys = enabledRows.map((item) => item.key).filter((item) => item !== key)
      const insertIndex = getSkillInsertIndex(event, currentEnabledKeys, target.key)
      const nextEnabledKeys = insertSkillKey(currentEnabledKeys, key, insertIndex)
      if (
        !stringArraysEqual(
          nextEnabledKeys,
          enabledRows.map((item) => item.key),
        )
      ) {
        onSkillReorder?.(nextEnabledKeys)
        if (onSkillReorder === undefined && !row.checked) {
          onSkillToggle?.(key, true)
        }
      }
      return
    }

    if (row.checked) {
      onSkillToggle?.(key, false)
    }
  }

  const draggedRow = optionalRows.find((row) => row.key === draggingSkillKey)

  if (rows.length === 0) {
    return (
      <div className="max-w-4xl space-y-5">
        {saveStatusLabel ? <AgentSavingIndicator label={saveStatusLabel} /> : null}
        <section className="border-border border-y">
          <div className="text-muted-foreground px-3 py-6 text-sm">
            먼저 스킬 목록을 불러온 뒤 이 에이전트에 적용할 수 있습니다.
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-5">
      {saveStatusLabel ? <AgentSavingIndicator label={saveStatusLabel} /> : null}

      {warnings.length > 0 ? (
        <div className="space-y-1 rounded-xl border border-amber-300/60 bg-amber-50/60 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      {unsupportedMessage ? (
        <div className="border-border text-muted-foreground rounded-xl border px-4 py-3 text-sm">
          {unsupportedMessage}
        </div>
      ) : null}

      {optionalRows.length > 0 ? (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setDraggingSkillKey(null)}
        >
          <div className="flex min-w-0 gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
              <input
                value={skillSearch}
                className={`${agentTextInputClass} pl-8 font-sans`}
                placeholder="스킬 검색"
                onChange={(event) => setSkillSearch(event.target.value)}
              />
            </div>
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-9 w-9 shrink-0"
              onClick={() => setCreateOpen(true)}
              aria-label="스킬 추가"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <section className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-start">
            <AgentSkillTransferColumn
              countLabel={formatSkillColumnCount(filteredEnabledRows.length, enabledRows.length)}
              emptyLabel={
                normalizedSkillSearch ? '검색 결과가 없습니다.' : '사용 중인 스킬이 없습니다.'
              }
              id="enabled-skills"
              rows={filteredEnabledRows}
              selectedKey={selectedSkillKey}
              title="사용 중"
              onSkillOpen={openSkill}
            />
            <div className="flex items-center justify-center gap-2 md:flex-col md:pt-12">
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="h-9 w-9"
                onClick={() => moveSelectedSkill(true)}
                disabled={selectedSide !== 'disabled' || selectedRow?.disabled}
                aria-label="선택한 스킬 사용"
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="h-9 w-9"
                onClick={() => moveSelectedSkill(false)}
                disabled={selectedSide !== 'enabled'}
                aria-label="선택한 스킬 미사용"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
            <AgentSkillTransferColumn
              countLabel={formatSkillColumnCount(filteredDisabledRows.length, disabledRows.length)}
              emptyLabel={
                normalizedSkillSearch ? '검색 결과가 없습니다.' : '미사용 스킬이 없습니다.'
              }
              id="disabled-skills"
              rows={filteredDisabledRows}
              selectedKey={selectedSkillKey}
              title="미사용"
              onSkillOpen={openSkill}
            />
          </section>
          <DragOverlay dropAnimation={{ duration: 180, easing: 'cubic-bezier(0.2, 0, 0, 1)' }}>
            {draggedRow ? <AgentSkillDragOverlayCard row={draggedRow} /> : null}
          </DragOverlay>
        </DndContext>
      ) : null}

      {requiredRows.length > 0 ? (
        <AgentSkillTransferReadonlyGroup
          rows={requiredRows}
          selectedKey={selectedSkillKey}
          title="시스템 필수 스킬"
          onSkillOpen={openSkill}
        />
      ) : null}

      {unmanagedRows.length > 0 ? (
        <section className="border-border border-y">
          <button
            type="button"
            className="border-border bg-muted/40 flex w-full cursor-pointer items-center gap-2 border-b px-3 py-2 text-left select-none"
            onClick={() => setUnmanagedOpen((open) => !open)}
          >
            <span className="text-muted-foreground text-xs font-medium">
              사용자 추가 스킬 {unmanagedRows.length}개, 여기서는 관리하지 않음
            </span>
            {unmanagedOpen ? (
              <ChevronDown className="text-muted-foreground h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="text-muted-foreground h-3.5 w-3.5" />
            )}
          </button>
          {unmanagedOpen
            ? unmanagedRows.map((row) => (
                <AgentSkillTransferReadonlyItem
                  key={row.key}
                  row={row}
                  selected={selectedSkillKey === row.key}
                  onSkillOpen={openSkill}
                />
              ))
            : null}
        </section>
      ) : null}

      {missingSkills.length > 0 ? (
        <div className="rounded-xl border border-amber-300/60 bg-amber-50/60 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200">
          <div className="font-medium">회사 스킬 목록에 없는 요청 스킬</div>
          <div className="mt-1 text-xs">{missingSkills.join(', ')}</div>
        </div>
      ) : null}

      <section className="border-border border-t pt-4">
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <AgentInlineSummary label="실행 방식" value={adapterLabel} />
          <AgentInlineSummary label="적용 범위" value={applicationLabel} />
          <AgentInlineSummary label="선택한 스킬" value={selectedCount} />
        </div>
      </section>

      <CreateSkillDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(skill) => {
          onSkillCreated?.(skill)
          setSelectedSkillKey(skill.skillId)
        }}
      />
    </div>
  )
}

export function AgentSectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="border-border bg-background space-y-4 rounded-lg border p-4">{children}</div>
    </section>
  )
}

const agentTextInputClass =
  'border-border placeholder:text-muted-foreground/40 focus-visible:ring-ring w-full rounded-md border bg-transparent px-2.5 py-1.5 font-mono text-sm outline-none focus-visible:ring-2'

function CreateSkillDialog({
  open,
  onCreated,
  onOpenChange,
}: {
  open: boolean
  onCreated: (skill: SkillCatalogItem) => void
  onOpenChange: (open: boolean) => void
}) {
  const [step, setStep] = useState<SkillWizardStep>('entry')
  const [source, setSource] = useState<'ai' | 'url' | null>(null)
  const [aiGoal, setAiGoal] = useState('')
  const [url, setUrl] = useState('')
  const [draft, setDraft] = useState<SkillDraftForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const draftRequestingRef = useRef(false)
  const canSave = draft !== null && draft.displayName.trim() !== '' && !saving

  const reset = () => {
    setStep('entry')
    setSource(null)
    setAiGoal('')
    setUrl('')
    setDraft(null)
    setSaving(false)
    setGenerating(false)
    draftRequestingRef.current = false
    setError(null)
  }

  const closeDialog = () => {
    reset()
    onOpenChange(false)
  }

  const createDraftFromAi = async () => {
    if (draftRequestingRef.current) return
    if (!aiGoal.trim()) {
      setError('만들고 싶은 스킬의 용도를 적어주세요.')
      return
    }
    draftRequestingRef.current = true
    setError(null)
    setGenerating(true)
    setStep('generating')
    try {
      const generated = await generateCustomSkillDraft({ goal: aiGoal })
      setDraft(skillDraftToForm(generated))
      setStep('basic')
    } catch {
      setStep('aiInput')
      setError('초안을 만들지 못했어요. 잠시 후 다시 시도하세요.')
    } finally {
      draftRequestingRef.current = false
      setGenerating(false)
    }
  }

  const createDraftFromUrl = async () => {
    if (draftRequestingRef.current) return
    if (!url.trim()) {
      setError('가져올 URL을 입력하세요.')
      return
    }
    draftRequestingRef.current = true
    setError(null)
    setGenerating(true)
    setStep('generating')
    try {
      const imported = await importCustomSkillFromUrl({ url })
      setDraft(skillDraftToForm(imported))
      setStep('basic')
    } catch {
      setStep('urlInput')
      setError('URL을 읽지 못했어요. 공개된 문서 주소인지 확인하고 다시 시도하세요.')
    } finally {
      draftRequestingRef.current = false
      setGenerating(false)
    }
  }

  const handleSubmit = async () => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const created = await createCustomSkill({
        name: normalizeCustomSkillName(draft.key || draft.displayName),
        displayName: draft.displayName.trim(),
        description: draft.description.trim(),
        body: draft.rawEdited ? draft.rawBody : buildSkillBody(draft),
        documents: draft.references
          .filter((reference) => reference.title.trim() && reference.content.trim())
          .map((reference, index) => ({
            documentKey: referenceDocumentKey(reference, index),
            title: reference.title.trim(),
            content: reference.content.trim(),
          })),
      })
      onCreated(created)
      closeDialog()
    } catch {
      setError('저장하지 못했어요. 잠시 후 다시 시도하세요.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) onOpenChange(true)
        else closeDialog()
      }}
    >
      <DialogContent className="max-h-[86vh] max-w-3xl overflow-hidden p-0">
        <DialogHeader className="border-border border-b px-5 py-4">
          <DialogTitle>스킬 추가</DialogTitle>
          <DialogDescription>에이전트가 반복해서 따를 작업 방식을 만듭니다.</DialogDescription>
        </DialogHeader>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {isDraftStep(step) ? <SkillWizardSteps current={step} /> : null}

          {step === 'entry' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="어떻게 시작할까요?"
                description="먼저 초안을 만드는 방법을 고르세요. 저장 전까지 현재 에이전트에는 적용되지 않습니다."
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  className="border-primary/30 bg-primary/5 hover:bg-primary/10 rounded-lg border p-4 text-left transition-colors"
                  onClick={() => {
                    setSource('ai')
                    setStep('aiInput')
                    setError(null)
                  }}
                >
                  <div className="text-base font-semibold">AI로 만들기</div>
                  <p className="text-muted-foreground mt-2 text-sm leading-6">
                    어떤 일을 맡길지 적으면 스킬 초안을 만들어요.
                  </p>
                </button>
                <button
                  type="button"
                  className="border-border hover:bg-accent/40 rounded-lg border p-4 text-left transition-colors"
                  onClick={() => {
                    setSource('url')
                    setStep('urlInput')
                    setError(null)
                  }}
                >
                  <div className="text-base font-semibold">URL로 가져오기</div>
                  <p className="text-muted-foreground mt-2 text-sm leading-6">
                    공개 문서나 페이지 주소를 읽어 초안으로 바꿔요.
                  </p>
                </button>
              </div>
            </div>
          ) : null}

          {step === 'aiInput' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="무슨 용도로 쓰고 싶나요?"
                description="어떤 상황에서 어떤 결과를 더 잘 만들고 싶은지 적어주세요."
              />
              <label className="space-y-2">
                <span className="text-sm font-medium">스킬 용도</span>
                <textarea
                  value={aiGoal}
                  onChange={(event) => setAiGoal(event.target.value)}
                  className={`${agentTextInputClass} min-h-[220px] resize-y font-sans leading-6`}
                  placeholder="예: QA가 결제 오류 리포트를 빠르게 분류하고 재현 절차를 남기기 위한 스킬"
                />
              </label>
              <div className="grid gap-2 sm:grid-cols-3">
                {[
                  '프론트엔드 PR에서 접근성, 상태 처리, 에러 처리를 점검하기 위한 스킬',
                  '장애 대응 기록에서 원인, 재발 방지, 후속 조치를 남기기 위한 스킬',
                  '사내 API 문서를 새 팀원이 바로 따라 할 수 있게 안내하기 위한 스킬',
                ].map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="border-border text-muted-foreground hover:bg-accent/40 rounded-md border px-3 py-2 text-left text-xs leading-5"
                    onClick={() => setAiGoal(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {step === 'urlInput' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="어디서 가져올까요?"
                description="공개된 문서, GitHub의 스킬 문서, 또는 설명 페이지 주소를 넣으세요."
              />
              <label className="space-y-2">
                <span className="text-sm font-medium">URL</span>
                <input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  className={`${agentTextInputClass} font-sans`}
                  placeholder="https://..."
                />
              </label>
              <p className="text-muted-foreground text-sm leading-6">
                주소의 내용을 읽어 초안을 만들고, 다음 단계에서 이름과 작업 방식을 나눠 확인합니다.
              </p>
            </div>
          ) : null}

          {step === 'generating' ? (
            <div className="flex min-h-[320px] flex-col items-center justify-center text-center">
              <Loader2 className="text-primary mb-4 h-8 w-8 animate-spin" />
              <div className="text-base font-semibold">
                {source === 'url' ? 'URL을 읽고 있어요' : '초안을 만드는 중이에요'}
              </div>
              <p className="text-muted-foreground mt-2 max-w-sm text-sm leading-6">
                내용을 정리하는 동안 다른 단계로 이동할 수 없습니다. 잠시만 기다려주세요.
              </p>
            </div>
          ) : null}

          {draft && step === 'basic' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="이름과 용도를 확인하세요"
                description="스킬 목록에 보일 이름과 에이전트가 이 스킬을 고르는 기준입니다."
              />
              <label className="space-y-2">
                <span className="text-sm font-medium">이름</span>
                <input
                  value={draft.displayName}
                  onChange={(event) => setDraft({ ...draft, displayName: event.target.value })}
                  className={`${agentTextInputClass} font-sans`}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">한 줄 설명</span>
                <textarea
                  value={draft.description}
                  onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                  className={`${agentTextInputClass} min-h-24 resize-y font-sans leading-6`}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">사용하는 상황</span>
                <textarea
                  value={draft.useCases}
                  onChange={(event) => setDraft({ ...draft, useCases: event.target.value })}
                  className={`${agentTextInputClass} min-h-24 resize-y font-sans leading-6`}
                  placeholder="예: 회의록, 음성 기록, 긴 논의 내용을 정리할 때"
                />
              </label>
            </div>
          ) : null}

          {draft && step === 'workflow' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="작업 방식을 다듬으세요"
                description="에이전트가 실제로 따라야 할 순서와 결과 기준입니다."
              />
              <label className="space-y-2">
                <span className="text-sm font-medium">처리 순서</span>
                <textarea
                  value={draft.steps}
                  onChange={(event) => setDraft({ ...draft, steps: event.target.value })}
                  className={`${agentTextInputClass} min-h-40 resize-y font-sans leading-6`}
                  placeholder={
                    '1. 입력 내용을 확인한다\n2. 핵심 항목을 분류한다\n3. 결과를 정리한다'
                  }
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">결과 형식</span>
                <textarea
                  value={draft.outputFormat}
                  onChange={(event) => setDraft({ ...draft, outputFormat: event.target.value })}
                  className={`${agentTextInputClass} min-h-24 resize-y font-sans leading-6`}
                  placeholder="예: 요약, 결정 사항, 담당자, 다음 할 일 순서로 답변"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">주의할 점</span>
                <textarea
                  value={draft.cautions}
                  onChange={(event) => setDraft({ ...draft, cautions: event.target.value })}
                  className={`${agentTextInputClass} min-h-24 resize-y font-sans leading-6`}
                  placeholder="예: 확인되지 않은 내용은 추측하지 않기"
                />
              </label>
            </div>
          ) : null}

          {draft && step === 'references' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="참고 자료를 확인하세요"
                description="에이전트가 필요할 때 함께 참고할 내용입니다. 없어도 저장할 수 있습니다."
              />
              <div className="space-y-3">
                {draft.references.length === 0 ? (
                  <div className="border-border text-muted-foreground rounded-md border px-3 py-6 text-sm">
                    참고 자료가 없습니다.
                  </div>
                ) : (
                  draft.references.map((reference, index) => (
                    <div
                      key={reference.id}
                      className="border-border space-y-3 rounded-md border p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium">참고 자료 {index + 1}</div>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setDraft({
                              ...draft,
                              references: draft.references.filter(
                                (item) => item.id !== reference.id,
                              ),
                            })
                          }
                        >
                          삭제
                        </Button>
                      </div>
                      <input
                        value={reference.title}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            references: updateReference(draft.references, reference.id, {
                              title: event.target.value,
                            }),
                          })
                        }
                        className={`${agentTextInputClass} font-sans`}
                        placeholder="참고 제목"
                      />
                      <textarea
                        value={reference.content}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            references: updateReference(draft.references, reference.id, {
                              content: event.target.value,
                            }),
                          })
                        }
                        className={`${agentTextInputClass} min-h-32 resize-y font-sans leading-6`}
                        placeholder="참고 내용"
                      />
                    </div>
                  ))
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setDraft({
                    ...draft,
                    references: [
                      ...draft.references,
                      { id: newReferenceId(), title: '', content: '' },
                    ],
                  })
                }
              >
                <Plus className="mr-2 h-4 w-4" />
                참고 자료 추가
              </Button>
            </div>
          ) : null}

          {draft && step === 'review' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="저장하기 전에 확인하세요"
                description="저장하면 현재 에이전트의 스킬 목록에 바로 추가됩니다."
              />
              <div className="border-border divide-border rounded-md border">
                <SkillReviewRow label="이름" value={draft.displayName || '-'} />
                <SkillReviewRow label="한 줄 설명" value={draft.description || '-'} />
                <SkillReviewRow label="사용하는 상황" value={draft.useCases || '-'} />
                <SkillReviewRow
                  label="참고 자료"
                  value={`${draft.references.filter((item) => item.title.trim() || item.content.trim()).length}개`}
                />
              </div>
              <Button type="button" variant="outline" onClick={() => setStep('raw')}>
                고급 원문 보기
              </Button>
            </div>
          ) : null}

          {draft && step === 'raw' ? (
            <div className="space-y-4">
              <SkillWizardHeading
                title="고급 원문"
                description="스킬이 저장될 원문입니다. 필요한 경우에만 수정하세요."
              />
              <textarea
                value={draft.rawEdited ? draft.rawBody : buildSkillBody(draft)}
                onChange={(event) =>
                  setDraft({ ...draft, rawBody: event.target.value, rawEdited: true })
                }
                className={`${agentTextInputClass} min-h-[420px] resize-y font-mono text-xs leading-5`}
                spellCheck={false}
              />
            </div>
          ) : null}

          {error ? <p className="text-destructive mt-4 text-sm">{error}</p> : null}
        </div>

        <div className="border-border flex items-center justify-between gap-2 border-t px-5 py-4">
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              if (step === 'entry') {
                closeDialog()
                return
              }
              if (step === 'aiInput' || step === 'urlInput') {
                setStep('entry')
                setError(null)
                return
              }
              if (step === 'generating') return
              setStep(previousSkillStep(step, source))
              setError(null)
            }}
            disabled={generating || saving}
          >
            {step === 'entry' ? '취소' : '이전'}
          </Button>

          {step === 'entry' ? null : step === 'aiInput' ? (
            <Button type="button" onClick={() => void createDraftFromAi()} disabled={generating}>
              초안 만들기
            </Button>
          ) : step === 'urlInput' ? (
            <Button type="button" onClick={() => void createDraftFromUrl()} disabled={generating}>
              가져오기
            </Button>
          ) : step === 'generating' ? (
            <Button type="button" disabled>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              처리 중
            </Button>
          ) : step === 'review' ? (
            <Button type="button" onClick={() => void handleSubmit()} disabled={!canSave}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              저장하고 사용하기
            </Button>
          ) : step === 'raw' ? (
            <Button type="button" onClick={() => setStep('review')}>
              확인
            </Button>
          ) : (
            <Button type="button" onClick={() => setStep(nextSkillStep(step))}>
              다음
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SkillWizardHeading({ description, title }: { description: string; title: string }) {
  return (
    <div>
      <h3 className="text-foreground text-lg font-semibold">{title}</h3>
      <p className="text-muted-foreground mt-1 text-sm leading-6">{description}</p>
    </div>
  )
}

function SkillWizardSteps({ current }: { current: SkillWizardStep }) {
  const steps: Array<{ id: SkillWizardStep; label: string }> = [
    { id: 'basic', label: '이름과 용도' },
    { id: 'workflow', label: '작업 방식' },
    { id: 'references', label: '참고 자료' },
    { id: 'review', label: '최종 확인' },
  ]
  const currentIndex = steps.findIndex((step) => step.id === current)
  return (
    <div className="mb-5 grid grid-cols-4 gap-2">
      {steps.map((step, index) => (
        <div
          key={step.id}
          className={`rounded-md border px-2 py-2 text-center text-xs ${
            index === currentIndex
              ? 'border-primary/40 bg-primary/10 text-foreground'
              : index < currentIndex
                ? 'border-border bg-muted/40 text-foreground'
                : 'border-border text-muted-foreground'
          }`}
        >
          {step.label}
        </div>
      ))}
    </div>
  )
}

function SkillReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-2 px-3 py-3 text-sm sm:grid-cols-[120px_minmax(0,1fr)]">
      <div className="text-muted-foreground">{label}</div>
      <div className="whitespace-pre-wrap">{value}</div>
    </div>
  )
}

function isDraftStep(step: SkillWizardStep) {
  return (
    step === 'basic' ||
    step === 'workflow' ||
    step === 'references' ||
    step === 'review' ||
    step === 'raw'
  )
}

function nextSkillStep(step: SkillWizardStep): SkillWizardStep {
  if (step === 'basic') return 'workflow'
  if (step === 'workflow') return 'references'
  if (step === 'references') return 'review'
  return step
}

function previousSkillStep(step: SkillWizardStep, source: 'ai' | 'url' | null): SkillWizardStep {
  if (step === 'basic') return source === 'url' ? 'urlInput' : 'aiInput'
  if (step === 'workflow') return 'basic'
  if (step === 'references') return 'workflow'
  if (step === 'review') return 'references'
  if (step === 'raw') return 'review'
  return 'entry'
}

type SkillWizardStep =
  | 'entry'
  | 'aiInput'
  | 'urlInput'
  | 'generating'
  | 'basic'
  | 'workflow'
  | 'references'
  | 'review'
  | 'raw'

type SkillReferenceDraft = {
  id: string
  title: string
  content: string
}

type SkillDraftForm = {
  key: string
  displayName: string
  description: string
  useCases: string
  steps: string
  outputFormat: string
  cautions: string
  references: SkillReferenceDraft[]
  rawBody: string
  rawEdited: boolean
}

function skillDraftToForm(draft: CustomSkillDraft): SkillDraftForm {
  const body = draft.body || ''
  return {
    key: draft.name,
    displayName: draft.displayName || draft.name,
    description: draft.description || '',
    useCases:
      extractMarkdownSection(body, ['사용 기준', '사용하는 상황', 'When to use']) ||
      draft.description ||
      '',
    steps:
      extractMarkdownSection(body, ['작업 순서', '작업 방식', 'Workflow']) ||
      stripSkillFrontmatter(body),
    outputFormat: extractMarkdownSection(body, ['결과 형식', '결과물', 'Output']) || '',
    cautions: extractMarkdownSection(body, ['주의할 점', '제한', '확인 기준']) || '',
    references: (draft.documents ?? [])
      .filter((document) => document.documentKey !== 'SKILL.md')
      .map((document) => ({
        id: newReferenceId(),
        title: document.title || document.documentKey,
        content: document.content || '',
      })),
    rawBody: body,
    rawEdited: false,
  }
}

function buildSkillBody(draft: SkillDraftForm) {
  return `---
name: ${normalizeCustomSkillName(draft.key || draft.displayName)}
description: ${draft.description.trim()}
---

# ${draft.displayName.trim() || '사용자 스킬'}

## 사용 기준

${draft.useCases.trim() || '- 사용자의 요청이 이 스킬의 목적과 직접 맞을 때 사용한다.'}

## 작업 순서

${draft.steps.trim() || '1. 요청의 목표를 확인한다.\n2. 필요한 정보를 정리한다.\n3. 결과를 검토하기 쉽게 답한다.'}

## 결과 형식

${draft.outputFormat.trim() || '- 사용자가 바로 확인할 수 있게 간단히 정리한다.'}

## 주의할 점

${draft.cautions.trim() || '- 확인되지 않은 내용은 추측하지 않는다.'}
`
}

function updateReference(
  references: SkillReferenceDraft[],
  id: string,
  patch: Partial<SkillReferenceDraft>,
) {
  return references.map((reference) =>
    reference.id === id ? { ...reference, ...patch } : reference,
  )
}

function referenceDocumentKey(reference: SkillReferenceDraft, index: number) {
  const slug = normalizeCustomSkillName(reference.title || `reference-${index + 1}`)
  return `references/${slug || `reference-${index + 1}`}.md`
}

function newReferenceId() {
  return `reference-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function extractMarkdownSection(markdown: string, headings: string[]) {
  const normalized = stripSkillFrontmatter(markdown)
  for (const heading of headings) {
    const pattern = new RegExp(
      `^##\\s+${escapeRegExp(heading)}\\s*$([\\s\\S]*?)(?=^##\\s+|$)`,
      'im',
    )
    const match = normalized.match(pattern)
    if (match?.[1]?.trim()) return match[1].trim()
  }
  return ''
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function stripSkillFrontmatter(markdown: string) {
  const normalized = markdown.replace(/\r\n/g, '\n')
  if (!normalized.startsWith('---\n')) return normalized.trim()
  const closing = normalized.indexOf('\n---\n', 4)
  if (closing < 0) return normalized.trim()
  return normalized.slice(closing + 5).trim()
}
export function AgentAdapterTypeDropdown({
  options,
  value,
  onChange,
}: {
  options: AgentSelectOption[]
  value: string
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="border-border hover:bg-accent/50 inline-flex w-full items-center justify-between gap-1.5 rounded-md border px-2.5 py-1.5 text-sm transition-colors"
        >
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <span className="truncate">{selected?.label ?? value}</span>
            {selected?.badge ? (
              <span className="shrink-0 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] leading-none font-medium text-amber-700 dark:text-amber-300">
                {selected.badge}
              </span>
            ) : null}
          </span>
          <ChevronDown className="text-muted-foreground h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-1" align="start">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={option.disabled}
            className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-sm ${
              option.disabled
                ? 'cursor-not-allowed opacity-40'
                : option.value === value
                  ? 'bg-accent'
                  : 'hover:bg-accent/50'
            }`}
            onClick={() => {
              if (!option.disabled) {
                onChange(option.value)
                setOpen(false)
              }
            }}
          >
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span className="truncate">{option.label}</span>
              {option.badge ? (
                <span className="shrink-0 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] leading-none font-medium text-amber-700 dark:text-amber-300">
                  {option.badge}
                </span>
              ) : null}
            </span>
            {option.disabled ? (
              <span className="text-muted-foreground text-[10px]">준비 중</span>
            ) : option.value === value ? (
              <Check className="h-3.5 w-3.5" />
            ) : null}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  )
}

export function AgentModelDropdown({
  allowDefault = true,
  options,
  placeholder = 'Select model',
  value,
  onChange,
}: {
  allowDefault?: boolean
  options: AgentSelectOption[]
  placeholder?: string
  value: string
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="border-border hover:bg-accent/50 inline-flex w-full items-center justify-between gap-1.5 rounded-md border px-2.5 py-1.5 text-sm transition-colors"
        >
          <span className={!value ? 'text-muted-foreground' : undefined}>
            {(selected?.label ?? value) || (allowDefault ? 'Default' : placeholder)}
          </span>
          <ChevronDown className="text-muted-foreground h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-1" align="start">
        <div className="max-h-[240px] overflow-y-auto">
          {allowDefault ? (
            <button
              type="button"
              className={`hover:bg-accent/50 flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                !value ? 'bg-accent' : ''
              }`}
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              Default
            </button>
          ) : null}
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`hover:bg-accent/50 flex w-full items-center rounded px-2 py-1.5 text-sm ${
                option.value === value ? 'bg-accent' : ''
              }`}
              onClick={() => {
                onChange(option.value)
                setOpen(false)
              }}
            >
              <span className="block w-full truncate text-left" title={option.value}>
                {option.label}
              </span>
              {option.value === value ? <Check className="h-3.5 w-3.5" /> : null}
            </button>
          ))}
          {options.length === 0 ? (
            <p className="text-muted-foreground px-2 py-2 text-xs">No models found.</p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export function AgentSummaryGrid({
  columns = 'two',
  items,
}: {
  columns?: 'two' | 'three' | 'four'
  items: AgentSummaryItemData[]
}) {
  return (
    <div
      className={`grid gap-3 text-sm ${
        columns === 'four'
          ? 'sm:grid-cols-2 md:grid-cols-4'
          : columns === 'three'
            ? 'sm:grid-cols-3'
            : 'sm:grid-cols-2'
      }`}
    >
      {items.map((item) => (
        <AgentSummaryItem key={item.label} label={item.label} value={item.value} />
      ))}
    </div>
  )
}

export function AgentSummaryItem({ label, value }: AgentSummaryItemData) {
  return (
    <div className="min-w-0">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-1 min-w-0 text-sm break-words">{value}</div>
    </div>
  )
}

function AgentRecentSummaryItem({ label, onSelect, value }: AgentSummaryItemData) {
  const content = (
    <>
      <div className="min-w-0 truncate text-sm font-medium" title={label}>
        {label}
      </div>
      <div className="text-muted-foreground min-w-0 truncate text-xs sm:text-right">{value}</div>
    </>
  )

  if (onSelect) {
    return (
      <button
        type="button"
        className="hover:bg-muted/50 grid w-full min-w-0 gap-1 py-3 text-left transition-colors sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-3"
        onClick={onSelect}
      >
        {content}
      </button>
    )
  }

  return (
    <div className="grid min-w-0 gap-1 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-3">
      {content}
    </div>
  )
}

const CHART_COLORS = ['#06b6d4', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#64748b']
const DAY_MS = 24 * 60 * 60 * 1000

export function AgentRunActivityChart({ runs }: { runs: AgentRunItemData[] }) {
  const activity = buildRunActivityData(runs)
  return <AgentStackedDayChart activity={activity} emptyLabel="실행 기록 없음" />
}

export function AgentRunStatusChart({ runs }: { runs: AgentRunItemData[] }) {
  const activity = buildRunActivityData(runs)
  return (
    <AgentStackedDayChart
      activity={activity}
      emptyLabel="상태 기록 없음"
      legend={[
        { color: CHART_COLORS[1], label: '완료' },
        { color: CHART_COLORS[3], label: '실패' },
        { color: CHART_COLORS[5], label: '기타' },
      ]}
    />
  )
}

export function AgentRunSuccessRateChart({ runs }: { runs: AgentRunItemData[] }) {
  const activity = buildRunActivityData(runs)
  const hasData = activity.some((day) => day.total > 0)
  if (!hasData) return <p className="text-muted-foreground text-xs">실행 기록 없음</p>

  return (
    <div>
      <div className="flex h-20 items-end gap-[3px]">
        {activity.map((day) => {
          const rate = day.total > 0 ? day.succeeded / day.total : 0
          const color =
            day.total === 0
              ? undefined
              : rate >= 0.8
                ? CHART_COLORS[1]
                : rate >= 0.5
                  ? CHART_COLORS[2]
                  : CHART_COLORS[3]
          return (
            <div
              key={day.date}
              className="flex h-full flex-1 flex-col justify-end"
              title={`${day.label}: ${day.total > 0 ? Math.round(rate * 100) : 0}%`}
            >
              {day.total > 0 ? (
                <div style={{ height: `${rate * 100}%`, minHeight: 2, backgroundColor: color }} />
              ) : (
                <div className="bg-muted/30 rounded-sm" style={{ height: 2 }} />
              )}
            </div>
          )
        })}
      </div>
      <AgentDateLabels days={activity} />
    </div>
  )
}

export function AgentUsageActivityChart({ records }: { records: AgentUsageMetricRecord[] }) {
  const data = buildLast14DayUsageData(records)
  const maxValue = Math.max(...data.map((day) => day.tokens), 1)
  const hasData = data.some((day) => day.tokens > 0)

  if (!hasData) return <p className="text-muted-foreground text-xs">사용량 기록 없음</p>
  return (
    <div>
      <div className="flex h-20 items-end gap-[3px]">
        {data.map((day) => {
          const heightPct = (day.tokens / maxValue) * 100
          return (
            <div
              key={day.date}
              className="flex h-full flex-1 flex-col justify-end"
              title={`${day.label}: ${day.tokens.toLocaleString('ko-KR')} tokens`}
            >
              {day.tokens > 0 ? (
                <div className="bg-violet-500" style={{ height: `${heightPct}%`, minHeight: 2 }} />
              ) : (
                <div className="bg-muted/30 rounded-sm" style={{ height: 2 }} />
              )}
            </div>
          )
        })}
      </div>
      <AgentDateLabels days={data} />
    </div>
  )
}

function AgentStackedDayChart({
  activity,
  emptyLabel,
  legend,
}: {
  activity: AgentRunActivityDay[]
  emptyLabel: string
  legend?: Array<{ color: string; label: string }>
}) {
  const maxValue = Math.max(...activity.map((day) => day.total), 1)
  const hasData = activity.some((day) => day.total > 0)

  if (!hasData) return <p className="text-muted-foreground text-xs">{emptyLabel}</p>

  return (
    <div>
      <div className="flex h-20 items-end gap-[3px]">
        {activity.map((day) => {
          const heightPct = (day.total / maxValue) * 100
          return (
            <div
              key={day.date}
              className="flex h-full flex-1 flex-col justify-end"
              title={`${day.label}: ${day.total}회`}
            >
              {day.total > 0 ? (
                <div
                  className="flex flex-col-reverse gap-px overflow-hidden"
                  style={{ height: `${heightPct}%`, minHeight: 2 }}
                >
                  {day.succeeded > 0 ? (
                    <div className="bg-emerald-500" style={{ flex: day.succeeded }} />
                  ) : null}
                  {day.failed > 0 ? (
                    <div className="bg-red-500" style={{ flex: day.failed }} />
                  ) : null}
                  {day.other > 0 ? (
                    <div className="bg-neutral-500" style={{ flex: day.other }} />
                  ) : null}
                </div>
              ) : (
                <div className="bg-muted/30 rounded-sm" style={{ height: 2 }} />
              )}
            </div>
          )
        })}
      </div>
      <AgentDateLabels days={activity} />
      {legend ? <AgentChartLegend items={legend} /> : null}
    </div>
  )
}

function AgentDateLabels({ days }: { days: Array<{ date: string; label: string }> }) {
  return (
    <div className="mt-1.5 flex gap-[3px]">
      {days.map((day, index) => (
        <div key={day.date} className="flex-1 text-center">
          {index === 0 || index === 6 || index === 13 ? (
            <span className="text-muted-foreground text-[9px] tabular-nums">{day.label}</span>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function AgentChartLegend({ items }: { items: Array<{ color: string; label: string }> }) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-2.5 gap-y-0.5">
      {items.map((item) => (
        <span key={item.label} className="text-muted-foreground flex items-center gap-1 text-[9px]">
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: item.color }}
          />
          {item.label}
        </span>
      ))}
    </div>
  )
}

interface AgentRunActivityDay {
  date: string
  label: string
  succeeded: number
  failed: number
  other: number
  total: number
}

function buildRunActivityData(runs: AgentRunItemData[]): AgentRunActivityDay[] {
  const days = buildLast14Days()
  const grouped = new Map(
    days.map((day) => [
      day.key,
      { date: day.key, label: day.label, succeeded: 0, failed: 0, other: 0, total: 0 },
    ]),
  )
  for (const run of runs) {
    const key = getDayKey(run.sortTime)
    const entry = key !== null ? grouped.get(key) : undefined
    if (!entry) continue
    if (isSuccessStatus(run.status)) entry.succeeded += 1
    else if (isFailureStatus(run.status)) entry.failed += 1
    else entry.other += 1
    entry.total += 1
  }
  return [...grouped.values()]
}

function buildLast14DayUsageData(records: AgentUsageMetricRecord[]) {
  const days = buildLast14Days()
  const grouped = new Map(
    days.map((day) => [day.key, { date: day.key, label: day.label, tokens: 0 }]),
  )
  for (const record of records) {
    const time = record.createdAt ? parseServerTimestamp(record.createdAt) : null
    const key = time !== null ? getDayKey(time) : null
    const entry = key !== null ? grouped.get(key) : undefined
    if (entry) {
      entry.tokens += Math.max(0, record.totalTokens ?? 0)
    }
  }
  return [...grouped.values()]
}

function buildLast14Days() {
  // 한국 시간(KST) 기준으로 오늘 자정을 구하고, 그 자정에서 14일을 거꾸로 나열
  const todayKstMidnight = getKstMidnightTime(Date.now())
  return Array.from({ length: 14 }, (_, index) => {
    const time = todayKstMidnight - (13 - index) * DAY_MS
    const { year, month, day } = getKstYearMonthDay(time)
    return {
      key: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      label: `${month}/${day}`,
    }
  })
}

function getDayKey(time: number | undefined) {
  if (time === undefined || !Number.isFinite(time) || time <= 0) return null
  const { year, month, day } = getKstYearMonthDay(time)
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// 임의의 시각(time, ms epoch)을 한국 시간(KST, UTC+9)으로 해석해 연/월/일을 반환한다.
const KST_DATE_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function getKstYearMonthDay(time: number): { year: number; month: number; day: number } {
  // en-CA는 YYYY-MM-DD 형식으로 출력 → 안전하게 parsing
  const parts = KST_DATE_FORMATTER.formatToParts(new Date(time))
  let year = 0
  let month = 0
  let day = 0
  for (const part of parts) {
    if (part.type === 'year') year = Number(part.value)
    else if (part.type === 'month') month = Number(part.value)
    else if (part.type === 'day') day = Number(part.value)
  }
  return { year, month, day }
}

// 임의의 시각이 속한 KST 날짜의 자정(KST 00:00)을 UTC ms epoch로 돌려준다.
function getKstMidnightTime(time: number): number {
  const { year, month, day } = getKstYearMonthDay(time)
  // KST는 UTC+9 — 해당 날짜의 00:00 KST는 UTC 기준 전날 15:00
  return Date.UTC(year, month - 1, day) - 9 * 60 * 60 * 1000
}

function isSuccessStatus(status?: string | null) {
  return (
    status === 'succeeded' ||
    status === 'completed' ||
    status === 'SUCCEEDED' ||
    status === 'COMPLETED'
  )
}

function isFailureStatus(status?: string | null) {
  return (
    status === 'failed' ||
    status === 'blocked' ||
    status === 'cancelled' ||
    status === 'canceled' ||
    status === 'FAILED' ||
    status === 'BLOCKED' ||
    status === 'CANCELLED' ||
    status === 'CANCELED'
  )
}

function AgentMetricCard({ metric }: { metric: AgentMetricItem }) {
  const Icon = metric.icon

  if (metric.chart) {
    return (
      <div className="border-border space-y-3 rounded-lg border p-4">
        <div>
          <h3 className="text-muted-foreground text-xs font-medium">{metric.label}</h3>
          {metric.description ? (
            <span className="text-muted-foreground/60 text-[10px]">{metric.description}</span>
          ) : null}
        </div>
        {metric.chart}
      </div>
    )
  }

  return (
    <div className="border-border min-h-28 rounded-lg border p-4">
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
        {metric.label}
      </div>
      <div className="mt-3 text-lg font-semibold tabular-nums">{metric.value}</div>
      {metric.description ? (
        <div className="text-muted-foreground mt-1 text-xs leading-5">{metric.description}</div>
      ) : null}
    </div>
  )
}

function AgentRunSummaryCard({ onSelect, run }: { onSelect?: () => void; run: AgentRunItemData }) {
  const summary = getRunSummaryExcerpt(run.summary)
  const content = (
    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <AgentStatusPill status={run.status} />
          <span className="text-muted-foreground font-mono text-xs">{shortRunId(run.id)}</span>
          {run.source ? (
            <span className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[10px] font-medium">
              {run.source}
            </span>
          ) : null}
        </div>
        {summary ? (
          <p className="text-muted-foreground max-h-16 overflow-hidden text-sm leading-5">
            {summary}
          </p>
        ) : (
          <p className="text-muted-foreground text-sm">아직 요약이 없습니다.</p>
        )}
      </div>
      <span className="text-muted-foreground shrink-0 text-xs">{run.createdAt ?? '방금 전'}</span>
    </div>
  )

  return (
    <button
      type="button"
      className={`border-border block w-full overflow-hidden rounded-lg border text-left transition-colors ${
        onSelect ? 'hover:bg-muted/50 cursor-pointer' : 'cursor-default'
      } ${isLiveRunStatus(run.status) ? 'border-cyan-500/30 shadow-[0_0_12px_rgba(6,182,212,0.08)]' : ''}`}
      onClick={onSelect}
      disabled={!onSelect}
    >
      {content}
    </button>
  )
}

function isLiveRunStatus(status?: string | null) {
  return status === 'running' || status === 'waiting' || status === 'queued' || status === 'RUNNING'
}

function getRunSummaryExcerpt(summary: string | undefined) {
  if (!summary) return ''
  const lines = summary
    .replace(/^#{1,6}\s+/gm, '')
    .split('\n')
    .map((line) => line.trim())
    .filter(
      (line) =>
        line.length > 0 &&
        !line.startsWith('---') &&
        !line.startsWith('|') &&
        !line.startsWith('```') &&
        !/^[-*>]/.test(line) &&
        !/^\d+\./.test(line),
    )
  const excerpt: string[] = []
  let chars = 0
  for (const line of lines) {
    if (excerpt.length >= 3 || chars + line.length > 280) break
    excerpt.push(line)
    chars += line.length
  }
  return excerpt.join(' ')
}

function AgentSkillTransferColumn({
  countLabel,
  emptyLabel,
  id,
  onSkillOpen,
  rows,
  selectedKey,
  title,
}: {
  countLabel: string
  emptyLabel: string
  id: SkillTransferDropId
  onSkillOpen: (key: string) => void
  rows: AgentSkillRowData[]
  selectedKey: string | null
  title: string
}) {
  const { isOver, setNodeRef } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      data-skill-drop-id={id}
      className={`border-border min-h-64 overflow-hidden rounded-lg border ${
        isOver ? 'ring-primary/30 ring-2' : ''
      }`}
    >
      <div className="border-border bg-muted/30 flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-muted-foreground font-mono text-xs">{countLabel}</span>
      </div>
      {rows.length === 0 ? (
        <div className="text-muted-foreground px-3 py-8 text-center text-sm">{emptyLabel}</div>
      ) : (
        <div className="divide-border divide-y">
          {rows.map((row) => (
            <AgentSkillTransferItem
              key={row.key}
              row={row}
              selected={selectedKey === row.key}
              onSkillOpen={onSkillOpen}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function AgentSavingIndicator({ label }: { label: string }) {
  return (
    <div className="text-muted-foreground flex items-center justify-end gap-2 text-xs">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      <span>{label}</span>
    </div>
  )
}

function AgentSkillTransferItem({
  onSkillOpen,
  row,
  selected,
}: {
  onSkillOpen: (key: string) => void
  row: AgentSkillRowData
  selected: boolean
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: row.key,
    disabled: row.disabled,
  })
  const { isOver, setNodeRef: setDropNodeRef } = useDroppable({
    id: getSkillRowDropId(row.key),
    disabled: row.disabled,
  })
  const setCombinedNodeRef = (node: HTMLDivElement | null) => {
    setNodeRef(node)
    setDropNodeRef(node)
  }
  const style = isDragging ? undefined : { transform: CSS.Transform.toString(transform) }

  return (
    <div
      ref={setCombinedNodeRef}
      data-skill-id={row.key}
      style={style}
      className={`hover:bg-accent/40 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 px-2 py-2 text-sm transition-colors ${
        selected || isOver ? 'bg-accent/50' : ''
      } ${row.disabled ? 'text-muted-foreground opacity-60' : ''} ${isDragging ? 'z-10 opacity-70' : ''}`}
      title={typeof row.description === 'string' ? row.description : undefined}
    >
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground cursor-grab rounded p-1 disabled:cursor-not-allowed"
        aria-label={`${row.name} 드래그`}
        disabled={row.disabled}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <button
        type="button"
        className="min-w-0 truncate text-left font-medium"
        onClick={() => onSkillOpen(row.key)}
      >
        {row.name}
      </button>
    </div>
  )
}

function AgentSkillDragOverlayCard({ row }: { row: AgentSkillRowData }) {
  return (
    <div className="border-border bg-background grid w-[min(26rem,calc(100vw-3rem))] grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-lg border px-2 py-2 text-sm shadow-2xl">
      <span className="text-muted-foreground rounded p-1">
        <GripVertical className="h-4 w-4" />
      </span>
      <span className="min-w-0 truncate font-medium">{row.name}</span>
    </div>
  )
}

type SkillTransferSide = 'enabled' | 'disabled'
type SkillTransferDropId = 'enabled-skills' | 'disabled-skills'
type SkillTransferTarget = { side: SkillTransferSide; key: string | null }

function getSkillTransferTarget(
  id: unknown,
  rows: AgentSkillRowData[],
): SkillTransferTarget | null {
  if (id === 'enabled-skills') return { side: 'enabled', key: null }
  if (id === 'disabled-skills') return { side: 'disabled', key: null }
  if (typeof id !== 'string' || !id.startsWith(SKILL_ROW_DROP_PREFIX)) return null
  const key = id.slice(SKILL_ROW_DROP_PREFIX.length)
  const row = rows.find((item) => item.key === key)
  if (row === undefined) return null
  return { side: row.checked ? 'enabled' : 'disabled', key }
}

function getSkillInsertIndex(event: DragEndEvent, enabledKeys: string[], overKey: string | null) {
  if (overKey === null) return enabledKeys.length
  const overIndex = enabledKeys.indexOf(overKey)
  if (overIndex === -1) return enabledKeys.length
  const activeRect = event.active.rect.current.translated ?? event.active.rect.current.initial
  if (activeRect === null || event.over === null) return overIndex
  const activeCenterY = activeRect.top + activeRect.height / 2
  const overCenterY = event.over.rect.top + event.over.rect.height / 2
  return overIndex + (activeCenterY > overCenterY ? 1 : 0)
}

function insertSkillKey(keys: string[], key: string, insertIndex: number) {
  const nextKeys = keys.filter((item) => item !== key)
  nextKeys.splice(Math.max(0, Math.min(insertIndex, nextKeys.length)), 0, key)
  return nextKeys
}

function normalizeSkillSearch(value: string) {
  return value.trim().toLowerCase()
}

function normalizeCustomSkillName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/_/g, '-')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
}

function filterSkillRows(rows: AgentSkillRowData[], normalizedSearch: string) {
  if (!normalizedSearch) return rows
  return rows.filter((row) => {
    const values = [
      row.key,
      row.name,
      typeof row.description === 'string' ? row.description : '',
      row.locationLabel ?? '',
    ]
    return values.some((value) => value.toLowerCase().includes(normalizedSearch))
  })
}

function formatSkillColumnCount(visibleCount: number, totalCount: number) {
  return visibleCount === totalCount ? String(totalCount) : `${visibleCount}/${totalCount}`
}

function stringArraysEqual(first: string[], second: string[]) {
  if (first.length !== second.length) return false
  return first.every((item, index) => item === second[index])
}

const SKILL_ROW_DROP_PREFIX = 'skill-row:'

function getSkillRowDropId(key: string) {
  return `${SKILL_ROW_DROP_PREFIX}${key}`
}

function AgentSkillTransferReadonlyGroup({
  rows,
  selectedKey,
  title,
  onSkillOpen,
}: {
  rows: AgentSkillRowData[]
  selectedKey: string | null
  title: string
  onSkillOpen: (key: string) => void
}) {
  return (
    <section className="border-border border-y">
      <div className="border-border bg-muted/40 border-b px-3 py-2">
        <span className="text-muted-foreground text-xs font-medium">{title}</span>
      </div>
      {rows.map((row) => (
        <AgentSkillTransferReadonlyItem
          key={row.key}
          row={row}
          selected={selectedKey === row.key}
          onSkillOpen={onSkillOpen}
        />
      ))}
    </section>
  )
}

function AgentSkillTransferReadonlyItem({
  onSkillOpen,
  row,
  selected,
}: {
  onSkillOpen: (key: string) => void
  row: AgentSkillRowData
  selected: boolean
}) {
  return (
    <button
      type="button"
      className={`hover:bg-accent/40 flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm transition-colors ${
        selected ? 'bg-accent/50' : ''
      } ${row.disabled ? 'text-muted-foreground opacity-60' : ''}`}
      onClick={() => onSkillOpen(row.key)}
      title={typeof row.description === 'string' ? row.description : undefined}
    >
      <span className="min-w-0 truncate font-medium">{row.name}</span>
    </button>
  )
}

function AgentInlineSummary({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="border-border/60 flex items-center justify-between gap-3 border-b py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

function getRunStatusView(status: string) {
  const normalized = normalizeRunStatusValue(status)
  switch (normalized) {
    case 'failed':
      return {
        label: '오류',
        dotClassName: 'bg-red-500',
        pillClassName: 'border-red-200 bg-red-50 text-red-700',
      }
    case 'running':
      return {
        label: '실행 중',
        dotClassName: 'bg-blue-500',
        pillClassName: 'border-blue-200 bg-blue-50 text-blue-700',
      }
    case 'waiting':
      return {
        label: '대기 중',
        dotClassName: 'bg-amber-500',
        pillClassName: 'border-amber-200 bg-amber-50 text-amber-700',
      }
    case 'succeeded':
      return {
        label: '완료',
        dotClassName: 'bg-emerald-500',
        pillClassName: 'border-emerald-200 bg-emerald-50 text-emerald-700',
      }
    default:
      return {
        label: '준비 중',
        dotClassName: 'bg-muted-foreground/50',
        pillClassName: 'border-border bg-muted text-muted-foreground',
      }
  }
}

function normalizeRunStatusValue(status: string) {
  switch (status) {
    case 'failed':
    case 'FAILED':
    case 'blocked':
    case 'BLOCKED':
    case 'cancelled':
    case 'CANCELLED':
    case 'canceled':
    case 'CANCELED':
      return 'failed'
    case 'running':
    case 'RUNNING':
      return 'running'
    case 'waiting':
    case 'WAITING':
      return 'waiting'
    case 'succeeded':
    case 'completed':
    case 'COMPLETED':
      return 'succeeded'
    case 'pending':
    case 'PENDING':
      return 'pending'
    default:
      return 'pending'
  }
}

function AgentStatusPill({ status }: { status: string }) {
  const statusView = getRunStatusView(status)
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase ${statusView.pillClassName}`}
    >
      {statusView.label}
    </span>
  )
}

function shortRunId(id: string) {
  return id.length > 8 ? id.slice(0, 8) : id
}

function statusLabel(status: AgentBudgetSummaryData['status']) {
  if (status === 'hard_stop') return '사용 중지'
  if (status === 'warning') return '주의'
  return '정상'
}

function normalizeInstructionPath(value: string) {
  return value.trim().replaceAll('\\', '/').replace(/^\/+/, '')
}

function parseBudgetInput(value: string) {
  const normalized = value.trim()
  if (normalized === '') return 0
  const parsed = Number(normalized)
  if (!Number.isFinite(parsed) || parsed < 0) return null
  return parsed
}
