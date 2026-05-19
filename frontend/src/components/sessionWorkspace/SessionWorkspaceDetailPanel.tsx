import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { Activity, BarChart3, Check, FileText, Loader2, Play } from 'lucide-react'
import { PageTabBar } from '@/components/PageTabBar'
import { Button } from '@/components/ui/button'
import { HelpHint } from '@/components/ui/help-hint'
import { Tabs } from '@/components/ui/tabs'
import {
  AgentDetailHeader,
  AgentAdapterTypeDropdown,
  AgentRunActivityChart,
  AgentRunStatusChart,
  AgentRunSuccessRateChart,
  AgentUsageActivityChart,
  AgentConfigurationPanel,
  AgentDashboardPanel,
  AgentInstructionsBundlePanel,
  AgentInstructionsPanel,
  AgentModelDropdown,
  AgentSectionCard,
  AgentSkillsLibraryPanel,
  AgentSkillsPanel,
} from '@/components/sessionWorkspace/AgentDetailPanels'
import { AgentRunsPanel } from '@/components/sessionWorkspace/agentRuns/AgentRunsPanel'
import type { AgentRunItemData } from '@/components/sessionWorkspace/agentRuns/types'
import { AgentSkillDetailDialog } from '@/components/sessionWorkspace/AgentSkillDetailDialog'
import {
  type AgentRunUsageSummary,
  buildAgentRunUsageMap,
  buildAgentUsageSummaryItems,
  buildAgentUsageRows,
  buildUsageSummaryFromRecords,
  filterUsageRecordsByTaskRunIds,
  formatAgentRunCostUsage,
  formatAgentRunTokenUsage,
} from '@/components/sessionWorkspace/agentUsageDisplay'
import { WorkBoardPanel, WorkflowPanel } from '@/components/sessionWorkspace/work/board'
import { SubAgentsPanel } from '@/components/sessionWorkspace/subAgents'
import {
  SUB_AGENT_ADAPTER_OPTIONS,
  getDefaultModel,
  normalizeSubAgentAdapterType,
  type SubAgentAdapterType,
} from '@/components/sessionWorkspace/subAgents/subAgentConfigOptions'
import { getTime } from '@/components/taskRuns/stepRunActivityPanel/activityPanelText'
import { getCommandUsage, type CommandUsageRecord } from '@/apis/aiCommandUsage'
import {
  deleteCustomSkill,
  getUserSkillDetail,
  updateSessionAgent,
  type AgentProfile,
  type SkillCatalogDetail,
  type SkillCatalogItem,
} from '@/apis/agents'
import { useAgentCacheStore } from '@/store/useAgentCacheStore'
import {
  getCachedMainAgentProfile,
  getCachedUsageRecords,
  setCachedMainAgentProfile,
  setCachedUsageRecords,
} from '@/components/sessionWorkspace/sessionWorkspaceDashboardCache'
import { useAgentVisualizationStore } from '@/store/useAgentVisualizationStore'
import { useAiRealtimeStore } from '@/store/useAiRealtimeStore'
import { useChatStore } from '@/store/useChatStore'
import { useSessionStore } from '@/store/useSessionStore'
import { useTaskRunStore } from '@/store/useTaskRunStore'
import type { JsonObject, RawTaskEventPayload } from '@/realtime/aiRealtimeTypes'
import type {
  AiModelOption,
  AiSessionSettingsPatch,
  ChatMessageView,
  RawAiSession,
} from '@/types/aiChat'
import type { RawTaskRun, TaskRunAgentRef } from '@/types/taskRuns'
import { isInternalStepAnchorEvent, toTaskRunSummaryView } from '@/utils/taskRunStatusView'
import {
  getModelFamilies,
  getModelOptions,
  getString,
  groupModels,
  inferModelFamily,
  setOptionalUiString,
  shallowJsonEqual,
  toJsonObject,
} from './sessionWorkspaceUtils'
import type { ModelFamily } from './sessionWorkspaceUtils'
import type { WorkspacePanelId } from './sessionWorkspaceTypes'

interface SessionWorkspaceDetailPanelProps {
  activePanel: WorkspacePanelId | null
  sessionId: string
  session: RawAiSession | null
}

const EMPTY_MESSAGES: never[] = []

export function SessionWorkspaceDetailPanel({
  activePanel,
  sessionId,
  session,
}: SessionWorkspaceDetailPanelProps) {
  // 시각화 패널은 SessionShell 이 항상 백그라운드로 마운트한다.
  // 여기서는 시각화 이외 패널만 렌더한다.
  if (activePanel === null || activePanel === 'visualization') {
    return null
  }

  if (activePanel === 'subAgents') {
    return <SubAgentsPanel sessionId={sessionId} />
  }
  if (activePanel === 'issueBoard') {
    return <WorkBoardPanel sessionId={sessionId} />
  }
  if (activePanel === 'workflow') {
    return <WorkflowPanel sessionId={sessionId} />
  }
  if (session === null) {
    const title = activePanel === 'ceo' ? '팀장 에이전트' : '세션'
    return (
      <WorkspacePageShell title={title} eyebrow="작업면">
        <p className="text-muted-foreground text-sm">세션 정보를 불러오는 중입니다.</p>
      </WorkspacePageShell>
    )
  }
  if (activePanel === 'ceo') {
    return <MainAgentPage key={session.session_id} session={session} />
  }
  return null
}

