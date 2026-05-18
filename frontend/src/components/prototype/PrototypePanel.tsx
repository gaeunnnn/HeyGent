import {
  SandpackCodeEditor,
  SandpackFileExplorer,
  SandpackLayout,
  SandpackProvider,
  type SandpackFiles,
  useSandpack,
  useSandpackClient,
} from '@codesandbox/sandpack-react'
import { ArrowLeft, ArrowRight, Code2, Download, Eye, Loader2, RefreshCw, X } from 'lucide-react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { getActivePrototypeArtifact, type PrototypeArtifact } from '@/apis/prototypes'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

type PrototypePanelProps = {
  sessionId: string
  openHint: boolean
  pollForArtifact?: boolean
  reopenSignal?: number
  onArtifactVisible?: () => void
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error'
type PrototypeTab = 'preview' | 'code'

const MIN_PROTOTYPE_PANEL_WIDTH = 480
const MAX_PROTOTYPE_PANEL_WIDTH = 1040
const PROTOTYPE_CORE_DEPENDENCIES = {
  react: '^19.2.5',
  'react-dom': '^19.2.5',
} as const
const PROTOTYPE_AVAILABLE_DEPENDENCIES = {
  '@dnd-kit/core': '^6.3.1',
  '@dnd-kit/utilities': '^3.2.2',
  '@radix-ui/react-accordion': '^1.2.12',
  '@radix-ui/react-alert-dialog': '^1.1.15',
  '@radix-ui/react-aspect-ratio': '^1.1.8',
  '@radix-ui/react-avatar': '^1.1.11',
  '@radix-ui/react-checkbox': '^1.3.3',
  '@radix-ui/react-collapsible': '^1.1.12',
  '@radix-ui/react-context-menu': '^2.2.16',
  '@radix-ui/react-dialog': '^1.1.15',
  '@radix-ui/react-dropdown-menu': '^2.1.16',
  '@radix-ui/react-hover-card': '^1.1.15',
  '@radix-ui/react-label': '^2.1.8',
  '@radix-ui/react-menubar': '^1.1.16',
  '@radix-ui/react-navigation-menu': '^1.2.14',
  '@radix-ui/react-popover': '^1.1.15',
  '@radix-ui/react-progress': '^1.1.8',
  '@radix-ui/react-radio-group': '^1.3.8',
  '@radix-ui/react-scroll-area': '^1.2.10',
  '@radix-ui/react-select': '^2.2.6',
  '@radix-ui/react-separator': '^1.1.8',
  '@radix-ui/react-slider': '^1.3.6',
  '@radix-ui/react-slot': '^1.2.4',
  '@radix-ui/react-switch': '^1.2.6',
  '@radix-ui/react-tabs': '^1.1.13',
  '@radix-ui/react-toggle': '^1.1.10',
  '@radix-ui/react-toggle-group': '^1.1.11',
  '@radix-ui/react-tooltip': '^1.2.8',
  '@react-three/drei': '^10.7.7',
  '@react-three/fiber': '^9.6.1',
  '@xyflow/react': '^12.10.2',
  animejs: '^4.4.1',
  axios: '^1.15.2',
  bootstrap: '^5.3.8',
  'class-variance-authority': '^0.7.1',
  clsx: '^2.1.1',
  cmdk: '^1.1.1',
  d3: '^7.9.0',
  'date-fns': '^4.1.0',
  'embla-carousel-react': '^8.6.0',
  'framer-motion': '^12.38.0',
  gsap: '^3.15.0',
  'input-otp': '^1.4.2',
  'lottie-react': '^2.4.1',
  'lucide-react': '^1.8.0',
  'mapbox-gl': '^3.23.1',
  motion: '^12.38.0',
  'next-themes': '^0.4.6',
  'react-day-picker': '^9.14.0',
  'react-hook-form': '^7.74.0',
  'react-icons': '^5.6.0',
  'react-is': '^19.2.6',
  'react-markdown': '^10.1.0',
  'react-resizable-panels': '^4.10.0',
  'react-router': '^7.14.2',
  recharts: '^3.8.1',
  'remark-gfm': '^4.0.1',
  sonner: '^2.0.7',
  three: '^0.184.0',
  'tailwind-merge': '^3.5.0',
  vaul: '^1.1.2',
  zustand: '^5.0.12',
} as const
const PROTOTYPE_LINKED_DEPENDENCIES: Partial<
  Record<
    keyof typeof PROTOTYPE_AVAILABLE_DEPENDENCIES,
    (keyof typeof PROTOTYPE_AVAILABLE_DEPENDENCIES)[]
  >
> = {
  '@react-three/drei': ['@react-three/fiber', 'three'],
  '@react-three/fiber': ['three'],
  recharts: ['react-is'],
}
const PROTOTYPE_DEV_DEPENDENCIES = {
  '@vitejs/plugin-react': '^6.0.1',
  typescript: '~6.0.2',
  vite: '^8.0.9',
} as const

export function PrototypePanel({
  sessionId,
  openHint,
  pollForArtifact = false,
  reopenSignal,
  onArtifactVisible,
}: PrototypePanelProps) {
  const [artifact, setArtifact] = useState<PrototypeArtifact | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [dismissedArtifact, setDismissedArtifact] = useState<{
    versionId: string
    reopenSignal?: number
  } | null>(null)
  const [previewKey, setPreviewKey] = useState(0)
  const [activeTab, setActiveTab] = useState<PrototypeTab>('preview')
  const [panelWidth, setPanelWidth] = useState(() => getInitialPanelWidth())
  const notifiedVersionIdRef = useRef<string | null>(null)
  const shouldPoll = pollForArtifact

  useEffect(() => {
    let cancelled = false

    const load = async (showLoading: boolean) => {
      if (showLoading) setLoadState('loading')
      try {
        const response = await getActivePrototypeArtifact(sessionId)
        if (cancelled) return
        setArtifact(response.artifact)
        setLoadState('ready')
        setErrorMessage(null)
        if (response.artifact && notifiedVersionIdRef.current !== response.artifact.versionId) {
          notifiedVersionIdRef.current = response.artifact.versionId
          onArtifactVisible?.()
        }
      } catch (error) {
        if (cancelled) return
        setLoadState('error')
        setErrorMessage(
          error instanceof Error ? error.message : '프로토타입을 불러오지 못했습니다.',
        )
      }
    }

    void load(true)
    const intervalId = shouldPoll
      ? window.setInterval(() => {
          void load(false)
        }, 2500)
      : undefined

    return () => {
      cancelled = true
      if (intervalId !== undefined) window.clearInterval(intervalId)
    }
  }, [onArtifactVisible, sessionId, shouldPoll])

  const visible = Boolean(openHint || artifact)
  const dismissed =
    artifact?.versionId !== undefined &&
    dismissedArtifact?.versionId === artifact.versionId &&
    dismissedArtifact.reopenSignal === reopenSignal

  if (!visible || dismissed) {
    return null
  }

  const title = artifact?.title ?? '프로토타입 생성 중'
  const presetLabel = artifact?.designPresetId ?? 'DESIGN.md'
  const handleResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = panelWidth
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const maxWidth =
        typeof window === 'undefined'
          ? MAX_PROTOTYPE_PANEL_WIDTH
          : Math.min(
              MAX_PROTOTYPE_PANEL_WIDTH,
              Math.max(MIN_PROTOTYPE_PANEL_WIDTH, window.innerWidth - 360),
            )
      const nextWidth = startWidth + startX - moveEvent.clientX
      setPanelWidth(Math.min(maxWidth, Math.max(MIN_PROTOTYPE_PANEL_WIDTH, nextWidth)))
    }

    const handlePointerUp = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
  }

  return (
    <aside
      className="border-border bg-background relative flex h-full min-h-0 shrink-0 flex-col self-stretch overflow-hidden border-l"
      style={{ width: panelWidth }}
    >
      <div
        role="separator"
        aria-label="프로토타입 패널 너비 조절"
        className="hover:bg-primary/40 absolute top-0 left-0 z-10 h-full w-1 cursor-col-resize bg-transparent transition-colors"
        onPointerDown={handleResizeStart}
      />
      <header className="border-border flex h-12 items-center gap-2 border-b px-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="text-foreground truncate text-sm font-semibold">{title}</span>
            <span className="bg-muted text-muted-foreground shrink-0 rounded-md px-1.5 py-0.5 text-[11px]">
              {presetLabel}
            </span>
          </div>
          <p className="text-muted-foreground truncate text-[11px]">
            {artifact?.summary ?? 'DESIGN.md를 읽고 React 화면 코드를 구성하고 있습니다.'}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="프리뷰 새로고침"
          onClick={() => setPreviewKey((value) => value + 1)}
          disabled={!artifact}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="프로토타입 패널 닫기"
          onClick={() =>
            setDismissedArtifact({ versionId: artifact?.versionId ?? 'pending', reopenSignal })
          }
        >
          <X className="h-4 w-4" />
        </Button>
      </header>

      {artifact ? (
        <PrototypeSandpack
          key={`${artifact.versionId}:${previewKey}`}
          activeTab={activeTab}
          artifact={artifact}
          onTabChange={setActiveTab}
        />
      ) : (
        <PrototypeLoading loadState={loadState} errorMessage={errorMessage} />
      )}
    </aside>
  )
}

