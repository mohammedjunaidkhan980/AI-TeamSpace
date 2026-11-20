import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, Search, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../../../components/shared/page-header";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Input } from "../../../components/ui/input";
import { Modal } from "../../../components/ui/modal";
import { Skeleton } from "../../../components/ui/skeleton";
import { toast } from "../../../components/ui/toaster";
import { documentsApi } from "../../../services/api/documents-api";
import { groupsApi } from "../../../services/api/groups-api";
import type { DocumentResponse } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { DocumentRow } from "../components/document-row";
import { downloadDocument } from "../utils/download-document";

export function DocumentsPage() {
  const [searchParams] = useSearchParams();
  const selectedId = searchParams.get("documentId");
  const [search, setSearch] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentResponse | null>(null);
  const queryClient = useQueryClient();
  const groupsQuery = useQuery({ queryKey: ["groups"], queryFn: groupsApi.list });
  const query = useInfiniteQuery({
    queryKey: ["documents", { search }],
    queryFn: ({ pageParam }) => documentsApi.list({ search, before: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: (queryState) => queryState.state.data?.pages.some((page) => page.items.some((item) => item.status === "pending" || item.status === "processing")) ? 5000 : false,
  });
  const selectedQuery = useQuery({
    queryKey: ["documents", selectedId],
    queryFn: () => documentsApi.details(selectedId!),
    enabled: Boolean(selectedId),
  });
  const [uploadProgress, setUploadProgress] = useState(0);
  const uploadMutation = useMutation({
    mutationFn: ({ groupId, file }: { groupId: string; file: File }) =>
      documentsApi.upload(groupId, file, setUploadProgress),
    onSuccess: async (document) => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setUploadOpen(false);
      setUploadProgress(0);
      toast({ variant: "success", title: "Document uploaded", description: `${document.filename} is queued for processing.` });
    },
    onError: (error) => toast({ variant: "error", title: "Upload failed", description: getErrorMessage(error) }),
  });
  const deleteMutation = useMutation({
    mutationFn: documentsApi.remove,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setDeleteTarget(null);
      toast({ variant: "success", title: "Document deleted" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not delete document", description: getErrorMessage(error) }),
  });
  const retryMutation = useMutation({
    mutationFn: documentsApi.retry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast({ variant: "success", title: "Processing restarted" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not retry processing", description: getErrorMessage(error) }),
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const groupNames = new Map((groupsQuery.data?.items ?? []).map((group) => [group.group_id, group.name]));

  useEffect(() => {
    if (selectedId) {
      document.getElementById(`document-${selectedId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selectedId, items.length]);

  return (
    <>
      <PageHeader title="Documents" description="Manage group knowledge and track document processing." action={<Button onClick={() => setUploadOpen(true)} disabled={!groupsQuery.data?.items.length}><Plus className="h-4 w-4" /> Upload document</Button>} />
      {groupsQuery.isError && <ErrorState message={getErrorMessage(groupsQuery.error, "Could not load your groups.")} onRetry={() => void groupsQuery.refetch()} />}
      <div className="mb-5 max-w-lg">
        <span className="relative block"><Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search filenames" aria-label="Search documents" className="pl-10" /></span>
      </div>
      {selectedId && selectedQuery.data && (
        <Card className="mb-5 border-brand-100 bg-brand-50/30 p-4">
          <div className="flex items-start justify-between gap-4">
            <div><p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Referenced source</p><p className="mt-1 text-sm font-semibold text-slate-900">{selectedQuery.data.filename}</p><p className="mt-1 text-xs text-slate-500">Group: {groupNames.get(selectedQuery.data.group_id) ?? selectedQuery.data.group_id} · Uploaded by {selectedQuery.data.uploader_name}</p></div>
            <Button size="sm" variant="outline" onClick={() => selectedQuery.data && void downloadDocument(selectedQuery.data)}>Download</Button>
          </div>
        </Card>
      )}
      {selectedId && selectedQuery.isError && <ErrorState message="The referenced document is unavailable or you no longer have access to its group." />}
      {query.isPending ? (
        <div className="space-y-3">{[1, 2, 3].map((item) => <Skeleton className="h-20" key={item} />)}</div>
      ) : query.isError ? (
        <ErrorState message={getErrorMessage(query.error, "Could not load documents.")} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <Card><EmptyState icon={<FileText className="h-5 w-5" />} title={search ? "No documents found" : "No documents yet"} description={search ? "Try another filename search." : "Upload a PDF, TXT, or DOCX file to a group to make it searchable for AI agents."} action={!search && groupsQuery.data?.items.length ? <Button onClick={() => setUploadOpen(true)}><UploadCloud className="h-4 w-4" /> Upload your first document</Button> : undefined} /></Card>
      ) : (
        <Card className="divide-y divide-slate-100">
          {items.map((document) => (
            <div key={document.document_id} id={`document-${document.document_id}`} className={selectedId === document.document_id ? "bg-brand-50/40" : ""}>
              <div className="flex items-center gap-3 px-4 pt-3 sm:px-5">
                <span className="text-xs font-medium text-brand-700">{groupNames.get(document.group_id) ?? "Group"}</span>
              </div>
              <DocumentRow
                document={document}
                onDownload={() => void downloadDocument(document)}
                onDelete={() => setDeleteTarget(document)}
                onRetry={() => retryMutation.mutate(document.document_id)}
                busy={deleteMutation.isPending || retryMutation.isPending}
              />
            </div>
          ))}
          {query.hasNextPage && <div className="flex justify-center p-4"><Button variant="outline" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>Load more</Button></div>}
        </Card>
      )}

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        groups={groupsQuery.data?.items ?? []}
        progress={uploadProgress}
        pending={uploadMutation.isPending}
        error={uploadMutation.isError ? getErrorMessage(uploadMutation.error) : null}
        onSubmit={(groupId, file) => uploadMutation.mutate({ groupId, file })}
      />
      <ConfirmationDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => { if (!open) { setDeleteTarget(null); deleteMutation.reset(); } }}
        title="Delete document?"
        description={`Delete ${deleteTarget?.filename ?? "this document"} and its indexed content? This cannot be undone.`}
        confirmLabel="Delete document"
        pending={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.document_id)}
      />
    </>
  );
}

function UploadDialog({
  open,
  onOpenChange,
  groups,
  progress,
  pending,
  error,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: Array<{ group_id: string; name: string }>;
  progress: number;
  pending: boolean;
  error: string | null;
  onSubmit: (groupId: string, file: File) => void;
}) {
  const [groupId, setGroupId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Upload a document" description="Documents are private to the selected group and indexed for group-scoped AI retrieval. Supported formats: PDF, TXT, DOCX (maximum 20 MB).">
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (groupId && file) onSubmit(groupId, file); }}>
        <label className="block text-sm font-medium text-slate-700">Group
          <select value={groupId} onChange={(event) => setGroupId(event.target.value)} required className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100">
            <option value="">Select a group</option>{groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.name}</option>)}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">File
          <input type="file" accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required className="mt-1.5 block w-full rounded-xl border border-slate-200 p-2 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700" />
        </label>
        {pending && <div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-brand-600 transition-all" style={{ width: `${progress}%` }} /></div><p className="mt-1 text-right text-xs text-slate-500">{progress}% uploaded</p></div>}
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button type="submit" disabled={!groupId || !file || pending}>{pending ? "Uploading…" : "Upload"}</Button></div>
      </form>
    </Modal>
  );
}