function MainAgentPage({ session }: { session: RawAiSession }) {
  const authenticatedReady = useAiRealtimeStore((state) => state.authenticatedReady)
  const commandClient = useAiRealtimeStore((state) => state.commandClient)
  const messages = useChatStore(
    (state) => state.messagesBySessionId[session.session_id] ?? EMPTY_MESSAGES,
  )
  const fetchMessages = useChatStore((state) => state.fetchMessages)
  const updateSession = useChatStore((state) => state.updateSession)
  const updateSessionSettings = useChatStore((state) => state.updateSessionSettings)
  const fetchModelOptions = useChatStore((state) => state.fetchModelOptions)
  const cachedModelOptions = useChatStore((state) => state.modelOptions)
  const taskRunsById = useTaskRunStore((state) => state.taskRunsById)
  const eventsByTaskRunId = useTaskRunStore((state) => state.eventsByTaskRunId)
  const fetchActiveTaskRuns = useTaskRunStore((state) => state.fetchActiveTaskRuns)
  const updateAgentInfo = useAgentVisualizationStore((state) => state.updateAgentInfo)
  const setMainAgentNameDraft = useSessionStore((state) => state.setMainAgentNameDraft)
  const [searchParams, setSearchParams] = useSearchParams()
  const [mainAgentProfile, setMainAgentProfile] = useState<AgentProfile | null>(() =>
    getCachedMainAgentProfile(session.session_id),
  )

  const metadata = useMemo(() => toJsonObject(session.metadata), [session.metadata])
  const uiMetadata = useMemo(() => toJsonObject(metadata.ui), [metadata])
  const mainAgentConfig = useMemo(
    () => toJsonObject(mainAgentProfile?.configSnapshot),
    [mainAgentProfile],
  )
  const mainAgentInstructionFiles = useMemo(
    () => getInstructionFilesFromDocuments(mainAgentConfig.documents),
    [mainAgentConfig.documents],
  )
  const settings = useMemo(() => toJsonObject(session.settings), [session.settings])
  const sessionId = session.session_id
  const currentAgentName =
    getString(uiMetadata, 'agentName') ?? getString(mainAgentConfig, 'name') ?? ''
  const currentCallName =
    getString(uiMetadata, 'callName') ?? getString(mainAgentConfig, 'title') ?? ''
  const currentCapabilities =
    getString(uiMetadata, 'agentCapabilities') ?? getString(mainAgentConfig, 'description') ?? ''
  const currentSkillIds = normalizeMainAgentSkillIds(
    uiMetadata.agentSkills ?? mainAgentConfig.skills,
  )
  const currentInstructionsEntryFile =
    getString(uiMetadata, 'instructionsEntryFile') ??
    getString(mainAgentConfig, 'entryDocumentKey') ??
    'AGENTS.md'
  const currentInstructionsFiles = {
    ...mainAgentInstructionFiles,
    ...getInstructionsFiles(uiMetadata.instructionsFiles),
  }
  const currentSettingsPrompt =
    getString(settings, 'systemPrompt') ?? getString(settings, 'system_prompt') ?? ''
  const currentPersona =
    currentSettingsPrompt.trim() !== ''
      ? currentSettingsPrompt
      : (currentInstructionsFiles[currentInstructionsEntryFile] ?? '')
  const currentInstructionsMode =
    getString(uiMetadata, 'instructionsMode') === 'external' ? 'external' : 'managed'
  const currentInstructionsRootPath = getString(uiMetadata, 'instructionsRootPath') ?? ''
  const currentModel = getString(mainAgentConfig, 'model') ?? getString(settings, 'model') ?? ''
  const currentProvider = inferProviderFromModel(
    currentModel,
    getString(mainAgentConfig, 'adapterType') ??
      getString(settings, 'provider') ??
      getString(settings, 'providerName'),
  )
  const currentDelegationPolicy = toJsonObject(settings.delegationPolicy)
  const currentCanDelegate = currentDelegationPolicy.canDelegate === true
  const currentProfileImage = normalizeAgentProfileImage(
    getString(uiMetadata, 'agentProfileImage') ??
      getString(mainAgentConfig, 'profileImage') ??
      undefined,
  )
  const [agentName, setAgentName] = useState(currentAgentName)
  const [callName, setCallName] = useState(currentCallName)
  const [capabilities, setCapabilities] = useState(currentCapabilities)
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>(currentSkillIds)
  const [persona, setPersona] = useState(currentPersona)
  const [instructionsEntryFile, setInstructionsEntryFile] = useState(currentInstructionsEntryFile)
  const [instructionsFiles, setInstructionsFiles] = useState(currentInstructionsFiles)
  const [instructionsMode, setInstructionsMode] = useState<'managed' | 'external'>(
    currentInstructionsMode,
  )
  const [instructionsRootPath, setInstructionsRootPath] = useState(currentInstructionsRootPath)
  const [selectedProvider, setSelectedProvider] = useState<SubAgentAdapterType>(currentProvider)
  const [selectedModel, setSelectedModel] = useState(currentModel)
  const [canDelegate, setCanDelegate] = useState(currentCanDelegate)
  const [profileImage, setProfileImage] = useState(currentProfileImage)
  const [modelOptionsLoading, setModelOptionsLoading] = useState(
    authenticatedReady && cachedModelOptions === null,
  )
  const [modelOptionsError, setModelOptionsError] = useState<string | null>(null)
  const [modelOptions, setModelOptions] = useState(() =>
    getModelOptions(cachedModelOptions?.models),
  )
  const [selectedFamily, setSelectedFamily] = useState<ModelFamily>(inferModelFamily(currentModel))
  const [providerBaseline, setProviderBaseline] = useState<SubAgentAdapterType>(currentProvider)
  const [modelBaseline, setModelBaseline] = useState(currentModel)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [usageRecords, setUsageRecords] = useState<CommandUsageRecord[]>(
    () => getCachedUsageRecords(session.session_id) ?? [],
  )
  const [usageError, setUsageError] = useState<string | null>(null)
  const [skillCatalog, setSkillCatalog] = useState<SkillCatalogItem[]>([])
  const [skillCatalogError, setSkillCatalogError] = useState<string | null>(null)
  const [skillDetail, setSkillDetail] = useState<SkillCatalogDetail | null>(null)
  const [skillDetailOpen, setSkillDetailOpen] = useState(false)
  const [skillDetailLoading, setSkillDetailLoading] = useState(false)

  const providerModelOptions = useMemo(
    () => getProviderModelOptions(modelOptions, selectedProvider),
    [modelOptions, selectedProvider],
  )
  const modelGroups = useMemo(() => groupModels(providerModelOptions), [providerModelOptions])
  const modelFamilies = useMemo(() => getModelFamilies(modelGroups), [modelGroups])
  const effectiveSelectedFamily = modelFamilies.some((family) => family.id === selectedFamily)
    ? selectedFamily
    : (modelFamilies[0]?.id ?? 'gpt')
  const visibleModels = modelGroups[effectiveSelectedFamily]
  const visibleModelOptions = visibleModels.map((model) => ({
    value: model.id,
    label: model.label,
    description: model.provider ?? effectiveSelectedFamily,
  }))
  const displayName = agentName.trim() || '팀장 에이전트'
  const displayRole = callName.trim() || '팀장 에이전트'
  const activeTab = getMainAgentTab(searchParams.get('agentTab'))
  const skillCatalogReady = skillCatalog.length > 0
  const knownSkillIds = new Set(skillCatalog.map((skill) => skill.skillId))
  const selectedKnownSkillIds = skillCatalogReady
    ? selectedSkillIds.filter((skillId) => knownSkillIds.has(skillId))
    : selectedSkillIds
  const missingSkillIds = skillCatalogReady
    ? selectedSkillIds.filter((skillId) => !knownSkillIds.has(skillId))
    : []
  const orderedSkillCatalog = useMemo(
    () => orderSkillCatalogBySelectedIds(skillCatalog, selectedKnownSkillIds),
    [skillCatalog, selectedKnownSkillIds],
  )
  const isDirty =
    agentName.trim() !== currentAgentName ||
    callName.trim() !== currentCallName ||
    capabilities.trim() !== currentCapabilities ||
    !stringArraysEqual(selectedSkillIds, currentSkillIds) ||
    persona.trim() !== currentPersona ||
    instructionsEntryFile.trim() !== currentInstructionsEntryFile ||
    !shallowStringRecordEqual(instructionsFiles, currentInstructionsFiles) ||
    instructionsMode !== currentInstructionsMode ||
    instructionsRootPath.trim() !== currentInstructionsRootPath ||
    selectedProvider !== providerBaseline ||
    selectedModel !== modelBaseline ||
    profileImage !== currentProfileImage ||
    canDelegate !== currentCanDelegate
  const showConfigActionBar =
    (activeTab === 'configuration' || activeTab === 'instructions' || activeTab === 'skills') &&
    (isDirty || saving)
  const sessionRuns = useMemo(
    () => buildSessionRunItems(session, messages, taskRunsById, eventsByTaskRunId, usageRecords),
    [eventsByTaskRunId, messages, session, taskRunsById, usageRecords],
  )
  const mainAgentTaskRunIds = useMemo(
    () => buildMainAgentTaskRunIds(session, messages, taskRunsById, mainAgentProfile?.profileId),
    [mainAgentProfile?.profileId, messages, session, taskRunsById],
  )
  const mainAgentUsageSummary = useMemo(
    () =>
      buildUsageSummaryFromRecords(
        filterUsageRecordsByTaskRunIds(usageRecords, mainAgentTaskRunIds),
      ),
    [mainAgentTaskRunIds, usageRecords],
  )
  const mainAgentUsageRecords = useMemo(
    () => filterUsageRecordsByTaskRunIds(usageRecords, mainAgentTaskRunIds),
    [mainAgentTaskRunIds, usageRecords],
  )
  const usageItems = useMemo(
    () => buildAgentUsageSummaryItems(mainAgentUsageSummary, false, usageError),
    [mainAgentUsageSummary, usageError],
  )
  const usageRows = useMemo(
    () => buildAgentUsageRows(mainAgentUsageRecords),
    [mainAgentUsageRecords],
  )

  useEffect(() => {
    if (!authenticatedReady || commandClient === null || sessionId.startsWith('pending_session_')) {
      return
    }

    let cancelled = false
    void Promise.all([fetchMessages(sessionId), fetchActiveTaskRuns(sessionId)]).catch((error) => {
      if (cancelled) return
      console.error(error)
    })

    return () => {
      cancelled = true
    }
  }, [authenticatedReady, commandClient, fetchActiveTaskRuns, fetchMessages, sessionId])

  useEffect(() => {
    if (!authenticatedReady || sessionId.startsWith('pending_session_')) {
      return
    }

    let cancelled = false
    void useAgentCacheStore
      .getState()
      .fetchSessionMainAgent(sessionId)
      .then((profile) => {
        if (cancelled) return
        setMainAgentProfile(profile)
        setCachedMainAgentProfile(sessionId, profile)
        const config = toJsonObject(profile.configSnapshot)
        const files = getInstructionFilesFromDocuments(config.documents)
        setAgentName(
          getString(uiMetadata, 'agentName') ?? getString(config, 'name') ?? '팀장 에이전트',
        )
        setCallName(
          getString(uiMetadata, 'callName') ?? getString(config, 'title') ?? '팀장 에이전트',
        )
        setCapabilities(
          getString(uiMetadata, 'agentCapabilities') ?? getString(config, 'description') ?? '',
        )
        setSelectedSkillIds(normalizeMainAgentSkillIds(uiMetadata.agentSkills ?? config.skills))
        const entryDocumentKey = getString(config, 'entryDocumentKey') ?? 'AGENTS.md'
        const nextEntryFile = getString(uiMetadata, 'instructionsEntryFile') ?? entryDocumentKey
        const nextFiles = {
          ...files,
          ...getInstructionsFiles(uiMetadata.instructionsFiles),
        }
        setInstructionsEntryFile(nextEntryFile)
        setInstructionsFiles(nextFiles)
        setPersona(
          currentSettingsPrompt.trim() !== ''
            ? currentSettingsPrompt
            : (nextFiles[nextEntryFile] ?? ''),
        )
        setInstructionsMode(
          getString(uiMetadata, 'instructionsMode') === 'external' ? 'external' : 'managed',
        )
        setInstructionsRootPath(getString(uiMetadata, 'instructionsRootPath') ?? '')
        const profileModel = getString(config, 'model') ?? ''
        const profileProvider = inferProviderFromModel(
          profileModel,
          getString(config, 'adapterType'),
        )
        setSelectedProvider(profileProvider)
        setProviderBaseline(profileProvider)
        setSelectedModel(profileModel)
        setModelBaseline(profileModel)
        setSelectedFamily(inferModelFamily(profileModel))
        setProfileImage(
          normalizeAgentProfileImage(
            getString(uiMetadata, 'agentProfileImage') ??
              getString(config, 'profileImage') ??
              undefined,
          ),
        )
      })
      .catch(() => {
        if (!cancelled) setMainAgentProfile(null)
      })

    return () => {
      cancelled = true
    }
  }, [authenticatedReady, currentSettingsPrompt, sessionId, uiMetadata])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null) {
      return
    }

    let cancelled = false
    void useAgentCacheStore
      .getState()
      .fetchUserSkills()
      .then((items) => {
        if (cancelled) return
        setSkillCatalog(items)
        setSkillCatalogError(null)
      })
      .catch(() => {
        if (!cancelled) setSkillCatalogError('스킬 목록을 불러오지 못했습니다.')
      })

    return () => {
      cancelled = true
    }
  }, [authenticatedReady, commandClient])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null || sessionId.startsWith('pending_session_')) {
      return
    }

    let active = true
    void getCommandUsage({ sessionId })
      .then((result) => {
        if (!active) return
        setUsageError(null)
        setUsageRecords(result.records)
        setCachedUsageRecords(sessionId, result.records)
      })
      .catch(() => {
        if (!active) return
        setUsageError('사용량을 불러오지 못했습니다.')
      })

    return () => {
      active = false
    }
  }, [authenticatedReady, commandClient, sessionId])

  useEffect(() => {
    if (!authenticatedReady || commandClient === null) {
      return
    }

    let active = true

    void fetchModelOptions(sessionId)
      .then((options) => {
        if (!active) return
        const providerModels =
          options.providers?.flatMap((provider) => provider.models) ?? options.models
        const nextModels = getModelOptions(providerModels)
        setModelOptions(nextModels)
        setModelOptionsLoading(false)
        if (currentModel === '' && typeof options.model === 'string' && options.model.trim()) {
          setSelectedProvider(inferProviderFromModel(options.model))
          setProviderBaseline(inferProviderFromModel(options.model))
          setSelectedModel(options.model)
          setModelBaseline(options.model)
          setSelectedFamily(inferModelFamily(options.model))
        }
      })
      .catch((error) => {
        if (!active) return
        setModelOptionsError(
          error instanceof Error ? error.message : '모델 목록 조회에 실패했습니다.',
        )
        setModelOptionsLoading(false)
      })

    return () => {
      active = false
    }
  }, [authenticatedReady, commandClient, currentModel, fetchModelOptions, sessionId])

  useEffect(() => {
    return () => {
      setMainAgentNameDraft(sessionId, null)
    }
  }, [sessionId, setMainAgentNameDraft])

  useEffect(() => {
    if (!showConfigActionBar) return

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [showConfigActionBar])

  const markDirty = () => {
    setSaved(false)
    setSaveError(null)
  }

  const selectTab = (tab: MainAgentTab) => {
    const nextParams = new URLSearchParams(searchParams)
    if (tab === 'dashboard') {
      nextParams.delete('agentTab')
    } else {
      nextParams.set('agentTab', tab)
    }
    setSearchParams(nextParams)
  }

  const resetDraft = () => {
    setAgentName(currentAgentName)
    setMainAgentNameDraft(sessionId, null)
    setCallName(currentCallName)
    setCapabilities(currentCapabilities)
    setSelectedSkillIds(currentSkillIds)
    setPersona(currentPersona)
    setInstructionsEntryFile(currentInstructionsEntryFile)
    setInstructionsFiles(currentInstructionsFiles)
    setInstructionsMode(currentInstructionsMode)
    setInstructionsRootPath(currentInstructionsRootPath)
    setSelectedProvider(providerBaseline)
    setSelectedModel(modelBaseline)
    setSelectedFamily(inferModelFamily(modelBaseline))
    setCanDelegate(currentCanDelegate)
    setProfileImage(currentProfileImage)
    setSaveError(null)
    setSaved(false)
  }

  const openSkillDetail = (skillId: string) => {
    setSkillDetailOpen(true)
    setSkillDetailLoading(true)
    void getUserSkillDetail(skillId)
      .then((detail) => {
        setSkillDetail(detail)
      })
      .catch(() => {
        setSkillCatalogError('스킬 상세를 불러오지 못했습니다.')
      })
      .finally(() => setSkillDetailLoading(false))
  }

  const handleSkillDeleted = async (detail: SkillCatalogDetail) => {
    await deleteCustomSkill(detail.skillId)
    setSkillCatalog((current) => current.filter((skill) => skill.skillId !== detail.skillId))
    setSelectedSkillIds((current) => current.filter((skillId) => skillId !== detail.skillId))
    setSkillDetail(null)
    useAgentCacheStore.getState().invalidateUserSkills()
    markDirty()
  }

  const handleSave = async () => {
    const nextUiMetadata: JsonObject = { ...uiMetadata }
    setOptionalUiString(nextUiMetadata, 'agentName', agentName)
    setOptionalUiString(nextUiMetadata, 'callName', callName)
    setOptionalUiString(nextUiMetadata, 'agentCapabilities', capabilities)
    if (selectedSkillIds.length === 0) {
      delete nextUiMetadata.agentSkills
    } else {
      nextUiMetadata.agentSkills = selectedSkillIds
    }
    setOptionalUiString(nextUiMetadata, 'agentProfileImage', profileImage)
    setOptionalUiString(nextUiMetadata, 'instructionsEntryFile', instructionsEntryFile)
    if (Object.keys(instructionsFiles).length === 0) {
      delete nextUiMetadata.instructionsFiles
    } else {
      nextUiMetadata.instructionsFiles = instructionsFiles
    }
    setOptionalUiString(nextUiMetadata, 'instructionsMode', instructionsMode)
    setOptionalUiString(nextUiMetadata, 'instructionsRootPath', instructionsRootPath)

    const settingsPatch: AiSessionSettingsPatch = {}
    const nextPersona = persona.trim()
    if (mainAgentProfile === null && nextPersona !== currentPersona) {
      settingsPatch.systemPrompt = nextPersona
    }
    if (mainAgentProfile === null && selectedModel !== '' && selectedModel !== modelBaseline) {
      settingsPatch.model = selectedModel
    }
    if (canDelegate !== currentCanDelegate) {
      settingsPatch.delegationPolicy = { canDelegate }
    }

    setSaving(true)
    setSaveError(null)
    setSaved(false)

    try {
      if (!shallowJsonEqual(uiMetadata, nextUiMetadata)) {
        await updateSession({ sessionId, metadataPatch: { ui: nextUiMetadata } })
      }
      if (Object.keys(settingsPatch).length > 0) {
        await updateSessionSettings({ sessionId, settingsPatch })
      }
      if (mainAgentProfile !== null) {
        const documentKey = instructionsEntryFile.trim() || 'AGENTS.md'
        const nextInstructionsFiles = {
          ...instructionsFiles,
          [documentKey]: persona.trim(),
        }
        const profile = await updateSessionAgent(sessionId, mainAgentProfile.profileId, {
          name: agentName.trim() || '팀장 에이전트',
          role: 'ceo',
          title: callName.trim() || '팀장 에이전트',
          description: capabilities.trim(),
          adapterType: selectedProvider,
          model: selectedModel,
          profileImage,
          skills: selectedKnownSkillIds,
          entryDocumentKey: documentKey,
          instructionsFiles: nextInstructionsFiles,
        })
        setMainAgentProfile(profile)
        // 메인 에이전트 정보가 수정되었으므로 캐시 무효화.
        // 시각화/사이드바 등에서 stale 정보 표시되는 것을 막는다.
        useAgentCacheStore.getState().invalidateSessionMainAgent(sessionId)
        useAgentCacheStore.getState().invalidateSessionAgents(sessionId)
        const savedProvider = inferProviderFromModel(
          profile.model,
          profile.adapterType ?? getString(toJsonObject(profile.configSnapshot), 'adapterType'),
        )
        setSelectedProvider(savedProvider)
        setProviderBaseline(savedProvider)
      } else {
        setProviderBaseline(selectedProvider)
      }
      if (settingsPatch.model !== undefined || mainAgentProfile !== null) {
        setModelBaseline(selectedModel)
      }
      setAgentName(agentName.trim())
      setCallName(callName.trim())
      setCapabilities(capabilities.trim())
      setPersona(nextPersona)
      setInstructionsEntryFile(instructionsEntryFile.trim() || 'AGENTS.md')
      setInstructionsRootPath(instructionsRootPath.trim())
      updateAgentInfo('ceo', {
        name: agentName.trim() || '팀장 에이전트',
        ...(profileImage ? { profileImage } : {}),
      })
      setMainAgentNameDraft(sessionId, null)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 1400)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '메인 에이전트 저장에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <WorkspacePageShell title="팀장 에이전트" eyebrow="팀장 에이전트" hideHeader>
      <div className={`space-y-6 ${showConfigActionBar ? 'pb-24 sm:pb-0' : ''}`}>
        <MainAgentHeader
          callName={displayRole}
          onConfigure={() => selectTab('configuration')}
          model={selectedModel}
          name={displayName}
          profileImage={profileImage}
          saved={saved}
          saving={saving}
        />

        <Tabs value={activeTab} onValueChange={(value) => selectTab(value as MainAgentTab)}>
          <PageTabBar
            align="start"
            items={MAIN_AGENT_TABS}
            value={activeTab}
            onValueChange={(value) => selectTab(value as MainAgentTab)}
          />
        </Tabs>

        {activeTab === 'dashboard' && (
          <AgentDashboardPanel
            costs={usageItems}
            latestRun={sessionRuns[0] ?? null}
            metrics={[
              {
                icon: Activity,
                label: '실행 활동',
                value: `${sessionRuns.length}회`,
                description: '최근 14일',
                chart: <AgentRunActivityChart runs={sessionRuns} />,
              },
              {
                icon: FileText,
                label: '담당 작업',
                value: `${mainAgentTaskRunIds.length}개`,
                description: '최근 14일',
                chart: <AgentRunStatusChart runs={sessionRuns} />,
              },
              {
                icon: BarChart3,
                label: '토큰 사용',
                value: mainAgentUsageSummary.totalTokens.toLocaleString('ko-KR'),
                description: '최근 14일',
                chart: <AgentUsageActivityChart records={mainAgentUsageRecords} />,
              },
              {
                icon: Play,
                label: '성공률',
                value: getRunSuccessRateLabel(sessionRuns),
                description: '최근 14일',
                chart: <AgentRunSuccessRateChart runs={sessionRuns} />,
              },
            ]}
            recentTitle="최근 작업"
            recentEmptyText="최근 작업이 없습니다."
            recentItems={sessionRuns.map((run) => ({
              label: run.summary ?? run.id,
              onSelect: () => selectTab('runs'),
              value: `${formatSessionRunStatus(run.status)}${run.createdAt ? ` · ${run.createdAt}` : ''}`,
            }))}
            onLatestRunOpen={() => selectTab('runs')}
            onRecentOpen={() => selectTab('runs')}
            usageRows={usageRows}
          />
        )}

        {activeTab === 'skills' && (
          <AgentSkillsPanel>
            <AgentSkillsLibraryPanel
              adapterLabel="세션"
              applicationLabel="에이전트 실행 시 적용"
              rows={orderedSkillCatalog.map((skill) => ({
                key: skill.skillId,
                name: skill.displayName,
                description: skill.description,
                checked: selectedKnownSkillIds.includes(skill.skillId),
                disabled: !skill.enabled,
                detail: skill.enabled
                  ? undefined
                  : '사용자 설정에서 꺼져 있어 이 에이전트에 적용할 수 없습니다.',
              }))}
              missingSkills={missingSkillIds}
              selectedCount={selectedKnownSkillIds.length}
              warnings={skillCatalogError ? [skillCatalogError] : []}
              onSkillCreated={(skill) => {
                setSkillCatalog((current) =>
                  current.some((item) => item.skillId === skill.skillId)
                    ? current
                    : [...current, skill],
                )
                setSelectedSkillIds((current) =>
                  current.includes(skill.skillId) ? current : [...current, skill.skillId],
                )
                useAgentCacheStore.getState().invalidateUserSkills()
                markDirty()
              }}
              onSkillOpen={openSkillDetail}
              onSkillReorder={(orderedSkillIds) => {
                setSelectedSkillIds([...orderedSkillIds, ...missingSkillIds])
                markDirty()
              }}
              onSkillToggle={(skillId, checked) => {
                setSelectedSkillIds((current) =>
                  checked
                    ? Array.from(new Set([...current, skillId]))
                    : current.filter((item) => item !== skillId),
                )
                markDirty()
              }}
            />
          </AgentSkillsPanel>
        )}

        {activeTab === 'instructions' && (
          <AgentInstructionsPanel>
            <AgentInstructionsBundlePanel
              content={persona}
              entryFile={instructionsEntryFile}
              files={instructionsFiles}
              mode={instructionsMode}
              rootPath={instructionsRootPath}
              onContentChange={(value) => {
                setPersona(value)
                markDirty()
              }}
              onEntryFileChange={(value) => {
                setInstructionsEntryFile(value)
                markDirty()
              }}
              onFilesChange={(value) => {
                setInstructionsFiles(value)
                markDirty()
              }}
              onModeChange={(value) => {
                setInstructionsMode(value)
                markDirty()
              }}
              onRootPathChange={(value) => {
                setInstructionsRootPath(value)
                markDirty()
              }}
            />
          </AgentInstructionsPanel>
        )}

        {activeTab === 'configuration' && (
          <AgentConfigurationPanel>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.82fr)]">
              <div className="space-y-4">
                <AgentSectionCard title="프로필">
                  <div className="grid gap-4 sm:grid-cols-[14rem_minmax(0,1fr)]">
                    <div aria-label="프로필 이미지">
                      <AgentImageStepper profileImage={profileImage} />
                    </div>
                    <div className="space-y-3">
                      <Field
                        label="이름"
                        hint={
                          <>
                            <p className="text-foreground font-medium">이름</p>
                            <p>
                              사이드바·채팅 화면 등에서{' '}
                              <span className="text-foreground">에이전트를 부르는 표시명</span>
                              이에요.
                            </p>
                            <p>여기서 바꾸면 모든 화면에 같이 반영됩니다.</p>
                            <p>예) “기획 팀장”, “마케팅 리더”.</p>
                          </>
                        }
                      >
                        <DraftInput
                          onChange={(value) => {
                            setAgentName(value)
                            setMainAgentNameDraft(sessionId, value)
                            markDirty()
                          }}
                          placeholder="예: 기획 도우미"
                          value={agentName}
                        />
                      </Field>
                      <Field
                        label="호칭"
                        hint={
                          <>
                            <p className="text-foreground font-medium">호칭</p>
                            <p>
                              대화에서 사용할 <span className="text-foreground">말투·직함</span>
                              이에요.
                            </p>
                            <p>
                              에이전트가 자기를 어떻게 불러달라고 할지, 답변할 때 어떤 호칭을 쓸지
                              정할 때 참고합니다.
                            </p>
                            <p>예) “팀장님”, “기획자”, “사용자님”.</p>
                          </>
                        }
                      >
                        <DraftInput
                          onChange={(value) => {
                            setCallName(value)
                            markDirty()
                          }}
                          placeholder="예: 팀장님, 사용자님"
                          value={callName}
                        />
                      </Field>
                      <Field
                        label="할 수 있는 일"
                        hint={
                          <>
                            <p className="text-foreground font-medium">할 수 있는 일</p>
                            <p>
                              이 에이전트의{' '}
                              <span className="text-foreground">담당 업무 한 줄 설명</span>이에요.
                            </p>
                            <p>
                              팀원 에이전트들과 시스템이 “이 팀장에게 어떤 일을 맡길 수 있는지”
                              판단할 때 참고합니다. 너무 길게보단 핵심 업무를 짧고 분명하게.
                            </p>
                            <p>예) “회의록 요약, 일정 정리, 신규 기획 초안 작성”.</p>
                          </>
                        }
                      >
                        <textarea
                          value={capabilities}
                          onChange={(event) => {
                            setCapabilities(event.target.value)
                            markDirty()
                          }}
                          rows={3}
                          placeholder="이 에이전트가 할 수 있는 일을 적어주세요."
                          className={`${inputClass} min-h-[72px] resize-y leading-6`}
                        />
                      </Field>
                    </div>
                  </div>
                </AgentSectionCard>
              </div>
              <div className="space-y-4">
                <AgentSectionCard title="모델">
                  <Field label="공급자">
                    <AgentAdapterTypeDropdown
                      value={selectedProvider}
                      options={SUB_AGENT_ADAPTER_OPTIONS.map((option) => ({
                        value: option.id,
                        label: option.label,
                        description: option.description,
                      }))}
                      onChange={(value) => {
                        const nextProvider = normalizeSubAgentAdapterType(value)
                        const nextModels = getProviderModelOptions(modelOptions, nextProvider)
                        const nextModel = nextModels[0]?.id ?? getDefaultModel(nextProvider)
                        setSelectedProvider(nextProvider)
                        setSelectedModel(nextModel)
                        setSelectedFamily(inferModelFamily(nextModel))
                        markDirty()
                      }}
                    />
                  </Field>
                  <Field
                    label="모델"
                    hint={
                      <>
                        <p className="text-foreground font-medium">모델</p>
                        <p>
                          에이전트의 <span className="text-foreground">두뇌</span>를 고르는
                          항목이에요.
                        </p>
                        <p>모델마다 속도·정확도·비용이 다릅니다.</p>
                        <p>잘 모르겠으면 기본값을 그대로 두세요.</p>
                      </>
                    }
                  >
                    {authenticatedReady && modelOptionsLoading && (
                      <span className="text-muted-foreground mb-1 inline-flex items-center gap-1.5 text-xs">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        조회 중
                      </span>
                    )}
                    {authenticatedReady && modelOptionsError ? (
                      <p className="text-destructive text-sm">
                        {formatServerError(modelOptionsError)}
                      </p>
                    ) : (
                      <AgentModelDropdown
                        value={selectedModel}
                        options={visibleModelOptions}
                        onChange={(modelId) => {
                          setSelectedModel(modelId)
                          markDirty()
                        }}
                        allowDefault
                      />
                    )}
                  </Field>
                </AgentSectionCard>
                <AgentSectionCard title="실행 규칙">
                  <ToggleRow
                    checked={canDelegate}
                    description="세션 안에서 필요한 서브에이전트를 호출할 수 있습니다."
                    label="서브에이전트 호출 허용"
                    onChange={(checked) => {
                      setCanDelegate(checked)
                      markDirty()
                    }}
                  />
                </AgentSectionCard>
              </div>
            </div>
          </AgentConfigurationPanel>
        )}

        {activeTab === 'runs' && (
          <AgentRunsPanel emptyText="아직 실행 기록이 없습니다." items={sessionRuns} />
        )}

        {saveError && (
          <p className="text-destructive text-sm" aria-live="polite">
            {saveError}
          </p>
        )}
        {showConfigActionBar && (
          <div className="border-border bg-background/95 fixed inset-x-0 bottom-0 z-30 border-t backdrop-blur-sm sm:hidden">
            <div className="flex items-center justify-end gap-2 px-3 py-2 pb-[max(env(safe-area-inset-bottom),0.5rem)]">
              <Button size="sm" onClick={() => void handleSave()} disabled={saving || !isDirty}>
                {saving ? '저장 중' : '저장'}
              </Button>
              <Button variant="ghost" size="sm" onClick={resetDraft} disabled={saving}>
                취소
              </Button>
            </div>
          </div>
        )}
        {showConfigActionBar && (
          <div className="fixed right-6 bottom-6 z-30 hidden sm:block">
            <div className="bg-background/90 border-border flex items-center gap-2 rounded-lg border px-3 py-1.5 shadow-lg backdrop-blur-sm">
              <Button size="sm" onClick={() => void handleSave()} disabled={saving || !isDirty}>
                {saving ? '저장 중' : '저장'}
              </Button>
              <Button variant="ghost" size="sm" onClick={resetDraft} disabled={saving}>
                취소
              </Button>
            </div>
          </div>
        )}
        <AgentSkillDetailDialog
          detail={skillDetail}
          loading={skillDetailLoading}
          open={skillDetailOpen}
          onDelete={handleSkillDeleted}
          onOpenChange={setSkillDetailOpen}
        />
      </div>
    </WorkspacePageShell>
  )
}

