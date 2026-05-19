import { useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  Circle,
  CircleCheck,
  Clock3,
  FileText,
  ListTree,
  PauseCircle,
  PlayCircle,
  Plus,
  X,
  SlidersHorizontal,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/components/ui/utils'
import type { IssueBoardIssue, IssueBoardStatus } from '../model/issueBoardModel'
import { formatRelativeTime } from './issueBoardPanelUtils'

export function IssueRelatedPanel({
  allIssues,
  issue,
  onAddRelation,
  onChangeParent,
  onCreateChild,
  onRemoveRelation,
}: {
  allIssues: IssueBoardIssue[]
  issue: IssueBoardIssue
  onAddRelation: (sourceId: string, targetId: string, relationType: 'blocks' | 'related') => void
  onChangeParent: (issueId: string, parentId: string | null) => void
  onCreateChild: (parentId: string, title: string, description: string) => void
  onRemoveRelation: (sourceId: string, targetId: string, relationType: 'blocks' | 'related') => void
}) {
  const candidates = allIssues.filter((item) => item.id !== issue.id)
  const parent = issue.parentId ? allIssues.find((item) => item.id === issue.parentId) : null
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <RelatedSection title="부모 작업" icon={<ListTree className="h-4 w-4" />}>
        {parent ? (
          <RelatedIssuePill item={parent} onRemove={() => onChangeParent(issue.id, null)} />
        ) : (
          <EmptyRelatedText>루트 작업</EmptyRelatedText>
        )}
        <RelationPicker
          candidates={candidates.filter((candidate) => candidate.id !== issue.parentId)}
          label="부모 선택"
          onSelect={(targetId) => onChangeParent(issue.id, targetId)}
        />
      </RelatedSection>
      <RelatedSection title="하위 작업" icon={<ListTree className="h-4 w-4" />}>
        {issue.childItems.length > 0 ? (
          issue.childItems.map((item) => <RelatedIssuePill key={item.id} item={item} />)
        ) : (
          <EmptyRelatedText>하위 작업 없음</EmptyRelatedText>
        )}
        <ChildWorkForm
          onSubmit={(title, description) => onCreateChild(issue.id, title, description)}
        />
      </RelatedSection>
      <RelatedSection title="차단 항목" icon={<AlertTriangle className="h-4 w-4" />}>
        {issue.blockedBy.length > 0 ? (
          issue.blockedBy.map((item) => (
            <RelatedIssuePill
              key={item.id}
              item={item}
              onRemove={() => onRemoveRelation(item.id, issue.id, 'blocks')}
            />
          ))
        ) : (
          <EmptyRelatedText>차단 항목 없음</EmptyRelatedText>
        )}
        <RelationPicker
          candidates={candidates}
          label="차단 항목 추가"
          onSelect={(targetId) => onAddRelation(targetId, issue.id, 'blocks')}
        />
      </RelatedSection>
      <RelatedSection title="관련 작업" icon={<ListTree className="h-4 w-4" />}>
        {issue.relatedItems.length > 0 ? (
          issue.relatedItems.map((item) => (
            <RelatedIssuePill
              key={item.id}
              item={item}
              onRemove={() => onRemoveRelation(issue.id, item.id, 'related')}
            />
          ))
        ) : (
          <EmptyRelatedText>관련 작업 없음</EmptyRelatedText>
        )}
        <RelationPicker
          candidates={candidates}
          label="관련 작업 추가"
          onSelect={(targetId) => onAddRelation(issue.id, targetId, 'related')}
        />
      </RelatedSection>
      <RelatedSection title="산출물" icon={<FileText className="h-4 w-4" />}>
        {issue.documents.length > 0 ? (
          issue.documents.map((document) => (
            <div key={document.id} className="rounded-md border p-3">
              <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{document.title}</span>
              </div>
              <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">{document.summary}</p>
              <p className="text-muted-foreground mt-2 text-[11px]">
                수정 {formatRelativeTime(document.updatedAt)}
              </p>
            </div>
          ))
        ) : (
          <EmptyRelatedText>산출물 없음</EmptyRelatedText>
        )}
      </RelatedSection>
      <RelatedSection title="실행 정책" icon={<SlidersHorizontal className="h-4 w-4" />}>
        <div className="text-muted-foreground rounded-md border p-3 text-xs">
          담당 에이전트 1명이 이 작업 컨텍스트로 실행합니다. 서버 연결 후 작업 실행, 재개, 중단
          이벤트가 이 영역에 반영됩니다.
        </div>
      </RelatedSection>
    </div>
  )
}

