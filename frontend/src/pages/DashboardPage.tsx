import { useEffect, useState, useCallback } from 'react'
import {
  Server,
  Wifi,
  Bot,
  Eye,
  Plus,
  Loader2,
  KeyRound,
  Activity,
  ChevronDown,
  ChevronRight,
  Heart,
  Moon,
  Footprints,
  Sparkles,
  Monitor,
  HelpCircle,
  RefreshCw,
} from 'lucide-react'
import { motion } from 'motion/react'
import { useNavigate } from 'react-router'
import { useUIStore } from '@/store/useUIStore'
import { getIotDevices, deleteIotDevice, pairIotDevice, type IotDevice } from '@/apis/iot'
import { listBridgeDevices } from '@/apis/bridge'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { HelpHint } from '@/components/ui/help-hint'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { NewSessionModal, type CustomAgentConfig } from '@/components/session/NewSessionModal'
import { getLatestHealthData, type HealthSummaryData } from '@/apis/health'

// ── Mock 상태 (서버·에이전트) ─────────────────────────────────────────────────
type ServerStatus = 'ok' | 'error'
type AgentStatus = 'idle' | 'working'

const MOCK_SERVER: ServerStatus = 'ok'
const MOCK_AGENT: AgentStatus = 'idle'

// ── StatusDot ────────────────────────────────────────────────────────────────
interface StatusDotProps {
  color: 'emerald' | 'red' | 'amber' | 'muted' | 'blue'
  pulse?: boolean
}

function StatusDot({ color, pulse }: StatusDotProps) {
  const colorClass = {
    emerald: 'bg-emerald-500',
    red: 'bg-red-500',
    amber: 'bg-amber-400',
    muted: 'bg-muted-foreground/50',
    blue: 'bg-blue-500',
  }[color]

  return (
    <span className="relative flex h-2 w-2 shrink-0 items-center justify-center">
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${colorClass}`}
        />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${colorClass}`} />
    </span>
  )
}

// ── StatusCard ───────────────────────────────────────────────────────────────
interface StatusCardProps {
  icon: React.ReactNode
  title: string
  statusLabel: string
  dotColor: StatusDotProps['color']
  pulse?: boolean
}

function StatusCard({ icon, title, statusLabel, dotColor, pulse }: StatusCardProps) {
  return (
    <div className="border-border bg-card flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-center gap-2">
        <div className="text-muted-foreground bg-muted/60 flex h-8 w-8 items-center justify-center rounded-lg">
          {icon}
        </div>
        <p className="text-muted-foreground text-xs">{title}</p>
      </div>
      <div className="flex items-center gap-1.5">
        <StatusDot color={dotColor} pulse={pulse} />
        <span className="text-foreground text-sm font-medium">{statusLabel}</span>
      </div>
    </div>
  )
}

