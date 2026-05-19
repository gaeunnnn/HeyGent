import { Plus } from 'lucide-react'
import type { AgentPanelItem } from '@/store/useSessionStore'
import { SubAgentProfileImage } from './SubAgentProfileImage'

export function SubAgentList({
  agentPanels,
  onCreate,
  onOpen,
}: {
  agentPanels: AgentPanelItem[]
  onCreate: () => void
  onOpen: (itemId: string) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={onCreate}
          className="border-border hover:bg-accent/50 inline-flex items-center gap-1.5 border px-2.5 py-1.5 text-xs font-medium transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          추가
        </button>
      </div>

      <div className="border-border border">
        {agentPanels.length === 0 ? (
          <p className="text-muted-foreground px-4 py-3 text-sm">
            에이전트가 없습니다. 추가 버튼으로 역할을 나눌 수 있습니다.
          </p>
        ) : (
          agentPanels.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onOpen(item.id)}
              className="border-border hover:bg-accent/50 flex w-full items-center gap-3 border-b px-4 py-2 text-left text-sm transition-colors last:border-b-0"
            >
              <SubAgentProfileImage
                accent={item.agent.accent}
                profileImage={item.agent.profileImage}
                spriteId={item.agent.spriteId}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{item.agent.name}</span>
                {item.agent.title && (
                  <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                    {item.agent.title}
                  </span>
                )}
                {item.agent.description && (
                  <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                    {item.agent.description}
                  </span>
                )}
              </span>
              {item.agent.skills?.length ? (
                <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">
                  {item.agent.skills.length} skills
                </span>
              ) : null}
            </button>
          ))
        )}
      </div>
    </section>
  )
}