function buildSessionRunItems(
  session: RawAiSession,
  messages: ChatMessageView[],
  taskRunsById: Record<string, RawTaskRun>,
  eventsByTaskRunId: Record<string, RawTaskEventPayload[]>,
  usageRecords: CommandUsageRecord[],
): AgentRunItemData[] {
  const ids = new Set<string>()
  const usageByTaskRunId = buildAgentRunUsageMap(usageRecords)

  messages.forEach((message) => {
    if (message.taskRunId !== undefined) {
      ids.add(message.taskRunId)
    }
  })

  Object.values(taskRunsById).forEach((taskRun) => {
    if (taskRun.session_id === session.session_id) {
      ids.add(taskRun.task_run_id)
    }
  })

  if (typeof session.active_task_run_id === 'string' && session.active_task_run_id.trim()) {
    ids.add(session.active_task_run_id)
  }

  const runItems = [...ids]
    .map((taskRunId) =>
      buildSessionRunItem(taskRunId, session, messages, taskRunsById[taskRunId], eventsByTaskRunId),
    )
    .sort((first, second) => second.sortTime - first.sortTime)
    .map((item) => toAgentRunItem(item, usageByTaskRunId))

  if (runItems.length > 0 || (!session.last_message && !session.last_task_run_status)) {
    return runItems
  }

  const sessionSettings = toJsonObject(session.settings)
  const fallbackModel = getString(sessionSettings, 'model') ?? undefined
  const fallbackProvider =
    getString(sessionSettings, 'providerName') ??
    getString(sessionSettings, 'provider') ??
    getString(sessionSettings, 'provider_name')

  return [
    {
      id: session.session_id,
      status: normalizeRunStatus(session.last_task_run_status),
      source: 'chat',
      createdAt: formatRunTimestamp(getTime(session.last_message_at)),
      summary: session.last_message || '아직 요약이 없습니다.',
      tokens: '-',
      cost: '-',
      adapter: getRunAdapterLabel(fallbackProvider, fallbackModel),
      model: fallbackModel,
      sortTime: getTime(session.last_message_at),
    },
  ]
}