function PrototypeSandpack({
  activeTab,
  artifact,
  onTabChange,
}: {
  activeTab: PrototypeTab
  artifact: PrototypeArtifact
  onTabChange: (value: PrototypeTab) => void
}) {
  const dependencies = useMemo(() => resolvePrototypeDependencies(artifact), [artifact])
  const files = useMemo(() => buildSandpackFiles(artifact, dependencies), [artifact, dependencies])
  const mountKey = useId()
  const previousTabRef = useRef(activeTab)
  const [runtimeKey, setRuntimeKey] = useState(0)

  useEffect(() => {
    if (previousTabRef.current !== activeTab && activeTab === 'preview') {
      setRuntimeKey((value) => value + 1)
    }
    previousTabRef.current = activeTab
  }, [activeTab])

  return (
    <div className="prototype-sandpack flex min-h-0 w-full min-w-0 flex-1 flex-col bg-[#0b1020] [&_.cm-content]:!text-slate-100 [&_.cm-editor]:!h-full [&_.cm-editor]:!w-full [&_.cm-editor]:!bg-[#0b1020] [&_.cm-gutters]:!border-slate-800 [&_.cm-gutters]:!bg-[#0b1020] [&_.cm-gutters]:!text-slate-500 [&_.cm-line]:!text-slate-100 [&_.cm-scroller]:!h-full [&_.cm-scroller]:!w-full [&_.sp-code-editor]:!h-full [&_.sp-code-editor]:!w-full [&_.sp-code-editor]:!bg-[#0b1020] [&_.sp-file-explorer]:!h-full [&_.sp-file-explorer]:!bg-[#0f172a] [&_.sp-file-explorer]:!text-slate-200 [&_.sp-layout]:!h-full [&_.sp-layout]:!w-full [&_.sp-layout]:!max-w-none [&_.sp-layout]:!flex-1 [&_.sp-layout]:!bg-[#0b1020] [&_.sp-preview]:!h-full [&_.sp-preview]:!w-full [&_.sp-preview]:!max-w-none [&_.sp-preview-container]:!h-full [&_.sp-preview-container]:!w-full [&_.sp-preview-container]:!max-w-none [&_.sp-stack]:!h-full [&_.sp-stack]:!w-full [&_.sp-wrapper]:!h-full [&_.sp-wrapper]:!w-full [&_.sp-wrapper]:!max-w-none [&_iframe]:!h-full [&_iframe]:!w-full">
      <style>{`
        .prototype-sandpack .sp-wrapper,
        .prototype-sandpack .sp-layout,
        .prototype-sandpack .sp-stack,
        .prototype-sandpack .sp-preview,
        .prototype-sandpack .sp-preview-container,
        .prototype-sandpack .sp-code-editor,
        .prototype-sandpack .cm-editor,
        .prototype-sandpack iframe {
          width: 100% !important;
          max-width: none !important;
          min-width: 0 !important;
        }

        .prototype-sandpack .sp-layout,
        .prototype-sandpack .sp-preview,
        .prototype-sandpack .sp-code-editor {
          flex: 1 1 0% !important;
        }
      `}</style>
      <SandpackProvider
        key={`${artifact.versionId}:${mountKey}:${runtimeKey}`}
        files={files}
        template="react-ts"
        theme="dark"
        customSetup={{
          dependencies,
          devDependencies: PROTOTYPE_DEV_DEPENDENCIES,
        }}
        options={{
          activeFile: artifact.entryFile || '/src/App.tsx',
          autorun: true,
          autoReload: true,
          initMode: 'immediate',
          visibleFiles: Object.keys(files).filter((path) => path.startsWith('/src/')),
        }}
      >
        <Tabs
          value={activeTab}
          onValueChange={(value) => onTabChange(value as PrototypeTab)}
          className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col"
        >
          <div className="border-border bg-background flex h-10 shrink-0 items-center justify-between border-b px-3">
            <TabsList className="dark:bg-muted dark:text-muted-foreground h-8 bg-slate-200 text-slate-700">
              <TabsTrigger
                value="preview"
                className="dark:data-[state=active]:!bg-background dark:data-[state=active]:!text-foreground h-7 gap-1.5 px-2 text-xs data-[state=active]:!bg-white data-[state=active]:!text-slate-950"
              >
                <Eye className="h-3.5 w-3.5" />
                Preview
              </TabsTrigger>
              <TabsTrigger
                value="code"
                className="dark:data-[state=active]:!bg-background dark:data-[state=active]:!text-foreground h-7 gap-1.5 px-2 text-xs data-[state=active]:!bg-white data-[state=active]:!text-slate-950"
              >
                <Code2 className="h-3.5 w-3.5" />
                Code
              </TabsTrigger>
            </TabsList>
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground text-[11px]">v{artifact.versionNumber}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="프로토타입 ZIP 다운로드"
                title="프로토타입 ZIP 다운로드"
                onClick={() => downloadPrototypeZip(artifact, files)}
              >
                <Download className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          <TabsContent
            forceMount
            value="preview"
            className={`m-0 min-h-0 w-full min-w-0 flex-1 overflow-hidden ${
              activeTab === 'preview' ? 'flex' : 'hidden'
            }`}
          >
            <SandpackLayout
              className="h-full min-h-0 w-full min-w-0 flex-1 !rounded-none !border-0"
              style={{ flex: '1 1 0%', maxWidth: 'none', minWidth: 0, width: '100%' }}
            >
              <PrototypePreviewFrame versionId={artifact.versionId} />
            </SandpackLayout>
          </TabsContent>
          <TabsContent
            forceMount
            value="code"
            className={`m-0 min-h-0 w-full min-w-0 flex-1 overflow-hidden ${
              activeTab === 'code' ? 'flex' : 'hidden'
            }`}
          >
            <SandpackLayout
              className="h-full min-h-0 w-full min-w-0 flex-1 !rounded-none !border-0"
              style={{ flex: '1 1 0%', maxWidth: 'none', minWidth: 0, width: '100%' }}
            >
              <SandpackFileExplorer className="h-full min-w-48 shrink-0" />
              <SandpackCodeEditor
                className="h-full min-h-0 min-w-0 flex-1"
                showLineNumbers
                showTabs
                closableTabs
              />
            </SandpackLayout>
          </TabsContent>
        </Tabs>
        <SandpackAutoRun activeTab={activeTab} versionId={artifact.versionId} />
      </SandpackProvider>
    </div>
  )
}

