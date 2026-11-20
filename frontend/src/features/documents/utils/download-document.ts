import { documentsApi } from "../../../services/api/documents-api";
import type { DocumentResponse } from "../../../types/api";
import { toast } from "../../../components/ui/toaster";
import { getErrorMessage } from "../../../utils/errors";

export async function downloadDocument(document: DocumentResponse) {
  try {
    const blob = await documentsApi.download(document.document_id);
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    toast({ variant: "error", title: "Could not download document", description: getErrorMessage(error) });
  }
}