function buildMainAgentTaskRunIds(
  session: RawAiSession,
  messages: ChatMessageView[],
  taskRunsById: Record<string, RawTaskRun>,
  mainProfileId?: string,
) {
  const ids = new Set<string>()
  for (const taskRun of Object.values(taskRunsById)) {
    if (
      taskRun.session_id === session.session_id &&
      taskRunMatchesMainAgent(taskRun, mainProfileId)
    ) {
      ids.add(taskRun.task_run_id)
    }
  }
  for (const message of messages) {
    if (!message.taskRunId) continue
    const taskRun = taskRunsById[message.taskRunId]
    if (taskRun === undefined || taskRunMatchesMainAgent(taskRun, mainProfileId)) {
      ids.add(message.taskRunId)
    }
  }
  if (ids.size === 0 && typeof session.active_task_run_id === 'string') {
    ids.add(session.active_task_run_id)
  }
  return [...ids]
}

function taskRunMatchesMainAgent(taskRun: RawTaskRun, mainProfileId?: string) {
  const context = taskRun.displayContext
  if (mainProfileId) {
    if (matchesMainAgentRef(context?.assigneeAgent, mainProfileId)) return true
    if (matchesMainAgentRef(context?.actorAgent, mainProfileId)) return true
    if (taskRun.agent_profile_id === mainProfileId) return true
  }
  const agentType = String(
    context?.assigneeAgent?.kind ?? context?.actorAgent?.kind ?? '',
  ).toLowerCase()
  if (agentType === 'main') return true
  return context === undefined || context === null
}

