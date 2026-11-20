import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, LoaderCircle, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { toast } from "../../../components/ui/toaster";
import { documentsApi } from "../../../services/api/documents-api";
import type { DocumentResponse, GroupDetails } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { DocumentRow } from "../../documents/components/document-row";
import { downloadDocument } from "../../documents/utils/download-document";

export function GroupDocumentsPanel({ group }: { group: GroupDetails }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<DocumentResponse | null>(null);
  const query = useInfiniteQuery({
    queryKey: ["groups", group.group_id, "documents"],
    queryFn: ({ pageParam }) => documentsApi.groupList(group.group_id, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: (state) => state.state.data?.pages.some((page) => page.items.some((item) => item.status === "pending" || item.status === "processing")) ? 5000 : false,
  });
  const upload = useMutation({
    mutationFn: (file: File) => documentsApi.upload(group.group_id, file, setProgress),
    onSuccess: async (document) => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "documents"] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
      toast({ variant: "success", title: "Document uploaded", description: `${document.filename} is queued for processing.` });
    },
    onError: (error) => toast({ variant: "error", title: "Upload failed", description: getErrorMessage(error) }),
  });
  const remove = useMutation({
    mutationFn: documentsApi.remove,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "documents"] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setDeleteTarget(null);
      toast({ variant: "success", title: "Document deleted" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not delete document", description: getErrorMessage(error) }),
  });
  const retry = useMutation({
    mutationFn: documentsApi.retry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "documents"] });
      toast({ variant: "success", title: "Processing restarted" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not retry processing", description: getErrorMessage(error) }),
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const chooseFile = (file?: File) => {
    if (file) upload.mutate(file);
  };
  const onDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  };

  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div><h2 className="text-sm font-semibold text-slate-900">Group documents</h2><p className="mt-1 text-xs text-slate-500">Files and vector search are scoped to {group.name}.</p></div>
          <Button size="sm" onClick={() => inputRef.current?.click()} disabled={upload.isPending}><UploadCloud className="h-4 w-4" /> Upload file</Button>
          <input ref={inputRef} type="file" accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="sr-only" aria-label="Select document to upload" onChange={(event) => chooseFile(event.target.files?.[0])} />
        </div>
        <button
          type="button"
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`m-4 flex w-[calc(100%-2rem)] flex-col items-center justify-center rounded-xl border border-dashed px-4 py-5 text-center transition sm:m-5 sm:w-[calc(100%-2.5rem)] ${dragging ? "border-brand-400 bg-brand-50" : "border-slate-200 bg-slate-50/60 hover:border-brand-300 hover:bg-brand-50/30"}`}
          disabled={upload.isPending}
        >
          {upload.isPending ? <LoaderCircle className="h-5 w-5 animate-spin text-brand-600" /> : <UploadCloud className="h-5 w-5 text-slate-400" />}
          <span className="mt-2 text-xs font-medium text-slate-700">{upload.isPending ? `Uploading ${progress}%` : "Drop a PDF, TXT, or DOCX here, or browse"}</span>
          <span className="mt-1 text-[10px] text-slate-400">Maximum upload size: 20 MB</span>
          {upload.isPending && <span className="mt-3 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-slate-200"><span className="block h-full bg-brand-600 transition-all" style={{ width: `${progress}%` }} /></span>}
        </button>
        {upload.isError && <p role="alert" className="px-5 pb-3 text-xs text-rose-700">{getErrorMessage(upload.error, "Document upload failed.")}</p>}
        {query.isPending ? <div className="space-y-3 p-5"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> :
          query.isError ? <div className="p-5"><ErrorState message={getErrorMessage(query.error, "Could not load group documents.")} onRetry={() => void query.refetch()} /></div> :
          items.length === 0 ? <EmptyState icon={<FileText className="h-5 w-5" />} title="No documents in this group" description="Upload team references to make them available to group-scoped AI retrieval." /> :
          <div className="divide-y divide-slate-100">{items.map((document) => <DocumentRow key={document.document_id} document={document} onDownload={() => void downloadDocument(document)} onDelete={() => setDeleteTarget(document)} onRetry={() => retry.mutate(document.document_id)} busy={remove.isPending || retry.isPending} />)}</div>}
        {query.hasNextPage && <div className="flex justify-center border-t border-slate-100 p-4"><Button variant="outline" size="sm" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>Load more</Button></div>}
      </Card>
      <ConfirmationDialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) { setDeleteTarget(null); remove.reset(); } }} title="Delete document?" description={`Delete ${deleteTarget?.filename ?? "this document"} and its indexed content?`} confirmLabel="Delete document" pending={remove.isPending} onConfirm={() => deleteTarget && remove.mutate(deleteTarget.document_id)} />
    </>
  );
}