// ── IotCard ──────────────────────────────────────────────────────────────────
function formatLastSeen(lastSeenAt: string | null): string {
  if (!lastSeenAt) return '-'
  return new Date(lastSeenAt).toLocaleString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface IotCardProps {
  loading: boolean
  device: IotDevice | null
  onRegister: () => void
  onDeregister: (deviceId: string) => void
}

function IotCard({ loading, device, onRegister, onDeregister }: IotCardProps) {
  const isActive = device?.status === 'ACTIVE'

  return (
    <div className="border-border bg-card rounded-xl border p-4">
      <div className="mb-3 flex items-center gap-2">
        <div className="text-muted-foreground bg-muted/60 flex h-8 w-8 items-center justify-center rounded-lg">
          <Wifi className="h-4 w-4" />
        </div>
        <p className="text-muted-foreground inline-flex items-center gap-1 text-xs">
          IoT 연결
          <HelpHint label="IoT 연결 도움말" iconClassName="h-3 w-3">
            <p className="text-foreground font-medium">IoT 연결</p>
            <p>
              HeyGent 전용 <span className="text-foreground">기기</span>를 내 계정에 등록하는
              단계예요.
            </p>
            <p>스마트폰에 무선 이어폰을 처음 연결하는 과정과 비슷합니다.</p>
          </HelpHint>
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-1">
          <Loader2 className="text-muted-foreground h-3.5 w-3.5 animate-spin" />
          <span className="text-muted-foreground text-xs">기기 정보를 불러오는 중...</span>
        </div>
      )}

      {!loading && !device && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-muted-foreground text-sm">등록된 디바이스가 없습니다.</span>
          <button
            type="button"
            onClick={onRegister}
            className="border-border text-foreground hover:bg-accent/50 shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors"
          >
            기기 등록하기
          </button>
        </div>
      )}

      {!loading && device && (
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-0.5">
              <p className="text-foreground truncate text-sm font-medium">
                {device.displayName ?? '(이름 없음)'}
              </p>
              <p className="text-muted-foreground truncate font-mono text-xs">{device.deviceId}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
              <StatusDot color={isActive ? 'emerald' : 'amber'} />
              <span className="text-foreground text-xs font-medium">
                {isActive ? '연결됨' : '비활성'}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="text-muted-foreground shrink-0 text-xs">마지막 접속</span>
              <span className="text-foreground truncate text-xs">
                {formatLastSeen(device.lastSeenAt)}
              </span>
            </div>
            <button
              type="button"
              onClick={() => onDeregister(device.deviceId)}
              className="shrink-0 text-xs font-medium text-red-500 transition-colors hover:text-red-600"
            >
              등록 해제
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

type BridgeStatus = 'loading' | 'installed' | 'not_installed' | 'error'

function BridgeCard() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<BridgeStatus>('loading')

  const [refreshNonce, setRefreshNonce] = useState(0)

  const refresh = useCallback(() => {
    setStatus('loading')
    setRefreshNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    listBridgeDevices()
      .then((devices) => {
        if (cancelled) return
        // revokedAt이 truthy(실제 해제 ISO 문자열)일 때만 제외 — null/undefined/"" 등은 정상으로 본다
        const active = devices.filter((device) => !device.revokedAt)
        setStatus(active.length > 0 ? 'installed' : 'not_installed')
      })
      .catch(() => {
        if (cancelled) return
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [refreshNonce])

  const dotColor: StatusDotProps['color'] =
    status === 'installed' ? 'emerald' : status === 'loading' ? 'muted' : 'amber'
  const statusLabel =
    status === 'loading'
      ? '확인 중...'
      : status === 'installed'
        ? '연결됨'
        : status === 'error'
          ? '확인 실패'
          : '연결되지 않음'

  return (
    <div className="border-border bg-card flex flex-col justify-between gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="text-muted-foreground bg-muted/60 flex h-8 w-8 items-center justify-center rounded-lg">
            <Monitor className="h-4 w-4" />
          </div>
          <div className="flex min-w-0 items-center gap-1.5">
            <p className="text-muted-foreground truncate text-xs">브릿지 프로그램</p>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground rounded-full transition-colors"
                  aria-label="브릿지 프로그램 도움말"
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 text-sm" align="end">
                <div className="space-y-2">
                  <p className="text-foreground font-medium">브릿지 프로그램이란?</p>
                  <p className="text-muted-foreground leading-relaxed">
                    HeyGent와 로컬 PC 또는 IoT 기기를 연결하는 작은 실행 프로그램입니다. 기기 등록,
                    로컬 명령 실행, 상태 전달처럼 브라우저만으로 처리하기 어려운 연결 작업을
                    중계합니다.
                  </p>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1 pt-2">
          <StatusDot color={dotColor} />
          <span className="text-foreground text-xs font-medium">{statusLabel}</span>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={status === 'loading'}
            aria-label="브릿지 연결 상태 새로고침"
            title="새로고침"
            className="text-muted-foreground hover:bg-accent/50 hover:text-foreground ml-0.5 flex h-5 w-5 items-center justify-center rounded transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${status === 'loading' ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="space-y-3">
        <p className="text-muted-foreground text-xs leading-relaxed">
          {status === 'installed'
            ? '내 PC와 브릿지가 연결되어 있어요. 브릿지 설정에서 상세 관리를 할 수 있습니다.'
            : status === 'error'
              ? '연결 상태를 가져오지 못했어요. 새로고침을 눌러 다시 시도해 주세요.'
              : '브릿지가 연결되지 않았어요. 브릿지 설정에서 설치 여부를 확인하고 페어링을 진행해 주세요.'}
        </p>
        <button
          type="button"
          onClick={() => navigate('/settings/bridge')}
          className="border-border text-foreground hover:bg-accent/50 inline-flex h-6 w-auto items-center gap-1 self-start rounded-md border px-2 text-[11px] font-medium transition-colors"
        >
          <Monitor className="h-3 w-3" />
          브릿지 설정
          <ChevronRight className="text-muted-foreground h-3 w-3" />
        </button>
      </div>
    </div>
  )
}

// ── DeregisterConfirmModal ────────────────────────────────────────────────────
interface DeregisterConfirmModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => Promise<void>
}

function DeregisterConfirmModal({ open, onOpenChange, onConfirm }: DeregisterConfirmModalProps) {
  const [loading, setLoading] = useState(false)

  const handleConfirm = async () => {
    setLoading(true)
    try {
      await onConfirm()
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm gap-5">
        <div>
          <DialogTitle className="text-base">기기 등록을 해제할까요?</DialogTitle>
          <DialogDescription className="text-muted-foreground mt-2 text-sm leading-relaxed">
            등록 해제하면 현재 계정과 디바이스의 연결이 끊어집니다.
            <br />
            다시 사용하려면 페어링 코드를 입력해 재등록해야 합니다.
          </DialogDescription>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleConfirm}
            disabled={loading}
            className="flex-1 rounded-xl bg-red-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          >
            {loading ? '해제 중...' : '등록 해제'}
          </button>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            className="border-border text-foreground hover:bg-accent/50 flex-1 rounded-xl border py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
          >
            취소
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── PairingModal ─────────────────────────────────────────────────────────────
interface PairingModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: (device: IotDevice) => void
}

function PairingModal({ open, onOpenChange, onSuccess }: PairingModalProps) {
  const [pairCode, setPairCode] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const resetForm = () => {
    setPairCode('')
    setDisplayName('')
    setCodeError(null)
    setApiError(null)
  }

  const handlePairCodeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.replace(/\D/g, '').slice(0, 6)
    setPairCode(value)
    if (codeError) setCodeError(null)
  }

  const validate = (): boolean => {
    if (pairCode.length === 0) {
      setCodeError('페어링 코드를 입력해 주세요.')
      return false
    }
    if (pairCode.length !== 6) {
      setCodeError('6자리 숫자를 입력해 주세요.')
      return false
    }
    return true
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true)
    setApiError(null)
    try {
      const res = await pairIotDevice({
        pairCode,
        ...(displayName.trim() && { displayName: displayName.trim() }),
      })
      onSuccess(res.data)
      onOpenChange(false)
    } catch {
      // TODO: UI 확인용 임시 처리 — 실제 API 연동 후 아래 블록 제거하고 setApiError만 남길 것
      onSuccess({
        id: 0,
        deviceId: `mock-${pairCode}`,
        displayName: displayName.trim() || 'HeyGent',
        status: 'ACTIVE',
        lastSeenAt: null,
        createdAt: null,
        updatedAt: null,
      })
      onOpenChange(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) resetForm()
        onOpenChange(isOpen)
      }}
    >
      <DialogContent className="max-w-sm gap-5">
        <div>
          <DialogTitle className="text-base">기기 등록</DialogTitle>
          <DialogDescription className="text-muted-foreground mt-1 text-sm">
            기기 화면에 표시된 6자리 페어링 코드를 입력해 주세요.
          </DialogDescription>
        </div>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-foreground inline-flex items-center gap-1.5 text-sm font-medium">
              페어링 코드
              <HelpHint label="페어링 코드 도움말" iconClassName="h-3.5 w-3.5">
                <p className="text-foreground font-medium">페어링 코드</p>
                <p>
                  기기 화면에 잠깐 표시되는{' '}
                  <span className="text-foreground">6자리 일회용 비밀번호</span>예요.
                </p>
                <p>이 코드를 맞춰 넣어야 내 계정과 기기가 짝이 됩니다.</p>
                <p>시간이 지나면 자동으로 새 코드로 바뀝니다.</p>
              </HelpHint>
            </label>
            <input
              type="text"
              inputMode="numeric"
              placeholder="6자리 숫자"
              value={pairCode}
              onChange={handlePairCodeChange}
              maxLength={6}
              className="border-border bg-background text-foreground placeholder:text-muted-foreground focus:border-foreground/40 w-full rounded-lg border px-3 py-2 text-sm tracking-widest transition-colors outline-none"
            />
            {codeError && <p className="text-destructive text-xs">{codeError}</p>}
          </div>

          <div className="space-y-1.5">
            <label className="text-foreground text-sm font-medium">
              기기 이름 <span className="text-muted-foreground font-normal">(선택)</span>
            </label>
            <input
              type="text"
              placeholder="HeyGent 1"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value.slice(0, 100))}
              maxLength={100}
              className="border-border bg-background text-foreground placeholder:text-muted-foreground focus:border-foreground/40 w-full rounded-lg border px-3 py-2 text-sm transition-colors outline-none"
            />
            <p className="text-muted-foreground text-right text-xs">{displayName.length}/100</p>
          </div>

          {apiError && (
            <p className="text-destructive bg-destructive/5 rounded-lg px-3 py-2 text-xs">
              {apiError}
            </p>
          )}
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="bg-foreground text-background hover:bg-foreground/85 flex-1 rounded-xl py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {loading ? '등록 중...' : '등록하기'}
          </button>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            className="border-border text-foreground hover:bg-accent/50 flex-1 rounded-xl border py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
          >
            취소
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ── ActionButton ─────────────────────────────────────────────────────────────
interface ActionButtonProps {
  icon: React.ReactNode
  label: string
  onClick: () => void
}

function ActionButton({ icon, label, onClick }: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="border-border bg-card hover:bg-accent/50 group flex flex-col items-start gap-3 rounded-xl border p-4 transition-colors"
    >
      <div className="text-muted-foreground group-hover:text-foreground bg-muted/60 flex h-8 w-8 items-center justify-center rounded-lg transition-colors">
        {icon}
      </div>
      <span className="text-foreground text-sm font-medium">{label}</span>
    </button>
  )
}

