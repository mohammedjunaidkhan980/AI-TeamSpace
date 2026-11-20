import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Plus, Power, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Modal } from "../../../components/ui/modal";
import { Skeleton } from "../../../components/ui/skeleton";
import { Spinner } from "../../../components/ui/spinner";
import { toast } from "../../../components/ui/toaster";
import { agentsApi } from "../../../services/api/agents-api";
import type { AgentTemplate, GroupAgent } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";

interface GroupAgentsPanelProps {
  groupId: string;
  isAdmin: boolean;
}

export function GroupAgentsPanel({ groupId, isAdmin }: GroupAgentsPanelProps) {
  const [addOpen, setAddOpen] = useState(false);
  const [confirmAgent, setConfirmAgent] = useState<GroupAgent | null>(null);
  const queryClient = useQueryClient();
  const agentsQuery = useQuery({
    queryKey: ["groups", groupId, "agents"],
    queryFn: () => agentsApi.groupAgents(groupId),
  });
  const templatesQuery = useQuery({
    queryKey: ["agents", "templates"],
    queryFn: agentsApi.templates,
    enabled: addOpen,
  });
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["groups", groupId, "agents"] }),
      queryClient.invalidateQueries({ queryKey: ["groups", groupId] }),
    ]);
  };
  const statusMutation = useMutation({
    mutationFn: ({ agentId, enabled }: { agentId: string; enabled: boolean }) =>
      agentsApi.updateStatus(groupId, agentId, enabled),
    onSuccess: async (agent) => {
      await invalidate();
      toast({ variant: "success", title: agent.enabled ? "Agent enabled" : "Agent disabled", description: `${agent.name} is ${agent.enabled ? "ready to be invoked" : "paused"}.` });
    },
  });
  const removeMutation = useMutation({
    mutationFn: (agent: GroupAgent) => agentsApi.removeFromGroup(groupId, agent.agent_id),
    onSuccess: async () => {
      await invalidate();
      toast({ variant: "success", title: "Agent removed", description: "The agent is no longer available to this group." });
      setConfirmAgent(null);
    },
  });
  const agents = agentsQuery.data ?? [];
  const availableTemplates = useMemo(() => {
    const activeTemplateIds = new Set(agents.map((agent) => agent.template_id));
    return (templatesQuery.data ?? []).filter((template) => !activeTemplateIds.has(template.template_id));
  }, [agents, templatesQuery.data]);

  return (
    <>
      <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div><h2 className="text-sm font-semibold text-slate-900">Agents assigned to this group</h2><p className="mt-1 text-xs text-slate-500">Each agent has a group-specific configuration based on a reusable template.</p></div>
        {isAdmin && <Button size="sm" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add agent</Button>}
      </div>
      {statusMutation.isError && <div className="px-5 pt-4 sm:px-6"><ErrorState message={getErrorMessage(statusMutation.error, "Could not update agent status.")} /></div>}
      {removeMutation.isError && <div className="px-5 pt-4 sm:px-6"><ErrorState message={getErrorMessage(removeMutation.error, "Could not remove this agent.")} onRetry={() => confirmAgent && removeMutation.mutate(confirmAgent)} /></div>}
      {agentsQuery.isPending ? (
        <div className="grid gap-3 p-5 sm:grid-cols-2 sm:p-6">{[1, 2].map((item) => <Skeleton className="h-44" key={item} />)}</div>
      ) : agentsQuery.isError ? (
        <div className="p-5 sm:p-6"><ErrorState message={getErrorMessage(agentsQuery.error, "Could not load group agents.")} onRetry={() => void agentsQuery.refetch()} /></div>
      ) : agents.length === 0 ? (
        <EmptyState icon={<Bot className="h-5 w-5" />} title="No AI agents assigned yet" description={isAdmin ? "Add a specialized agent template to give this group an AI teammate." : "A group admin can add specialized AI agents to this workspace."} action={isAdmin && <Button onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add first agent</Button>} />
      ) : (
        <div className="grid gap-3 p-5 sm:grid-cols-2 sm:p-6 xl:grid-cols-3">
          {agents.map((agent) => (
            <Card key={agent.agent_id} className="p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><Bot className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1"><h3 className="truncate text-sm font-semibold text-slate-900">{agent.name}</h3><p className="mt-0.5 truncate text-xs capitalize text-slate-400">{agent.template_id.replaceAll("_", " ")} template</p></div>
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${agent.enabled ? "bg-emerald-500" : "bg-slate-300"}`} title={agent.enabled ? "Enabled" : "Disabled"} />
              </div>
              <p className="mt-3 line-clamp-3 min-h-[3.75rem] text-xs leading-5 text-slate-500">{agent.description}</p>
              <div className="mt-3 flex min-h-6 flex-wrap gap-1.5">
                {agent.capabilities.map((capability) => <span key={capability} className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-600">{capability.replaceAll("_", " ")}</span>)}
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                <span className={`text-xs font-medium ${agent.enabled ? "text-emerald-700" : "text-slate-500"}`}>{agent.enabled ? "Enabled" : "Disabled"}</span>
                {isAdmin && <div className="flex gap-1">
                  <Button type="button" size="sm" variant="outline" aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`} onClick={() => statusMutation.mutate({ agentId: agent.agent_id, enabled: !agent.enabled })} disabled={statusMutation.isPending}>
                    {statusMutation.isPending ? <Spinner /> : <Power className="h-3.5 w-3.5" />}{agent.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button type="button" size="icon" variant="ghost" aria-label={`Remove ${agent.name}`} onClick={() => setConfirmAgent(agent)}><Trash2 className="h-4 w-4 text-slate-400 hover:text-rose-600" /></Button>
                </div>}
              </div>
            </Card>
          ))}
        </div>
      )}
      {!agentsQuery.isPending && !agentsQuery.isError && (
        <div className="flex items-start gap-2 border-t border-slate-100 px-5 py-3 text-xs leading-5 text-slate-500 sm:px-6">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" />
          Disabled agents remain configured but aren’t invoked. Template definitions are global; these listed agents are specific to this group.
        </div>
      )}
      <AddAgentModal
        open={addOpen}
        onOpenChange={setAddOpen}
        templates={availableTemplates}
        isLoading={templatesQuery.isPending}
        error={templatesQuery.isError ? getErrorMessage(templatesQuery.error, "Could not load agent templates.") : null}
        onRetry={() => void templatesQuery.refetch()}
        groupId={groupId}
      />
      <ConfirmationDialog
        open={Boolean(confirmAgent)}
        onOpenChange={(open) => { if (!open) { setConfirmAgent(null); removeMutation.reset(); } }}
        title="Remove this agent?"
        description={`Remove ${confirmAgent?.name ?? "this agent"} from the group? Historical messages will remain. This action disables the agent and hides it from active assignments.`}
        confirmLabel="Remove agent"
        pending={removeMutation.isPending}
        onConfirm={() => confirmAgent && removeMutation.mutate(confirmAgent)}
      />
    </>
  );
}