function PrototypePreviewFrame({ versionId }: { versionId: string }) {
  const { dispatch, iframe, listen } = useSandpackClient({ startRoute: '/' })
  const [loadingState, setLoadingState] = useState({ versionId, isLoading: true })
  const listenRef = useRef(listen)
  const isLoading = loadingState.versionId !== versionId || loadingState.isLoading

  useEffect(() => {
    listenRef.current = listen
  }, [listen])

  useEffect(() => {
    const unsubscribe = listenRef.current((message) => {
      if (message.type === 'start') {
        setLoadingState({ versionId, isLoading: true })
      }

      if (message.type === 'done') {
        setLoadingState({ versionId, isLoading: false })
      }
    })

    const fallbackId = window.setTimeout(() => {
      setLoadingState({ versionId, isLoading: false })
    }, 6000)

    return () => {
      unsubscribe()
      window.clearTimeout(fallbackId)
    }
  }, [versionId])

  const refreshPreview = useCallback(() => {
    setLoadingState({ versionId, isLoading: true })
    dispatch({ type: 'refresh' })
  }, [dispatch, versionId])

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col bg-white">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-slate-200 bg-slate-50 px-3">
        <button
          type="button"
          onClick={() => dispatch({ type: 'urlback' })}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900"
          aria-label="프리뷰 뒤로 가기"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => dispatch({ type: 'urlforward' })}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900"
          aria-label="프리뷰 앞으로 가기"
        >
          <ArrowRight className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={refreshPreview}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900"
          aria-label="프리뷰 새로고침"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <input
          aria-label="프리뷰 주소"
          readOnly
          value="/"
          className="h-7 min-w-0 flex-1 rounded-full border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none focus:border-slate-400"
        />
      </div>
      <div className="relative min-h-0 flex-1 bg-white">
        <iframe
          ref={iframe}
          title="Prototype Preview"
          className="block h-full w-full border-0 bg-white"
          style={{ colorScheme: 'light' }}
          onLoad={() => {
            window.setTimeout(() => setLoadingState({ versionId, isLoading: false }), 300)
          }}
        />
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/90 text-sm text-slate-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            프리뷰를 준비하는 중입니다.
          </div>
        ) : null}
      </div>
    </div>
  )
}