function matchesMainAgentRef(agent: TaskRunAgentRef | undefined, mainProfileId: string) {
  return agent?.profileId === mainProfileId || agent?.id === mainProfileId || agent?.kind === 'main'
}

function inferProviderFromModel(
  model: string | null | undefined,
  provider?: string | null,
): SubAgentAdapterType {
  const modelText = (model ?? '').trim().toLowerCase()
  if (modelText.startsWith('gemini-')) {
    return 'gemini_api_key'
  }
  return normalizeSubAgentAdapterType(provider ?? undefined)
}

function getProviderModelOptions(models: AiModelOption[], providerType: SubAgentAdapterType) {
  return models.filter((model) => {
    const provider = model.provider?.toLowerCase()
    if (providerType === 'openai_api_key') {
      return provider === undefined || provider.includes('openai') || provider === 'openai_api_key'
    }
    return provider === providerType || model.id.toLowerCase().startsWith('gemini-')
  })
}

function buildSessionRunItem(
  taskRunId: string,
  session: RawAiSession,
  messages: ChatMessageView[],
  taskRun: RawTaskRun | undefined,
  eventsByTaskRunId: Record<string, RawTaskEventPayload[]>,
): AgentRunItemData & { sortTime: number } {
  const events = (eventsByTaskRunId[taskRunId] ?? []).filter(
    (event) => !isInternalStepAnchorEvent(event),
  )
  const summary = toTaskRunSummaryView(taskRun, events)
  const relatedMessages = messages.filter((message) => message.taskRunId === taskRunId)
  const prompt = relatedMessages.find((message) => message.role === 'user')?.content
  const answer = [...relatedMessages]
    .reverse()
    .find((message) => message.role === 'assistant')?.content
  const inputPayload = toJsonObject(taskRun?.input_payload)
  const resultPayload = toJsonObject(taskRun?.result_payload)
  const resultMetadata = toJsonObject(resultPayload.metadata)
  const sessionSettings = toJsonObject(session.settings)
  const model =
    getFirstString(inputPayload, 'model', 'provider_model', 'providerModel') ??
    getFirstString(resultPayload, 'model') ??
    getFirstString(resultMetadata, 'model') ??
    getString(sessionSettings, 'model') ??
    undefined
  const provider =
    getFirstString(inputPayload, 'provider_name', 'providerName', 'provider') ??
    getFirstString(resultPayload, 'provider_name', 'providerName', 'provider') ??
    getString(sessionSettings, 'providerName') ??
    getString(sessionSettings, 'provider') ??
    getString(sessionSettings, 'provider_name') ??
    undefined
  const sortTime = getRunSortTime(taskRun, events, relatedMessages, session)

  return {
    id: taskRunId,
    status: normalizeRunStatus(
      taskRun?.status ?? summary.tone ?? (answer ? 'COMPLETED' : undefined),
    ),
    source: 'chat',
    createdAt: formatRunTimestamp(sortTime),
    summary:
      getCompactRunSummary(prompt) ??
      getCompactRunSummary(answer) ??
      getCompactRunSummary(summary.title) ??
      '아직 요약이 없습니다.',
    tokens: '-',
    cost: '-',
    adapter: getRunAdapterLabel(provider, model),
    model,
    request:
      prompt ??
      getFirstString(inputPayload, 'prompt', 'content', 'rawUserInput', 'raw_user_input') ??
      undefined,
    delegationInput: buildRunDelegationInput(inputPayload, taskRun?.displayContext),
    result:
      answer ??
      getFirstString(resultPayload, 'summary_message', 'summaryMessage', 'content', 'answer') ??
      getFirstString(taskRun, 'progress_summary') ??
      undefined,
    transcriptSessionId:
      getFirstString(
        inputPayload,
        'transcript_session_id',
        'transcriptSessionId',
        'agentSessionId',
        'agent_session_id',
      ) ?? undefined,
    timeline: buildRunTimelineItems(events),
    sortTime,
  }
}