function AddAgentModal({
  open,
  onOpenChange,
  templates,
  isLoading,
  error,
  onRetry,
  groupId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templates: AgentTemplate[];
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  groupId: string;
}) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const mutation = useMutation({
    mutationFn: () => agentsApi.addToGroup(groupId, selectedId),
    onSuccess: async (agent) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["groups", groupId, "agents"] }),
        queryClient.invalidateQueries({ queryKey: ["groups", groupId] }),
      ]);
      toast({ variant: "success", title: "AI agent added", description: `${agent.name} is now assigned to this group.` });
      setSelectedId("");
      onOpenChange(false);
    },
  });

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Add an AI agent" description="Choose a reusable template. The backend creates an independent agent configuration for this group.">
      <div className="space-y-4">
        {mutation.isError && <ErrorState message={getErrorMessage(mutation.error, "Could not add the agent.")} />}
        {error ? <ErrorState message={error} onRetry={onRetry} /> : isLoading ? <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> : templates.length === 0 ? <EmptyState icon={<Check className="h-5 w-5" />} title="All templates are assigned" description="Each group can have one active agent per template." className="py-6" /> : (
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {templates.map((template) => (
              <button key={template.template_id} type="button" onClick={() => setSelectedId(template.template_id)} className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition ${selectedId === template.template_id ? "border-brand-300 bg-brand-50/60" : "border-slate-200 hover:bg-slate-50"}`}>
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-brand-600"><Bot className="h-4 w-4" /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-800">{template.name}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{template.description}</span></span>
                {selectedId === template.template_id && <Check className="mt-1 h-4 w-4 shrink-0 text-brand-600" />}
              </button>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="button" disabled={!selectedId || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending && <Spinner />} Add agent</Button>
        </div>
      </div>
    </Modal>
  );
}