function SandpackAutoRun({ activeTab, versionId }: { activeTab: PrototypeTab; versionId: string }) {
  const { sandpack } = useSandpack()
  const { runSandpack } = sandpack
  const runSandpackRef = useRef(runSandpack)

  useEffect(() => {
    runSandpackRef.current = runSandpack
  }, [runSandpack])

  const schedulePreviewRun = useCallback(
    () =>
      [150].map((delay) =>
        window.setTimeout(() => {
          runSandpackRef.current()
        }, delay),
      ),
    [],
  )

  useEffect(() => {
    if (activeTab !== 'preview') return
    const timeoutIds = schedulePreviewRun()

    return () => {
      for (const timeoutId of timeoutIds) window.clearTimeout(timeoutId)
    }
  }, [activeTab, schedulePreviewRun, versionId])

  return null
}

function PrototypeLoading({
  errorMessage,
  loadState,
}: {
  errorMessage: string | null
  loadState: LoadState
}) {
  if (loadState === 'error') {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="border-border bg-card max-w-sm rounded-lg border p-4 text-sm">
          <p className="text-foreground font-medium">프로토타입을 불러오지 못했습니다</p>
          <p className="text-muted-foreground mt-2 leading-6">{errorMessage}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        디자인 컨텍스트와 React 컴포넌트를 준비하는 중입니다.
      </div>
      <Skeleton className="h-9 w-full rounded-md" />
      <div className="grid flex-1 grid-cols-[180px_minmax(0,1fr)] gap-3">
        <Skeleton className="h-full rounded-md" />
        <div className="space-y-3">
          <Skeleton className="h-20 rounded-md" />
          <Skeleton className="h-32 rounded-md" />
          <Skeleton className="h-28 rounded-md" />
        </div>
      </div>
    </div>
  )
}

