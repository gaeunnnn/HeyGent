import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Monitor, Copy, Check, Loader2, Trash2, RefreshCw, X, Download } from 'lucide-react'

// 브릿지 .exe 다운로드 경로 — frontend/public/downloads/ 아래 정적 파일.
// 빌드 명령: pyinstaller --onefile --windowed --name HeyGentBridge --collect-all customtkinter --collect-all pystray --paths . bridge/tray.py
const BRIDGE_EXE_PATH = '/downloads/HeyGentBridge.exe'
import {
  issueBridgePairingCode,
  listBridgeDevices,
  revokeBridgeDevice,
  type BridgeDevice,
  type BridgePairingCode,
} from '@/apis/bridge'

/**
 * 브릿지 설정 페이지.
 *
 * 기존 코드와 충돌을 피하기 위해 별도 라우트(/settings/bridge) + 별도 페이지로 분리.
 * 기능:
 *  - "새 브릿지 연결" 모달: backend 에 페어링 코드 발급 요청, 큰 글씨로 표시 + 카운트다운.
 *  - 디바이스 목록: 연결된 PC 들과 해제 버튼.
 *  - 자동 새로고침: 모달이 열려있는 동안 5초마다 devices 목록을 폴링해 새 디바이스 등장 시 모달 자동 닫힘.
 */
