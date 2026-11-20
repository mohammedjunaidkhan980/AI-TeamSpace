import { AlertCircle, ArrowDownToLine, Clock3, FileText, LoaderCircle, RotateCw, Trash2 } from "lucide-react";
import { Button } from "../../../components/ui/button";
import type { DocumentResponse } from "../../../types/api";

export function DocumentRow({
  document,
  onDownload,
  onDelete,
  onRetry,
  busy = false,
}: {
  document: DocumentResponse;
  onDownload: () => void;
  onDelete: () => void;
  onRetry?: () => void;
  busy?: boolean;
}) {
  return (
    <article className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:px-5">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><FileText className="h-5 w-5" /></span>
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-semibold text-slate-900">{document.filename}</h3>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
          <span className="uppercase">{document.file_type}</span><span>·</span><span>{formatFileSize(document.file_size)}</span><span>·</span>
          <span>{document.uploader_name}</span><span>·</span><Clock3 className="h-3 w-3" /><time dateTime={document.created_at}>{new Date(document.created_at).toLocaleDateString()}</time>
        </p>
        {document.processing_error && <p className="mt-1 text-xs text-rose-700">{document.processing_error}</p>}
      </div>
      <div className="flex items-center justify-between gap-2 sm:justify-end">
        <DocumentStatus status={document.status} />
        {document.status === "failed" && onRetry && <Button variant="outline" size="sm" onClick={onRetry} disabled={busy}><RotateCw className="h-3.5 w-3.5" /> Retry</Button>}
        <Button variant="ghost" size="icon" aria-label={`Download ${document.filename}`} onClick={onDownload} disabled={busy}><ArrowDownToLine className="h-4 w-4" /></Button>
        <Button variant="ghost" size="icon" aria-label={`Delete ${document.filename}`} onClick={onDelete} disabled={busy}><Trash2 className="h-4 w-4 text-slate-400 hover:text-rose-600" /></Button>
      </div>
    </article>
  );
}

export function DocumentStatus({ status }: { status: DocumentResponse["status"] }) {
  const styles: Record<DocumentResponse["status"], string> = {
    uploaded: "bg-slate-100 text-slate-600",
    pending: "bg-amber-50 text-amber-700",
    processing: "bg-brand-50 text-brand-700",
    completed: "bg-emerald-50 text-emerald-700",
    failed: "bg-rose-50 text-rose-700",
  };
  const icon = status === "processing" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : status === "failed" ? <AlertCircle className="h-3 w-3" /> : null;
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold capitalize ${styles[status]}`}>{icon}{status}</span>;
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