function buildSandpackFiles(
  artifact: PrototypeArtifact,
  dependencies: Record<string, string>,
): SandpackFiles {
  const baseFiles: SandpackFiles = {
    '/package.json': {
      code: JSON.stringify(
        {
          scripts: { dev: 'vite --host 0.0.0.0' },
          dependencies,
          devDependencies: PROTOTYPE_DEV_DEPENDENCIES,
        },
        null,
        2,
      ),
    },
    '/index.html': {
      code: '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0" /><style>html,body,#root{margin:0;width:100%;min-height:100%;}body{overflow-x:hidden;}</style></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>',
    },
    '/src/main.tsx': {
      code: "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport './styles.css';\nimport App from './App';\n\ncreateRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);\n",
    },
    '/src/index.tsx': {
      code: "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport './styles.css';\nimport App from './App';\n\ncreateRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);\n",
    },
    '/src/App.tsx': {
      code: 'export default function App() {\n  return <main className="prototype-empty">프로토타입 코드가 아직 없습니다.</main>;\n}\n',
    },
    '/src/styles.css': {
      code: 'body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; } .prototype-empty { min-height: 100vh; display: grid; place-items: center; color: #64748b; }',
    },
  }

  return {
    ...baseFiles,
    ...Object.fromEntries(
      Object.entries(artifact.files).map(([path, file]) => [
        normalizeSandpackPath(path),
        { code: sanitizePrototypeCode(file.code) },
      ]),
    ),
  }
}