export function BridgeSettingsPage() {
  const [devices, setDevices] = useState<BridgeDevice[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [pairingModalOpen, setPairingModalOpen] = useState(false)

  const refreshDevices = useCallback(async () => {
    setIsLoadingDevices(true)
    try {
      const list = await listBridgeDevices()
      setDevices(list)
      setErrorMessage(null)
    } catch (error) {
      console.error(error)
      setErrorMessage('디바이스 목록을 불러오지 못했어요.')
    } finally {
      setIsLoadingDevices(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const fetchOnce = async () => {
      try {
        const list = await listBridgeDevices()
        if (cancelled) return
        setDevices(list)
        setErrorMessage(null)
      } catch (error) {
        if (cancelled) return
        console.error(error)
        setErrorMessage('디바이스 목록을 불러오지 못했어요.')
      } finally {
        if (!cancelled) {
          setIsLoadingDevices(false)
        }
      }
    }

    void fetchOnce()
    // 10초마다 자동 갱신: 사용자가 브릿지 PC 의 프로그램을 켜고 끄는 동안 online/offline 상태를 따라가게 한다.
    const handle = window.setInterval(() => {
      void fetchOnce()
    }, 10000)
    return () => {
      cancelled = true
      window.clearInterval(handle)
    }
  }, [])

  const handleRevoke = useCallback(
    async (deviceId: number) => {
      const target = devices.find((device) => device.id === deviceId)
      const ok = window.confirm(
        target
          ? `'${target.deviceName}' 을(를) 해제할까요? 해제된 PC 는 더 이상 도구를 실행할 수 없어요.`
          : '디바이스를 해제할까요?',
      )
      if (!ok) {
        return
      }
      try {
        await revokeBridgeDevice(deviceId)
        await refreshDevices()
      } catch (error) {
        console.error(error)
        setErrorMessage('해제에 실패했어요. 잠시 후 다시 시도해 주세요.')
      }
    },
    [devices, refreshDevices],
  )

  const handleDeleteHistory = useCallback(
    async (deviceId: number) => {
      const target = devices.find((device) => device.id === deviceId)
      const ok = window.confirm(
        target
          ? `'${target.deviceName}' 의 해제 기록을 완전히 삭제할까요? 되돌릴 수 없어요.`
          : '이 기록을 삭제할까요?',
      )
      if (!ok) {
        return
      }
      try {
        // backend 가 revoked 상태이면 row 자체를 삭제한다 (active 면 revoke 만).
        await revokeBridgeDevice(deviceId)
        await refreshDevices()
      } catch (error) {
        console.error(error)
        setErrorMessage('기록 삭제에 실패했어요. 잠시 후 다시 시도해 주세요.')
      }
    },
    [devices, refreshDevices],
  )

  return (
    <main className="bg-background flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-10">
        <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <h1 className="text-foreground text-2xl font-bold">내 PC 브릿지</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              사용자 PC 에서 도구(터미널·파일)를 실행하려면 이 페이지에서 페어링한 PC 가 켜져 있어야
              해요.
            </p>
            <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
              🔒 브릿지가 받은 도구 호출은 사용자 PC 의 워크스페이스 폴더 안에서만 실행됩니다. 토큰
              같은 민감 데이터를 다루는 본체와, 임의 명령을 실행하는 워커가 별도 프로세스로 분리되어
              있어 권한이 최소화됩니다.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <a
              href={BRIDGE_EXE_PATH}
              download="HeyGentBridge.exe"
              className="border-border text-foreground hover:bg-muted inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium"
            >
              <Download className="h-4 w-4" />
              브릿지 다운로드
            </a>
            <button
              type="button"
              onClick={() => setPairingModalOpen(true)}
              className="inline-flex h-9 items-center rounded-md bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-700"
            >
              새 브릿지 연결
            </button>
          </div>
        </header>

        {errorMessage ? (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-500">
            {errorMessage}
          </div>
        ) : null}

        <section className="border-border bg-card rounded-xl border p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-foreground text-sm font-semibold">연결된 디바이스</h2>
            <button
              type="button"
              onClick={() => void refreshDevices()}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
            >
              <RefreshCw className="h-3.5 w-3.5" /> 새로고침
            </button>
          </div>

          {isLoadingDevices ? (
            <div className="text-muted-foreground flex items-center justify-center py-8 text-sm">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 불러오는 중...
            </div>
          ) : devices.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center justify-center gap-2 py-8 text-sm">
              <Monitor className="h-8 w-8 opacity-50" />
              아직 연결된 PC 가 없어요. 오른쪽 위 “새 브릿지 연결” 을 눌러주세요.
            </div>
          ) : (
            <ul className="divide-border divide-y">
              {devices.map((device) => {
                const isActive = !device.revokedAt
                const isOnline = device.online
                const statusLabel = !isActive ? '해제됨' : isOnline ? '온라인' : '오프라인'
                const statusColor = !isActive
                  ? 'text-muted-foreground'
                  : isOnline
                    ? 'text-emerald-500'
                    : 'text-amber-500'
                const iconWrapColor = !isActive
                  ? 'bg-muted text-muted-foreground'
                  : isOnline
                    ? 'bg-emerald-500/10 text-emerald-500'
                    : 'bg-amber-500/10 text-amber-500'
                return (
                  <li key={device.id} className="flex items-center justify-between py-3">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-9 w-9 items-center justify-center rounded-md ${iconWrapColor}`}
                      >
                        <Monitor className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="text-foreground text-sm font-medium">
                          {device.deviceName}
                        </div>
                        <div className="text-muted-foreground text-xs">
                          <span className={statusColor}>{statusLabel}</span> · 마지막 접속:{' '}
                          {formatRelative(device.lastSeenAt)}
                        </div>
                      </div>
                    </div>
                    {isActive ? (
                      <button
                        type="button"
                        onClick={() => void handleRevoke(device.id)}
                        className="border-border text-muted-foreground inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:text-red-500"
                      >
                        <Trash2 className="h-3.5 w-3.5" /> 해제
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleDeleteHistory(device.id)}
                        title="기록 완전 삭제"
                        aria-label="기록 완전 삭제"
                        className="border-border text-muted-foreground inline-flex items-center justify-center rounded-md border p-1 text-xs hover:text-red-500"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>

      {pairingModalOpen ? (
        <PairingCodeModal
          onClose={() => setPairingModalOpen(false)}
          onDeviceAppeared={async () => {
            await refreshDevices()
            setPairingModalOpen(false)
          }}
          deviceCount={devices.filter((d) => !d.revokedAt).length}
        />
      ) : null}
    </main>
  )
}

interface PairingCodeModalProps {
  onClose: () => void
  onDeviceAppeared: () => void | Promise<void>
  deviceCount: number
}

function PairingCodeModal({ onClose, onDeviceAppeared, deviceCount }: PairingCodeModalProps) {
  const [pairing, setPairing] = useState<BridgePairingCode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [remainingSeconds, setRemainingSeconds] = useState<number>(300)
  const baselineCountRef = useRef<number>(deviceCount)

  useEffect(() => {
    let mounted = true
    issueBridgePairingCode()
      .then((data) => {
        if (!mounted) return
        setPairing(data)
        setError(null)
      })
      .catch((err) => {
        console.error(err)
        if (!mounted) return
        setError('페어링 코드를 발급받지 못했어요. 잠시 후 다시 시도해 주세요.')
      })
    return () => {
      mounted = false
    }
  }, [])

  // 만료 카운트다운.
  useEffect(() => {
    if (!pairing?.expiresAt) return undefined
    const update = () => {
      const expires = new Date(pairing.expiresAt).getTime()
      const now = Date.now()
      const left = Math.max(0, Math.floor((expires - now) / 1000))
      setRemainingSeconds(left)
    }
    update()
    const handle = window.setInterval(update, 1000)
    return () => window.clearInterval(handle)
  }, [pairing?.expiresAt])

  // 5초마다 디바이스 목록 폴링: 새 디바이스가 들어오면 자동 닫기.
  useEffect(() => {
    const handle = window.setInterval(async () => {
      try {
        const list = await listBridgeDevices()
        const activeCount = list.filter((device) => !device.revokedAt).length
        if (activeCount > baselineCountRef.current) {
          await onDeviceAppeared()
        }
      } catch (err) {
        console.error(err)
      }
    }, 5000)
    return () => window.clearInterval(handle)
  }, [onDeviceAppeared])

  const formattedCode = useMemo(() => formatCode(pairing?.code ?? ''), [pairing?.code])

  const handleCopy = useCallback(() => {
    if (!pairing?.code) return
    void navigator.clipboard.writeText(pairing.code).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }, [pairing])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="border-border bg-card relative w-full max-w-md rounded-2xl border p-6 shadow-2xl">
        <h2 className="text-foreground text-lg font-semibold">브릿지 페어링 코드</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          PC 에서 HeyGent 브릿지 프로그램을 실행하고, 이 코드와 디바이스 이름을 입력하세요.
        </p>

        <div className="border-border bg-background mt-6 flex flex-col items-center gap-3 rounded-xl border py-6">
          {error ? (
            <div className="text-sm text-red-500">{error}</div>
          ) : !pairing ? (
            <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
          ) : (
            <>
              <div className="text-foreground font-mono text-5xl tracking-[0.4em]">
                {formattedCode}
              </div>
              <div className="text-muted-foreground text-xs">
                {remainingSeconds > 0
                  ? `남은 시간 ${formatSeconds(remainingSeconds)}`
                  : '코드가 만료되었어요. 다시 발급해 주세요.'}
              </div>
              <button
                type="button"
                onClick={handleCopy}
                className="border-border hover:bg-muted inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? '복사됨' : '코드 복사'}
              </button>
            </>
          )}
        </div>

        <p className="text-muted-foreground mt-4 text-xs">
          페어링이 완료되면 이 창은 자동으로 닫혀요. (5초마다 자동 확인)
        </p>

        <a
          href={BRIDGE_EXE_PATH}
          download="HeyGentBridge.exe"
          className="border-border text-muted-foreground hover:bg-muted mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md border px-3 py-2 text-xs"
        >
          <Download className="h-3.5 w-3.5" /> 브릿지 프로그램이 없으면 먼저 다운로드
        </a>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="border-border text-muted-foreground hover:text-foreground rounded-md border px-3 py-1.5 text-sm"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  )
}

function formatCode(code: string): string {
  if (code.length !== 6) {
    return code
  }
  return `${code.slice(0, 3)} ${code.slice(3)}`
}

function formatSeconds(total: number): string {
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

function formatRelative(timestamp: string | null): string {
  if (!timestamp) {
    return '없음'
  }
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) {
    return '없음'
  }
  return date.toLocaleString()
}