// ── HealthMetricCard ─────────────────────────────────────────────────────────
interface HealthMetricCardProps {
  icon: React.ReactNode
  label: string
  value: string
  unit?: string
  /** 진척도 0~1 — 게이지 바 표시 */
  progress: number
  hint?: string
  detail: HealthDetailGroup
  expanded: boolean
  onToggle: () => void
}

function HealthMetricCard({
  icon,
  label,
  value,
  unit,
  progress,
  hint,
  detail,
  expanded,
  onToggle,
}: HealthMetricCardProps) {
  const pct = Math.max(0, Math.min(1, progress)) * 100
  return (
    <div
      className={`border-border bg-card flex flex-col gap-2.5 rounded-xl border p-4 ${
        expanded ? 'lg:col-span-2' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="text-muted-foreground bg-muted/60 flex h-7 w-7 shrink-0 items-center justify-center rounded-md">
            {icon}
          </div>
          <span className="text-muted-foreground truncate text-xs font-medium">{label}</span>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="border-border text-foreground hover:bg-accent/50 inline-flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-medium transition-colors"
          aria-expanded={expanded}
          aria-label={`${label} 상세 정보 ${expanded ? '접기' : '보기'}`}
        >
          {expanded ? '접기' : '자세히보기'}
          <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </button>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-foreground text-xl font-semibold tabular-nums">{value}</span>
        {unit && <span className="text-muted-foreground text-xs">{unit}</span>}
      </div>
      <div className="bg-muted/60 relative h-1 w-full overflow-hidden rounded-full">
        <div
          className="bg-foreground/70 absolute inset-y-0 left-0 rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      {hint && <p className="text-muted-foreground text-[10px]">{hint}</p>}

      {expanded && (
        <div className="border-border/70 mt-2 space-y-3 border-t pt-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-foreground text-sm font-medium">{detail.title}</p>
              <span className="bg-muted/70 text-muted-foreground rounded-full px-2 py-0.5 text-[10px]">
                {detail.status}
              </span>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">{detail.summary}</p>
          </div>
          {detail.items.map((item) => (
            <div key={item.field} className="bg-muted/35 rounded-lg px-3 py-2">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-muted-foreground text-xs">{item.label}</span>
                <span className="text-muted-foreground/80 font-mono text-[10px]">{item.field}</span>
              </div>
              <div className="flex items-end justify-between gap-2">
                <span className="text-foreground text-sm font-semibold tabular-nums">
                  {item.value}
                </span>
                <span className="text-muted-foreground text-[10px]">{item.note}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

interface HealthFieldItem {
  field: string
  label: string
  value: string
  note: string
}

interface HealthDetailGroup {
  icon: React.ReactNode
  title: string
  summary: string
  status: string
  items: HealthFieldItem[]
}

function formatNumber(value: number) {
  return value.toLocaleString('ko-KR')
}

function formatSleepDuration(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  return `${hours}h ${restMinutes}m`
}

// ── config helpers ───────────────────────────────────────────────────────────
function serverStatusConfig(s: ServerStatus) {
  return s === 'ok'
    ? { label: '정상', color: 'emerald' as const }
    : { label: '오류', color: 'red' as const }
}

function agentStatusConfig(s: AgentStatus) {
  return s === 'idle'
    ? { label: '대기 중', color: 'muted' as const, pulse: false }
    : { label: '작업 중', color: 'blue' as const, pulse: true }
}

// ── DashboardPage ─────────────────────────────────────────────────────────────
export function DashboardPage() {
  const navigate = useNavigate()
  const { setSidebarCollapsed, setSettingsOpen } = useUIStore()

  const [iotDevices, setIotDevices] = useState<IotDevice[]>([])
  const [iotLoading, setIotLoading] = useState(true)
  const [pairingOpen, setPairingOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingDeviceId, setPendingDeviceId] = useState<string | null>(null)
  const [newSessionOpen, setNewSessionOpen] = useState(false)
  const [expandedHealthGroups, setExpandedHealthGroups] = useState<string[]>([])
  const [healthData, setHealthData] = useState<HealthSummaryData | null>(null)
  const [healthLoading, setHealthLoading] = useState(true)

  const fetchDevices = useCallback(
    () =>
      getIotDevices()
        .then((res) => setIotDevices(res.data))
        .catch(() => setIotDevices([]))
        .finally(() => setIotLoading(false)),
    [],
  )

  useEffect(() => {
    void fetchDevices()
  }, [fetchDevices])

  useEffect(() => {
    getLatestHealthData()
      .then(setHealthData)
      .catch(() => setHealthData(null))
      .finally(() => setHealthLoading(false))
  }, [])

  const handleDeregisterRequest = (deviceId: string) => {
    setPendingDeviceId(deviceId)
    setConfirmOpen(true)
  }

  const handleDeregisterConfirm = async () => {
    if (!pendingDeviceId) return
    try {
      await deleteIotDevice(pendingDeviceId)
    } catch {
      // TODO: UI 확인용 임시 처리 — 실제 API 연동 후 제거할 것
    }
    setConfirmOpen(false)
    setPendingDeviceId(null)
    setIotLoading(true)
    await fetchDevices()
  }

  const server = serverStatusConfig(MOCK_SERVER)
  const agent = agentStatusConfig(MOCK_AGENT)
  const device = iotDevices[0] ?? null
  const health = healthData
  const toggleHealthGroup = (title: string) => {
    setExpandedHealthGroups((current) =>
      current.includes(title) ? current.filter((item) => item !== title) : [...current, title],
    )
  }
  const healthGroups: HealthDetailGroup[] = health
    ? [
        {
          title: '활동',
          icon: <Activity className="h-4 w-4" />,
          summary: `${formatNumber(health.stepCount ?? 0)}걸음, 활동 ${health.activeMinutes ?? '--'}분을 기록했습니다.`,
          status: (health.activeMinutes ?? 0) >= 60 ? '충분' : '보완 필요',
          items: [
            {
              field: 'stepCount',
              label: '걸음 수',
              value: `${formatNumber(health.stepCount ?? 0)} 걸음`,
              note: '목표 10,000',
            },
            {
              field: 'activeMinutes',
              label: '활동 시간',
              value: health.activeMinutes != null ? `${health.activeMinutes}분` : '--',
              note: '목표 60분',
            },
            {
              field: 'totalCalories',
              label: '총 칼로리',
              value:
                health.totalCalories != null ? `${formatNumber(health.totalCalories)} kcal` : '--',
              note: '일일 소비량',
            },
            {
              field: 'activeCalories',
              label: '활동 칼로리',
              value:
                health.activeCalories != null
                  ? `${formatNumber(health.activeCalories)} kcal`
                  : '--',
              note: '운동 기여',
            },
          ],
        },
        {
          title: '체성분',
          icon: <Activity className="h-4 w-4" />,
          summary: `몸무게 ${health.weightKg ?? '--'}kg, 체지방률 ${health.bodyFatPct ?? '--'}% 기준으로 추이를 확인합니다.`,
          status: '추이 관찰',
          items: [
            {
              field: 'heightCm',
              label: '키',
              value: health.heightCm != null ? `${health.heightCm} cm` : '--',
              note: '기준값',
            },
            {
              field: 'weightKg',
              label: '몸무게',
              value: health.weightKg != null ? `${health.weightKg} kg` : '--',
              note: '최근 측정',
            },
            {
              field: 'bodyFatPct',
              label: '체지방률',
              value: health.bodyFatPct != null ? `${health.bodyFatPct}%` : '--',
              note: '추이 확인',
            },
            {
              field: 'muscleMassKg',
              label: '근육량',
              value: health.muscleMassKg != null ? `${health.muscleMassKg} kg` : '--',
              note: '추이 확인',
            },
          ],
        },
        {
          title: '활력',
          icon: <Heart className="h-4 w-4" />,
          summary: `심박 ${health.heartRateBpm ?? '--'}bpm, 혈압 ${health.systolicBp ?? '--'}/${health.diastolicBp ?? '--'}mmHg입니다.`,
          status: '안정',
          items: [
            {
              field: 'heartRateBpm',
              label: '심박수',
              value: health.heartRateBpm != null ? `${health.heartRateBpm} bpm` : '--',
              note: '안정 범위',
            },
            {
              field: 'systolicBp',
              label: '수축기 혈압',
              value: health.systolicBp != null ? `${health.systolicBp} mmHg` : '--',
              note: '정상',
            },
            {
              field: 'diastolicBp',
              label: '이완기 혈압',
              value: health.diastolicBp != null ? `${health.diastolicBp} mmHg` : '--',
              note: '정상',
            },
          ],
        },
        {
          title: '수면',
          icon: <Moon className="h-4 w-4" />,
          summary: `${formatSleepDuration(health.durationMinutes ?? 0)} 수면, 수면 점수 ${health.sleepScore ?? '--'}점입니다.`,
          status: (health.durationMinutes ?? 0) >= 420 ? '양호' : '부족',
          items: [
            {
              field: 'durationMinutes',
              label: '수면 시간',
              value:
                health.durationMinutes != null ? formatSleepDuration(health.durationMinutes) : '--',
              note: '목표 8h',
            },
            {
              field: 'sleepScore',
              label: '수면 점수',
              value: health.sleepScore != null ? `${health.sleepScore}점` : '--',
              note: '보통',
            },
          ],
        },
      ]
    : []

  const [activityHealth, bodyCompositionHealth, vitalityHealth, sleepHealth] = healthGroups
  const healthMetricCards =
    health && activityHealth && bodyCompositionHealth && vitalityHealth && sleepHealth
      ? [
          {
            detail: activityHealth,
            icon: <Footprints className="h-4 w-4" />,
            label: activityHealth.title,
            value: health.stepCount != null ? formatNumber(health.stepCount) : '--',
            unit: '걸음',
            progress: (health.stepCount ?? 0) / 10000,
            hint: `활동 ${health.activeMinutes ?? '--'}분`,
          },
          {
            detail: bodyCompositionHealth,
            icon: bodyCompositionHealth.icon,
            label: bodyCompositionHealth.title,
            value: health.weightKg != null ? String(health.weightKg) : '--',
            unit: 'kg',
            progress: (health.bodyFatPct ?? 0) / 35,
            hint: `체지방률 ${health.bodyFatPct ?? '--'}%`,
          },
          {
            detail: vitalityHealth,
            icon: vitalityHealth.icon,
            label: vitalityHealth.title,
            value: health.heartRateBpm != null ? String(health.heartRateBpm) : '--',
            unit: 'bpm',
            progress: (health.heartRateBpm ?? 0) / 130,
            hint: `혈압 ${health.systolicBp ?? '--'}/${health.diastolicBp ?? '--'}`,
          },
          {
            detail: sleepHealth,
            icon: sleepHealth.icon,
            label: sleepHealth.title,
            value:
              health.durationMinutes != null ? formatSleepDuration(health.durationMinutes) : '--',
            unit: '',
            progress: (health.durationMinutes ?? 0) / 480,
            hint: `수면 점수 ${health.sleepScore ?? '--'}점`,
          },
        ]
      : []

  return (
    <div className="bg-background flex-1 overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto w-full max-w-4xl px-6 py-10">
        <div className="space-y-8">
          {/* 섹션: 시스템 상태 */}
          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <p className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
              시스템 상태
            </p>
            <div className="grid grid-cols-2 gap-3">
              <StatusCard
                icon={<Server className="h-4 w-4" />}
                title="서버 연결"
                statusLabel={server.label}
                dotColor={server.color}
              />
              <StatusCard
                icon={<Bot className="h-4 w-4" />}
                title="에이전트"
                statusLabel={agent.label}
                dotColor={agent.color}
                pulse={agent.pulse}
              />
              <IotCard
                loading={iotLoading}
                device={device}
                onRegister={() => setPairingOpen(true)}
                onDeregister={handleDeregisterRequest}
              />
              <BridgeCard />
            </div>
          </motion.section>

          {/* 구분선 */}
          <div className="border-border border-t" />

          {/* 섹션: 빠른 실행 */}
          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 }}
          >
            <p className="text-muted-foreground mb-3 text-xs font-medium tracking-wide uppercase">
              빠른 실행
            </p>
            <div className="grid grid-cols-3 gap-3">
              <ActionButton
                icon={<Eye className="h-4 w-4" />}
                label="내 사무실 보기"
                onClick={() => navigate('/agent-status')}
              />
              <ActionButton
                icon={<Plus className="h-4 w-4" />}
                label="새 작업 요청하기"
                onClick={() => setNewSessionOpen(true)}
              />
              <ActionButton
                icon={<KeyRound className="h-4 w-4" />}
                label="API 키 등록"
                onClick={() => setSettingsOpen(true, 'apiKeys')}
              />
            </div>
          </motion.section>

          {/* 구분선 */}
          <div className="border-border border-t" />

          {/* 섹션: 건강 정보 */}
          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.15 }}
          >
            <div className="mb-3 flex items-center justify-between">
              <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                건강 정보
              </p>
              <span className="text-muted-foreground inline-flex items-center gap-1 text-[10px]">
                <Activity className="h-3 w-3" />
                Samsung Health 연동
              </span>
            </div>

            {healthLoading ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[...Array(4)].map((_, i) => (
                  <div
                    key={i}
                    className="border-border bg-card h-24 animate-pulse rounded-xl border"
                  />
                ))}
              </div>
            ) : healthMetricCards.length === 0 ? (
              <div className="border-border bg-card flex flex-col items-center justify-center gap-2 rounded-xl border px-4 py-10">
                <Activity className="text-muted-foreground h-8 w-8" />
                <p className="text-muted-foreground text-sm">건강 데이터가 없습니다.</p>
                <p className="text-muted-foreground text-xs">
                  Samsung Health 앱에서 데이터를 연동해 주세요.
                </p>
              </div>
            ) : (
              <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {healthMetricCards.map((card) => (
                  <HealthMetricCard
                    key={card.detail.title}
                    icon={card.icon}
                    label={card.label}
                    value={card.value}
                    unit={card.unit}
                    progress={card.progress}
                    hint={card.hint}
                    detail={card.detail}
                    expanded={expandedHealthGroups.includes(card.detail.title)}
                    onToggle={() => toggleHealthGroup(card.detail.title)}
                  />
                ))}
              </div>
            )}

            <div className="border-border bg-card rounded-xl border p-4">
              <div className="mb-3 flex items-center gap-3">
                <div className="bg-muted text-foreground/70 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                  <Sparkles className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <p className="text-foreground text-sm font-medium">LLM 건강 검토</p>
                  <p className="text-muted-foreground text-xs">
                    요약, 부족한 항목 피드백, 다음 행동 권장 사항
                  </p>
                </div>
              </div>
              <div className="bg-muted/35 rounded-lg p-3">
                <p className="text-muted-foreground mb-1 text-xs">오늘의 요약</p>
                <p className="text-foreground text-sm leading-relaxed">
                  심박과 혈압은 안정적이며 활동량은 중간 수준입니다. 수면 시간이 짧아 회복 지표가
                  우선 관리 대상입니다.
                </p>
              </div>
            </div>
          </motion.section>
        </div>
      </div>

      <PairingModal
        open={pairingOpen}
        onOpenChange={setPairingOpen}
        onSuccess={(registered) => {
          setIotDevices([registered])
          setPairingOpen(false)
        }}
      />

      <DeregisterConfirmModal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={handleDeregisterConfirm}
      />

      <NewSessionModal
        open={newSessionOpen}
        onOpenChange={setNewSessionOpen}
        onConfirm={(config) => {
          storePendingSessionConfig(config)
          setNewSessionOpen(false)
          if (config && !config.seedDefaultAgents) {
            setSidebarCollapsed(false)
            navigate('/agent-status')
          } else {
            setSidebarCollapsed(true)
            navigate('/new-chat')
          }
        }}
      />
    </div>
  )
}

function storePendingSessionConfig(config: CustomAgentConfig | undefined) {
  if (config === undefined) {
    sessionStorage.removeItem('ai-new-session-config')
    return
  }
  sessionStorage.setItem('ai-new-session-config', JSON.stringify(config))
}
