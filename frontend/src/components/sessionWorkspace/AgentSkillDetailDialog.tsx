import { useMemo, useState } from 'react'
import { ChevronRight, FileText, Folder, FolderOpen, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ChatMarkdown } from '@/components/chat/ChatMarkdown'
import type { SkillCatalogDetail, SkillCatalogDocument } from '@/apis/agents'

type SkillDocumentTreeNode = {
  key: string
  name: string
  order: number
  title: string
  children: SkillDocumentTreeNode[]
  document?: SkillCatalogDocument
}

export function AgentSkillDetailDialog({
  detail,
  loading,
  onOpenChange,
  open,
}: {
  detail: SkillCatalogDetail | null
  loading: boolean
  onOpenChange: (open: boolean) => void
  open: boolean
}) {
  const documents = useMemo(() => normalizeSkillDocuments(detail), [detail])
  const documentTree = useMemo(() => buildSkillDocumentTree(documents), [documents])
  const [selectedDocumentKeyDraft, setSelectedDocumentKeyDraft] = useState<string | null>(null)
  const [closedFolderKeys, setClosedFolderKeys] = useState<Set<string>>(new Set())
  const selectedDocumentKey = documents.some(
    (document) => document.documentKey === selectedDocumentKeyDraft,
  )
    ? selectedDocumentKeyDraft
    : (documents[0]?.documentKey ?? null)
  const selectedDocument = documents.find(
    (document) => document.documentKey === selectedDocumentKey,
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[86vh] max-w-5xl overflow-hidden p-0">
        <DialogHeader className="border-border border-b px-5 py-4">
          <DialogTitle>{detail?.displayName ?? '스킬 상세'}</DialogTitle>
          <DialogDescription className="line-clamp-3">
            {detail?.description ?? '스킬 문서를 확인합니다.'}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="text-muted-foreground flex h-[58vh] items-center justify-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            상세 조회 중
          </div>
        ) : (
          <div className="grid h-[68vh] min-h-0 grid-cols-1 md:grid-cols-[16rem_minmax(0,1fr)]">
            <aside className="border-border bg-muted/20 min-h-0 border-b md:border-r md:border-b-0">
              <div className="border-border flex h-10 items-center border-b px-3 text-xs font-medium">
                문서
              </div>
              <div className="max-h-48 overflow-y-auto p-2 md:max-h-[calc(68vh-2.5rem)]">
                {documentTree.length ? (
                  <SkillDocumentTree
                    nodes={documentTree}
                    closedFolderKeys={closedFolderKeys}
                    selectedDocumentKey={selectedDocumentKey}
                    onDocumentSelect={setSelectedDocumentKeyDraft}
                    onFolderToggle={(folderKey) => {
                      setClosedFolderKeys((current) => {
                        const next = new Set(current)
                        if (next.has(folderKey)) next.delete(folderKey)
                        else next.add(folderKey)
                        return next
                      })
                    }}
                  />
                ) : (
                  <p className="text-muted-foreground px-2 py-6 text-center text-xs">
                    문서가 없습니다.
                  </p>
                )}
              </div>
            </aside>

            <section className="bg-background min-h-0 overflow-hidden">
              <div className="border-border flex h-10 min-w-0 items-center gap-2 border-b px-4">
                <FileText className="text-muted-foreground h-4 w-4 shrink-0" />
                <span className="truncate text-sm font-medium">
                  {selectedDocument?.title ?? '문서 없음'}
                </span>
              </div>
              <div className="h-[calc(68vh-2.5rem)] overflow-y-auto px-5 py-4">
                {selectedDocument?.content ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ChatMarkdown content={selectedDocument.content} />
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm">내용이 없습니다.</p>
                )}
              </div>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function SkillDocumentTree({
  nodes,
  onDocumentSelect,
  onFolderToggle,
  closedFolderKeys,
  selectedDocumentKey,
}: {
  nodes: SkillDocumentTreeNode[]
  onDocumentSelect: (documentKey: string) => void
  onFolderToggle: (folderKey: string) => void
  closedFolderKeys: Set<string>
  selectedDocumentKey: string | null
}) {
  return (
    <div className="space-y-0.5">
      {nodes.map((node) => (
        <SkillDocumentTreeItem
          key={node.key}
          depth={0}
          node={node}
          closedFolderKeys={closedFolderKeys}
          selectedDocumentKey={selectedDocumentKey}
          onDocumentSelect={onDocumentSelect}
          onFolderToggle={onFolderToggle}
        />
      ))}
    </div>
  )
}

function SkillDocumentTreeItem({
  depth,
  node,
  onDocumentSelect,
  onFolderToggle,
  closedFolderKeys,
  selectedDocumentKey,
}: {
  depth: number
  node: SkillDocumentTreeNode
  onDocumentSelect: (documentKey: string) => void
  onFolderToggle: (folderKey: string) => void
  closedFolderKeys: Set<string>
  selectedDocumentKey: string | null
}) {
  const isFolder = node.children.length > 0 && node.document === undefined
  const isOpen = !closedFolderKeys.has(node.key)
  const isSelected = node.document?.documentKey === selectedDocumentKey
  const paddingLeft = `${depth * 0.85 + 0.5}rem`

  if (isFolder) {
    return (
      <div>
        <button
          type="button"
          className="hover:bg-accent/60 flex h-8 w-full min-w-0 items-center gap-1.5 rounded-md pr-2 text-left text-sm transition-colors"
          style={{ paddingLeft }}
          onClick={() => onFolderToggle(node.key)}
        >
          <ChevronRight
            className={`text-muted-foreground h-3.5 w-3.5 shrink-0 transition-transform ${
              isOpen ? 'rotate-90' : ''
            }`}
          />
          {isOpen ? (
            <FolderOpen className="text-muted-foreground h-4 w-4 shrink-0" />
          ) : (
            <Folder className="text-muted-foreground h-4 w-4 shrink-0" />
          )}
          <span className="truncate">{node.title}</span>
        </button>
        {isOpen ? (
          <div className="space-y-0.5">
            {node.children.map((child) => (
              <SkillDocumentTreeItem
                key={child.key}
                depth={depth + 1}
                node={child}
                closedFolderKeys={closedFolderKeys}
                selectedDocumentKey={selectedDocumentKey}
                onDocumentSelect={onDocumentSelect}
                onFolderToggle={onFolderToggle}
              />
            ))}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <button
      type="button"
      className={`flex h-8 w-full min-w-0 items-center gap-1.5 rounded-md pr-2 text-left text-sm transition-colors ${
        isSelected ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/60'
      }`}
      style={{ paddingLeft }}
      onClick={() => {
        if (node.document) onDocumentSelect(node.document.documentKey)
      }}
    >
      <span className="w-3.5 shrink-0" />
      <FileText className="h-4 w-4 shrink-0" />
      <span className="truncate">{node.title}</span>
    </button>
  )
}

function normalizeSkillDocuments(detail: SkillCatalogDetail | null): SkillCatalogDocument[] {
  if (!detail) return []
  if (detail.documents?.length) return detail.documents
  if (detail.body) {
    return [
      {
        documentKey: 'SKILL.md',
        title: '기본 지침',
        content: detail.body,
        contentFormat: 'markdown',
      },
    ]
  }
  return []
}

function buildSkillDocumentTree(documents: SkillCatalogDocument[]): SkillDocumentTreeNode[] {
  const root: SkillDocumentTreeNode[] = []
  for (const [documentIndex, document] of documents.entries()) {
    const parts = document.documentKey.split('/').filter(Boolean)
    let current = root
    let key = ''
    for (const [index, part] of parts.entries()) {
      key = key ? `${key}/${part}` : part
      const isLeaf = index === parts.length - 1
      let node = current.find((item) => item.key === key)
      if (!node) {
        node = {
          key,
          name: part,
          order: documentIndex,
          title: isLeaf ? document.title : formatFolderTitle(part),
          children: [],
          document: isLeaf ? document : undefined,
        }
        current.push(node)
      }
      if (isLeaf) {
        node.title = document.title
        node.document = document
      }
      current = node.children
    }
  }
  return sortSkillDocumentTree(root)
}

function sortSkillDocumentTree(nodes: SkillDocumentTreeNode[]): SkillDocumentTreeNode[] {
  return [...nodes]
    .sort((a, b) => {
      if (a.name === 'SKILL.md') return -1
      if (b.name === 'SKILL.md') return 1
      if (a.children.length !== b.children.length) return b.children.length - a.children.length
      return a.order - b.order
    })
    .map((node) => ({ ...node, children: sortSkillDocumentTree(node.children) }))
}

function formatFolderTitle(value: string) {
  if (value === 'references') return '참고 문서'
  if (value === 'scripts') return '실행 스크립트'
  if (value === 'assets') return '자료'
  return value.replace(/[-_]/g, ' ')
}
