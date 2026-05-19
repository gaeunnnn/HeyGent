import { useSearchParams } from 'react-router'
import { useEffect, useState } from 'react'
import {
  agentProfilesToPanelItems,
  createDefaultSessionAgents,
  createSessionAgent,
  createSessionAgentFromTemplate,
  deleteSessionAgent,
  updateSessionAgent,
  type AgentTemplate,
  agentProfileToAgent,
} from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import { useSessionStore } from '@/store/useSessionStore'
import { SubAgentCreateDialog } from './SubAgentCreateDialog'
import { SubAgentDraftForm } from './SubAgentDraftForm'
import { SubAgentDetailView } from './SubAgentDetailView'
import { SubAgentList } from './SubAgentList'
import { SubAgentsPanelShell } from './SubAgentsPanelShell'
import { normalizeSubAgentAdapterType } from './subAgentConfigOptions'

export function SubAgentsPanel({ sessionId }: { sessionId: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [templates, setTemplates] = useState<AgentTemplate[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const {
    getAgentPanelsForSession,
    removeAgentPanelFromSession,
    setAgentPanelsForSession,
    updateAgentPanelInSession,
  } = useSessionStore()
  const agentPanels = getAgentPanelsForSession(sessionId)
  const detailId = searchParams.get('agent')
  const createDialogOpen = searchParams.get('create') === '1'
  const initialAdapterType = normalizeSubAgentAdapterType(
    searchParams.get('adapterType') ?? undefined,
  )
  const detailItem =
    detailId === null ? undefined : agentPanels.find((panel) => panel.id === detailId)
  const draftMode = searchParams.get('new') === '1'

  useEffect(() => {
    let alive = true
    const cache = useAgentCacheStore.getState()
    void Promise.all([cache.fetchAgentTemplates(), cache.fetchSessionAgents(sessionId)])
      .then(([nextTemplates, profiles]) => {
        if (!alive) return
        setTemplates(nextTemplates)
        setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
        setLoadError(null)
      })
      .catch((error) => {
        if (!alive) return
        setLoadError(error instanceof Error ? error.message : '에이전트를 불러오지 못했습니다.')
      })
    return () => {
      alive = false
    }
  }, [sessionId, setAgentPanelsForSession])

  const resetDraft = () => {
    setSearchParams({})
  }

  const openDetail = (itemId: string) => {
    setSearchParams({ agent: itemId })
  }

  const openDetailTab = (itemId: string, tab: string) => {
    if (tab === 'dashboard') {
      setSearchParams({ agent: itemId })
      return
    }
    setSearchParams({ agent: itemId, subAgentTab: tab })
  }

  const openCreateDraft = () => {
    setSearchParams({ create: '1' })
  }

  if (draftMode) {
    return (
      <SubAgentsPanelShell title="새 에이전트" description="세부 설정">
        <SubAgentDraftForm
          key="create"
          initialAdapterType={initialAdapterType}
          onCancel={resetDraft}
          reservedNames={agentPanels.map((item) => item.agent.name)}
          onSave={(agent) => {
            void createSessionAgent(sessionId, {
              name: agent.name,
              role: agent.role ?? 'general',
              title: agent.title,
              description: agent.description,
              adapterType: agent.adapterType,
              model: agent.model,
              profileImage: agent.profileImage,
              skills: agent.skills,
              entryDocumentKey: agent.instructionsEntryFile ?? 'AGENTS.md',
              instructionsFiles: agent.instructionsFiles ?? {
                [agent.instructionsEntryFile ?? 'AGENTS.md']: agent.instructions ?? '',
              },
            })
              .then(() => {
                // 신규 서브에이전트가 생성되었으므로 캐시 무효화 후 다시 받는다.
                useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
                return useAgentCacheStore.getState().fetchSessionAgents(sessionId)
              })
              .then((profiles) => {
                setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
                resetDraft()
              })
              .catch((error) => {
                setLoadError(
                  error instanceof Error ? error.message : '에이전트를 저장하지 못했습니다.',
                )
              })
          }}
        />
      </SubAgentsPanelShell>
    )
  }

  if (detailItem !== undefined) {
    return (
      <SubAgentsPanelShell
        title={detailItem.agent.name}
        description={detailItem.agent.title || '에이전트 상세'}
        hideHeader
        width="wide"
      >
        <SubAgentDetailView
          key={`${sessionId}:${detailItem.id}`}
          item={detailItem}
          onDelete={async () => {
            await deleteSessionAgent(sessionId, detailItem.id)
            // 서브에이전트가 삭제됐으므로 캐시 무효화 — 다른 패널에서 stale 목록 안 보이도록.
            useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
            removeAgentPanelFromSession(sessionId, detailItem.id)
            resetDraft()
          }}
          onSave={(agent) => {
            const documentKey = agent.instructionsEntryFile ?? 'AGENTS.md'
            // 옵티미스틱: 사이드바·상세 헤더(이름/호칭 등)가 즉시 새 값으로 보이도록 패치 먼저.
            const previousAgent = detailItem.agent
            const optimisticAgent = { ...previousAgent, ...agent }
            updateAgentPanelInSession(sessionId, detailItem.id, optimisticAgent)
            // 사용자가 textarea 에서 편집한 본문은 `agent.instructions` 에만 들어 있고
            // `agent.instructionsFiles[documentKey]` 는 stale 인 경우가 많다 (textarea onChange 가
            // files dict 를 동시에 갱신하지 않음). 그래서 저장 시점에 instructions 를 entry document
            // key 위치에 덮어써 stale 값이 백엔드로 가지 않도록 한다.
            const mergedFiles: Record<string, string> = {
              ...(agent.instructionsFiles ?? {}),
              [documentKey]: agent.instructions ?? '',
            }
            return updateSessionAgent(sessionId, detailItem.id, {
              name: agent.name,
              role: agent.role ?? 'general',
              title: agent.title,
              description: agent.description,
              adapterType: agent.adapterType,
              model: agent.model,
              profileImage: agent.profileImage,
              skills: agent.skills,
              entryDocumentKey: documentKey,
              instructionsFiles: mergedFiles,
            })
              .then((profile) => {
                // 서브에이전트 설정이 수정됐으므로 캐시 무효화 — 다음 패널 진입 때 fresh 받음.
                useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
                // 서버 응답으로 정식 값을 한 번 더 적용한다. 단, 서버가 일부 필드를 null/빈 값으로
                // 내려주는 경우 사용자가 방금 입력한 옵티미스틱 값(특히 호칭·이름)을 덮어쓰지 않도록
                // 보호한다.
                const serverAgent = agentProfileToAgent(profile)
                const savedAgent = {
                  ...serverAgent,
                  name: serverAgent.name?.trim() ? serverAgent.name : optimisticAgent.name,
                  title: serverAgent.title?.trim() ? serverAgent.title : optimisticAgent.title,
                  description:
                    serverAgent.description !== undefined && serverAgent.description !== ''
                      ? serverAgent.description
                      : optimisticAgent.description,
                }
                updateAgentPanelInSession(sessionId, detailItem.id, savedAgent)
                return savedAgent
              })
              .catch((error) => {
                // 실패 시 옵티미스틱 패치를 이전 상태로 롤백
                updateAgentPanelInSession(sessionId, detailItem.id, previousAgent)
                setLoadError(
                  error instanceof Error ? error.message : '에이전트를 저장하지 못했습니다.',
                )
              })
          }}
          onTabChange={(tab) => openDetailTab(detailItem.id, tab)}
          requestedTab={searchParams.get('subAgentTab')}
          reservedNames={agentPanels
            .filter((item) => item.id !== detailItem.id)
            .map((item) => item.agent.name)}
          sessionId={sessionId}
        />
      </SubAgentsPanelShell>
    )
  }

  return (
    <SubAgentsPanelShell title="에이전트" description="세션 에이전트 설정">
      {loadError && (
        <p className="text-destructive border-destructive/30 mb-3 rounded-md border px-3 py-2 text-xs">
          {loadError}
        </p>
      )}
      <SubAgentList agentPanels={agentPanels} onCreate={openCreateDraft} onOpen={openDetail} />
      <SubAgentCreateDialog
        open={createDialogOpen}
        onOpenChange={(open) => {
          if (open) {
            setSearchParams({ create: '1' })
          } else {
            resetDraft()
          }
        }}
        onAskCeo={() => {
          void createDefaultSessionAgents(sessionId)
            .then((profiles) => {
              // 기본 에이전트들이 새로 생성됐으므로 캐시 무효화.
              useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
              setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
              resetDraft()
            })
            .catch((error) => {
              setLoadError(
                error instanceof Error ? error.message : '기본 에이전트를 만들지 못했습니다.',
              )
            })
        }}
        onPickAdapter={(adapterType) => {
          setSearchParams({ new: '1', adapterType })
        }}
        onPickTemplate={(templateId) => {
          void createSessionAgentFromTemplate(sessionId, templateId)
            .then(() => {
              // 템플릿 기반 에이전트가 생성됐으므로 캐시 무효화 후 다시 받는다.
              useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
              return useAgentCacheStore.getState().fetchSessionAgents(sessionId)
            })
            .then((profiles) => {
              setAgentPanelsForSession(sessionId, agentProfilesToPanelItems(profiles))
              resetDraft()
            })
            .catch((error) => {
              setLoadError(error instanceof Error ? error.message : '에이전트를 만들지 못했습니다.')
            })
        }}
        templates={templates}
      />
    </SubAgentsPanelShell>
  )
}