function toAgentRunItem(
  item: AgentRunItemData & { sortTime: number },
  usageByTaskRunId: Map<string, AgentRunUsageSummary>,
): AgentRunItemData {
  const usage = usageByTaskRunId.get(item.id)
  return {
    id: item.id,
    status: item.status,
    source: item.source,
    createdAt: item.createdAt,
    summary: item.summary,
    tokens: formatAgentRunTokenUsage(usage),
    cost: formatAgentRunCostUsage(usage),
    adapter: item.adapter,
    model: item.model,
    request: item.request,
    delegationInput: item.delegationInput,
    handoff: item.handoff,
    result: item.result,
    transcriptSessionId: item.transcriptSessionId,
    parentTranscriptSessionId: item.parentTranscriptSessionId,
    agentName: item.agentName,
    timeline: item.timeline,
    sortTime: item.sortTime,
  }
}

function getRunSuccessRateLabel(runs: AgentRunItemData[]) {
  const finished = runs.filter(
    (run) => isRunSuccessStatus(run.status) || isRunFailureStatus(run.status),
  )
  if (finished.length === 0) return '0%'
  const succeeded = finished.filter((run) => isRunSuccessStatus(run.status)).length
  return `${Math.round((succeeded / finished.length) * 100)}%`
}

function isRunSuccessStatus(status?: string | null) {
  return status === 'succeeded' || status === 'completed'
}