function resolvePrototypeDependencies(artifact: PrototypeArtifact): Record<string, string> {
  const dependencies: Record<string, string> = { ...PROTOTYPE_CORE_DEPENDENCIES }
  const source = Object.values(artifact.files)
    .map((file) => file.code)
    .join('\n')
  const packages = new Set<string>()
  const importPattern =
    /(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)|import\(\s*['"]([^'"]+)['"]\s*\)/g

  for (const match of source.matchAll(importPattern)) {
    const packageName = getPackageName(match[1] ?? match[2] ?? match[3] ?? '')
    if (packageName) packages.add(packageName)
  }

  for (const packageName of Array.from(packages)) {
    addPrototypeDependency(dependencies, packageName)
  }

  return dependencies
}

function addPrototypeDependency(dependencies: Record<string, string>, packageName: string) {
  if (packageName in PROTOTYPE_CORE_DEPENDENCIES) return
  if (!(packageName in PROTOTYPE_AVAILABLE_DEPENDENCIES)) return

  const dependencyName = packageName as keyof typeof PROTOTYPE_AVAILABLE_DEPENDENCIES
  dependencies[dependencyName] = PROTOTYPE_AVAILABLE_DEPENDENCIES[dependencyName]
  for (const linkedDependency of PROTOTYPE_LINKED_DEPENDENCIES[dependencyName] ?? []) {
    dependencies[linkedDependency] = PROTOTYPE_AVAILABLE_DEPENDENCIES[linkedDependency]
  }
}

function getPackageName(specifier: string) {
  const normalized = specifier.trim()
  if (!normalized || normalized.startsWith('.') || normalized.startsWith('/')) return ''
  const parts = normalized.split('/')
  if (normalized.startsWith('@')) return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : normalized
  return parts[0] ?? ''
}

function sanitizePrototypeCode(code: string) {
  return code
    .replace(/\p{Extended_Pictographic}\uFE0F?/gu, '')
    .replace(/[\uFE0E\uFE0F]/g, '')
    .replace(/[°º]/g, '도')
    .replace(/[·•]/g, '-')
}

function normalizeSandpackPath(path: string) {
  const normalized = path.replaceAll('\\', '/').trim()
  return normalized.startsWith('/') ? normalized : `/${normalized}`
}

