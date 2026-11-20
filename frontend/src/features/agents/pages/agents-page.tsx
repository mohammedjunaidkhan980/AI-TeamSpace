import { useQuery } from "@tanstack/react-query";
import { Bot, Sparkles } from "lucide-react";
import { PageHeader } from "../../../components/shared/page-header";
import { Card, CardContent } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { agentsApi } from "../../../services/api/agents-api";
import { getErrorMessage } from "../../../utils/errors";

export function AgentsPage() {
  const query = useQuery({ queryKey: ["agents", "templates"], queryFn: agentsApi.templates });

  return (
    <>
      <PageHeader title="AI agents" description="Specialized teammates for research, building, analysis, and more." />
      <div className="mb-5 flex items-start gap-3 rounded-xl border border-brand-100 bg-brand-50/70 p-4 text-sm text-brand-900">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
        <p>These are reusable templates. Group-specific agent configuration is available through the group APIs; this page is currently a read-only template catalog.</p>
      </div>
      {query.isPending ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[1, 2, 3].map((item) => <Skeleton className="h-44" key={item} />)}</div> :
        query.isError ? <ErrorState message={getErrorMessage(query.error, "Could not load agent templates.")} onRetry={() => void query.refetch()} /> :
        query.data.length === 0 ? <Card><EmptyState icon={<Bot className="h-5 w-5" />} title="No agent templates available" description="Templates will appear here when the backend provides them." /></Card> :
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {query.data.map((template) => (
            <Card key={template.template_id} className="p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><Bot className="h-5 w-5" /></span>
                <div><h2 className="font-semibold text-slate-900">{template.name}</h2><p className="mt-1 text-xs capitalize text-brand-700">{template.template_id.replaceAll("_", " ")}</p></div>
              </div>
              <CardContent className="px-0 pb-0 pt-4">
                <p className="text-sm leading-6 text-slate-500">{template.description}</p>
                <div className="mt-4 flex flex-wrap gap-1.5">{template.capabilities.map((capability) => <span key={capability} className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">{capability.replaceAll("_", " ")}</span>)}</div>
              </CardContent>
            </Card>
          ))}
        </div>}
    </>
  );
}