function isRunFailureStatus(status?: string | null) {
  return (
    status === 'failed' || status === 'blocked' || status === 'cancelled' || status === 'canceled'
  )
}

function getRunSortTime(
  taskRun: RawTaskRun | undefined,
  events: RawTaskEventPayload[],
  messages: ChatMessageView[],
  session: RawAiSession,
) {
  const eventTimes = events.map((event) => getTime(event.occurred_at))
  const messageTimes = messages.map((message) => getTime(message.createdAt))
  return Math.max(
    getTime(taskRun?.completed_at),
    getTime(taskRun?.updated_at),
    getTime(taskRun?.created_at),
    getTime(session.last_message_at),
    ...eventTimes,
    ...messageTimes,
    0,
  )
}

function getCompactRunSummary(value?: string | null) {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''
  if (!text) return undefined
  return text.length > 120 ? `${text.slice(0, 117)}...` : text
}

function getFirstString(source: unknown, ...keys: string[]) {
  const record = toJsonObject(source)
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim() !== '') return value.trim()
  }
  return null
}

function getRunAdapterLabel(provider?: string | null, model?: string | null) {
  const providerText = (provider ?? '').trim().toLowerCase()
  const modelText = (model ?? '').trim().toLowerCase()
  if (providerText.includes('gemini') || modelText.startsWith('gemini-')) return 'gemini'
  if (providerText.includes('openai') || modelText.startsWith('gpt-')) return 'openai'
  return providerText || undefined
}

function buildRunDelegationInput(
  inputPayload: JsonObject,
  displayContext: RawTaskRun['displayContext'] | undefined | null,
) {
  const parts: string[] = []
  const agentName = displayContext?.assigneeAgent?.displayName
  if (agentName && displayContext?.assigneeAgent?.kind !== 'main') {
    parts.push(`담당 에이전트: ${agentName}`)
  }
  const workIdentifier = getFirstString(inputPayload, 'workIdentifier', 'work_identifier')
  if (workIdentifier) parts.push(`작업: ${workIdentifier}`)
  const workContext = toJsonObject(inputPayload.workContext)
  const workTitle = getFirstString(workContext, 'title')
  if (workTitle) parts.push(`작업 제목: ${workTitle}`)
  return parts.length > 0 ? parts.join('\n') : undefined
}

function buildRunTimelineItems(events: RawTaskEventPayload[]) {
  return events.slice(-12).map((event, index) => ({
    id: `${event.task_run_id}-${event.sequence ?? index}`,
    label: event.event_type,
    message: event.summary_message ?? undefined,
    status: event.status ?? undefined,
    time: formatRunTimestamp(getTime(event.occurred_at)),
  }))
}