function ChildWorkForm({ onSubmit }: { onSubmit: (title: string, description: string) => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-2 h-8 gap-1.5"
        onClick={() => setOpen(true)}
      >
        <Plus className="h-3.5 w-3.5" />
        하위 작업 추가
      </Button>
    )
  }
  const submit = () => {
    const nextTitle = title.trim()
    if (!nextTitle) return
    onSubmit(nextTitle, description.trim() || nextTitle)
    setTitle('')
    setDescription('')
    setOpen(false)
  }
  return (
    <div className="rounded-md border p-2">
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="하위 작업 제목"
        className="bg-background h-8 w-full rounded border px-2 text-xs outline-none focus:ring-1"
      />
      <textarea
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="설명"
        className="bg-background mt-2 min-h-16 w-full resize-none rounded border px-2 py-1.5 text-xs outline-none focus:ring-1"
      />
      <div className="mt-2 flex justify-end gap-1">
        <Button type="button" size="sm" className="h-8" onClick={submit}>
          추가
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8"
          onClick={() => setOpen(false)}
        >
          취소
        </Button>
      </div>
    </div>
  )
}

function RelatedSection({
  children,
  icon,
  title,
}: {
  children: ReactNode
  icon: ReactNode
  title: string
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-muted-foreground flex items-center gap-1.5 text-xs font-semibold tracking-widest uppercase">
        {icon}
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

function EmptyRelatedText({ children }: { children: ReactNode }) {
  return <div className="text-muted-foreground rounded-md border p-3 text-xs">{children}</div>
}

function RelationPicker({
  candidates,
  label,
  onSelect,
}: {
  candidates: IssueBoardIssue[]
  label: string
  onSelect: (targetId: string) => void
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2 h-8 gap-1.5"
          disabled={candidates.length === 0}
        >
          <Plus className="h-3.5 w-3.5" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-1">
        {candidates.slice(0, 12).map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            onClick={() => onSelect(candidate.id)}
            className="hover:bg-accent/50 flex w-full items-center gap-2 rounded-sm px-2 py-2 text-left text-xs"
          >
            <span className="text-muted-foreground shrink-0 font-mono">{candidate.identifier}</span>
            <span className="truncate">{candidate.title}</span>
          </button>
        ))}
      </PopoverContent>
    </Popover>
  )
}

export function RelatedIssuePill({
  item,
  onRemove,
}: {
  item: IssueBoardIssue['relatedItems'][number]
  onRemove?: () => void
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-sm">
      <RelatedStatusIcon status={item.status} />
      <span className="text-muted-foreground shrink-0 font-mono text-xs">{item.identifier}</span>
      <span className="min-w-0 flex-1 truncate">{item.title}</span>
      {onRemove && (
        <button
          type="button"
          aria-label="관계 제거"
          className="text-muted-foreground hover:text-foreground shrink-0"
          onClick={onRemove}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

function RelatedStatusIcon({ status }: { status: IssueBoardStatus }) {
  const iconMap = {
    backlog: Clock3,
    todo: Circle,
    in_progress: PlayCircle,
    in_review: PauseCircle,
    blocked: AlertTriangle,
    done: CircleCheck,
    cancelled: Circle,
  }
  const Icon = iconMap[status]
  return (
    <Icon
      className={cn(
        'h-3.5 w-3.5 shrink-0',
        status === 'done' && 'text-green-500',
        status === 'blocked' && 'text-red-500',
        status === 'in_progress' && 'text-cyan-500',
      )}
    />
  )
}