function downloadPrototypeZip(artifact: PrototypeArtifact, files: SandpackFiles) {
  const blob = createPrototypeZipBlob(files)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = buildPrototypeZipFileName(artifact)
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function buildPrototypeZipFileName(artifact: PrototypeArtifact) {
  const title = artifact.title || 'prototype'
  const safeTitle = title
    .normalize('NFKC')
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 80)
  return `${safeTitle || 'prototype'}-v${artifact.versionNumber}.zip`
}

function createPrototypeZipBlob(files: SandpackFiles) {
  const encoder = new TextEncoder()
  const date = new Date()
  const localParts: Uint8Array[] = []
  const centralParts: Uint8Array[] = []
  let offset = 0

  const zipFiles = Object.entries(files)
    .map(([path, file]) => ({
      path: path.replaceAll('\\', '/').replace(/^\/+/, ''),
      data: encoder.encode(getSandpackFileCode(file)),
    }))
    .filter((file) => file.path.length > 0)
    .sort((left, right) => left.path.localeCompare(right.path))

  for (const file of zipFiles) {
    const name = encoder.encode(file.path)
    const crc = crc32(file.data)
    const time = toDosTime(date)
    const day = toDosDate(date)
    const localHeader = concatBytes(
      uint32(0x04034b50),
      uint16(20),
      uint16(0),
      uint16(0),
      uint16(time),
      uint16(day),
      uint32(crc),
      uint32(file.data.length),
      uint32(file.data.length),
      uint16(name.length),
      uint16(0),
      name,
    )
    localParts.push(localHeader, file.data)
    centralParts.push(
      concatBytes(
        uint32(0x02014b50),
        uint16(20),
        uint16(20),
        uint16(0),
        uint16(0),
        uint16(time),
        uint16(day),
        uint32(crc),
        uint32(file.data.length),
        uint32(file.data.length),
        uint16(name.length),
        uint16(0),
        uint16(0),
        uint16(0),
        uint16(0),
        uint32(0),
        uint32(offset),
        name,
      ),
    )
    offset += localHeader.length + file.data.length
  }

  const centralDirectory = concatBytes(...centralParts)
  const endRecord = concatBytes(
    uint32(0x06054b50),
    uint16(0),
    uint16(0),
    uint16(zipFiles.length),
    uint16(zipFiles.length),
    uint32(centralDirectory.length),
    uint32(offset),
    uint16(0),
  )

  return new Blob([concatBytes(...localParts, centralDirectory, endRecord)], {
    type: 'application/zip',
  })
}

function getSandpackFileCode(file: unknown) {
  if (typeof file === 'string') return file
  if (file && typeof file === 'object' && 'code' in file) {
    const code = (file as { code?: unknown }).code
    return typeof code === 'string' ? code : ''
  }
  return ''
}

function toDosTime(date: Date) {
  return (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2)
}

function toDosDate(date: Date) {
  return ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()
}

function uint16(value: number) {
  return Uint8Array.of(value & 0xff, (value >>> 8) & 0xff)
}

function uint32(value: number) {
  return Uint8Array.of(
    value & 0xff,
    (value >>> 8) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 24) & 0xff,
  )
}

function concatBytes(...parts: Uint8Array[]) {
  const length = parts.reduce((sum, part) => sum + part.length, 0)
  const output = new Uint8Array(length)
  let offset = 0
  for (const part of parts) {
    output.set(part, offset)
    offset += part.length
  }
  return output
}

function crc32(data: Uint8Array) {
  let crc = 0xffffffff
  for (const byte of data) {
    crc ^= byte
    for (let index = 0; index < 8; index += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function getInitialPanelWidth() {
  if (typeof window === 'undefined') return 760
  return Math.min(
    MAX_PROTOTYPE_PANEL_WIDTH,
    Math.max(MIN_PROTOTYPE_PANEL_WIDTH, Math.round(window.innerWidth * 0.5)),
  )
}