function formatRunTimestamp(time: number) {
  if (time <= 0) return undefined
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(time))
}

function normalizeRunStatus(status?: string | null) {
  switch (status) {
    case 'completed':
    case 'COMPLETED':
      return 'succeeded'
    case 'failed':
    case 'FAILED':
    case 'CANCELLED':
    case 'CANCELED':
      return 'failed'
    case 'running':
    case 'RUNNING':
      return 'running'
    case 'waiting':
    case 'WAITING':
    case 'PENDING':
      return 'waiting'
    case 'idle':
    case undefined:
    case null:
      return 'pending'
    default:
      return status
  }
}

function formatSessionRunStatus(status?: string | null) {
  switch (normalizeRunStatus(status)) {
    case 'succeeded':
      return '완료'
    case 'running':
      return '실행 중'
    case 'waiting':
      return '대기 중'
    case 'pending':
      return '준비 중'
    case 'failed':
      return '오류'
    default:
      return status || '없음'
  }
}

function getInstructionsFiles(value: unknown): Record<string, string> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, string] =>
        typeof entry[0] === 'string' && typeof entry[1] === 'string',
    ),
  )
}

function getInstructionFilesFromDocuments(value: unknown): Record<string, string> {
  if (!Array.isArray(value)) return {}
  return Object.fromEntries(
    value.flatMap((document) => {
      if (typeof document !== 'object' || document === null || Array.isArray(document)) return []
      const item = document as Record<string, unknown>
      const key = typeof item.documentKey === 'string' ? item.documentKey : ''
      const content = typeof item.content === 'string' ? item.content : ''
      return key ? [[key, content] as const] : []
    }),
  )
}

function shallowStringRecordEqual(left: Record<string, string>, right: Record<string, string>) {
  const leftEntries = Object.entries(left)
  const rightEntries = Object.entries(right)
  if (leftEntries.length !== rightEntries.length) return false
  return leftEntries.every(([key, value]) => right[key] === value)
}

type MainAgentTab = 'dashboard' | 'instructions' | 'skills' | 'configuration' | 'runs'

const MAIN_AGENT_TABS: Array<{ value: MainAgentTab; label: string }> = [
  { value: 'dashboard', label: '대시보드' },
  { value: 'instructions', label: '지침' },
  { value: 'skills', label: '스킬' },
  { value: 'configuration', label: '설정' },
  { value: 'runs', label: '실행 기록' },
]

const inputClass =
  'border-border placeholder:text-muted-foreground/40 focus-visible:ring-ring w-full rounded-md border bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2'

const CEO_IMAGE_OPTIONS = [
  { id: 'profile', label: '프로필', src: '/assets/agents/ceo/ceo_profile_img.png' },
] as const

function MainAgentHeader({
  callName,
  model,
  name,
  onConfigure,
  profileImage,
  saved,
  saving,
}: {
  callName: string
  model: string
  name: string
  onConfigure: () => void
  profileImage: string
  saved: boolean
  saving: boolean
}) {
  return (
    <AgentDetailHeader
      name={name}
      status="작업 가능"
      subtitle={
        <>
          {callName} · {model || '기본 모델'}
        </>
      }
      profile={
        <button
          type="button"
          onClick={onConfigure}
          className="bg-accent hover:bg-accent/80 flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg transition-colors"
          aria-label="메인 에이전트 프로필 설정 열기"
        >
          <img src={profileImage} alt="" className="h-10 w-10 object-contain" draggable={false} />
        </button>
      }
      savedIndicator={
        <>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
              <Check className="h-3.5 w-3.5" />
              저장됨
            </span>
          )}
          {saving && (
            <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              저장 중
            </span>
          )}
        </>
      }
    />
  )
}

function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: ReactNode
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
        {label}
        {hint ? (
          <HelpHint label={`${label} 도움말`} iconClassName="h-3 w-3">
            {hint}
          </HelpHint>
        ) : null}
      </span>
      {children}
    </label>
  )
}

function DraftInput({
  onChange,
  placeholder,
  value,
}: {
  onChange: (value: string) => void
  placeholder: string
  value: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className={inputClass}
    />
  )
}

function ToggleRow({
  checked,
  description,
  label,
  onChange,
}: {
  checked: boolean
  description: string
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="border-border hover:bg-accent/40 flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="border-border mt-0.5 h-4 w-4 rounded"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        <span className="text-muted-foreground mt-0.5 block text-xs leading-5">{description}</span>
      </span>
    </label>
  )
}

function normalizeAgentProfileImage(value: string | undefined) {
  if (value !== undefined && CEO_IMAGE_OPTIONS.some((option) => option.src === value)) {
    return value
  }
  return CEO_IMAGE_OPTIONS[0].src
}

function normalizeMainAgentSkillIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return Array.from(
    new Set(value.filter((item): item is string => typeof item === 'string' && item.trim() !== '')),
  )
}

function orderSkillCatalogBySelectedIds(
  catalog: SkillCatalogItem[],
  selectedSkillIds: string[],
): SkillCatalogItem[] {
  const byId = new Map(catalog.map((skill) => [skill.skillId, skill]))
  const selected = selectedSkillIds
    .map((skillId) => byId.get(skillId))
    .filter((skill): skill is SkillCatalogItem => skill !== undefined)
  const selectedIds = new Set(selected.map((skill) => skill.skillId))
  return [...selected, ...catalog.filter((skill) => !selectedIds.has(skill.skillId))]
}

function stringArraysEqual(left: string[], right: string[]) {
  if (left.length !== right.length) return false
  return left.every((value, index) => right[index] === value)
}

function getMainAgentTab(value: string | null): MainAgentTab {
  if (value === 'overview') return 'dashboard'
  if (value === 'activity') return 'runs'
  return MAIN_AGENT_TABS.some((tab) => tab.value === value) ? (value as MainAgentTab) : 'dashboard'
}

function AgentImageStepper({ profileImage }: { profileImage: string }) {
  return (
    <div
      className="flex min-h-36 w-full min-w-0 items-center justify-center rounded-lg"
      aria-label="에이전트 이미지"
    >
      <div className="bg-accent flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-lg">
        <img src={profileImage} alt="" className="h-24 w-24 object-contain" draggable={false} />
      </div>
    </div>
  )
}

function WorkspacePageShell({
  eyebrow,
  title,
  action,
  children,
  hideHeader = false,
}: {
  eyebrow: string
  title: string
  action?: ReactNode
  children: ReactNode
  hideHeader?: boolean
}) {
  return (
    <main className="bg-background min-w-0 flex-1 overflow-auto p-4 outline-none md:p-6">
      <div className="w-full space-y-6">
        {!hideHeader && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs uppercase">{eyebrow}</span>
              <div className="ml-auto">{action}</div>
            </div>
            <h2 className="text-xl font-bold">{title}</h2>
          </div>
        )}
        {children}
      </div>
    </main>
  )
}

function formatServerError(message: string) {
  return message.replaceAll('AI WebSocket', '서버').replaceAll('AI 웹소켓', '서버')
}
