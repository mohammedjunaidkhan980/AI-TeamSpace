import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, UserPlus, UsersRound } from "lucide-react";
import { useState } from "react";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { ErrorState } from "../../../components/ui/error-state";
import { Modal } from "../../../components/ui/modal";
import { Spinner } from "../../../components/ui/spinner";
import { toast } from "../../../components/ui/toaster";
import { connectionsApi } from "../../../services/api/connections-api";
import { groupsApi } from "../../../services/api/groups-api";
import { getErrorMessage } from "../../../utils/errors";

interface AddGroupMembersModalProps {
  groupId: string;
  existingMemberIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddGroupMembersModal({
  groupId,
  existingMemberIds,
  open,
  onOpenChange,
}: AddGroupMembersModalProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: connectionsApi.list,
    enabled: open,
  });
  const availableConnections = connectionsQuery.data?.items.filter(
    (person) => !existingMemberIds.includes(person.id),
  ) ?? [];
  const mutation = useMutation({
    mutationFn: () => groupsApi.addMembers(groupId, selectedIds),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["groups", groupId] }),
        queryClient.invalidateQueries({ queryKey: ["groups"] }),
        queryClient.invalidateQueries({ queryKey: ["connections"] }),
      ]);
      toast({
        variant: "success",
        title: result.members.length === 1 ? "Member added" : "Members added",
        description: `${result.members.length} teammate${result.members.length === 1 ? "" : "s"} added to the group.`,
      });
      setSelectedIds([]);
      onOpenChange(false);
    },
  });

  function toggle(id: string) {
    setSelectedIds((ids) => ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id]);
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Add members" description="Only your accepted connections can be added to this group.">
      <div className="space-y-4">
        {mutation.isError && <ErrorState message={getErrorMessage(mutation.error, "Could not add group members.")} />}
        {connectionsQuery.isPending ? (
          <p className="py-6 text-center text-sm text-slate-500">Loading your connections…</p>
        ) : connectionsQuery.isError ? (
          <ErrorState message={getErrorMessage(connectionsQuery.error, "Could not load connections.")} onRetry={() => void connectionsQuery.refetch()} />
        ) : availableConnections.length === 0 ? (
          <div className="py-5"><div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><UsersRound className="h-5 w-5" /></div><p className="mt-3 text-center text-sm font-medium text-slate-800">No available connections</p><p className="mt-1 text-center text-xs text-slate-500">Connect with teammates first, or everyone you’re connected to is already here.</p></div>
        ) : (
          <ul className="max-h-72 overflow-y-auto rounded-xl border border-slate-200">
            {availableConnections.map((person) => {
              const checked = selectedIds.includes(person.id);
              return (
                <li key={person.id}>
                  <button type="button" onClick={() => toggle(person.id)} className="flex w-full items-center gap-3 border-b border-slate-100 px-3 py-2.5 text-left last:border-0 hover:bg-slate-50">
                    <Avatar name={person.full_name} src={person.profile_picture_url} className="h-9 w-9" />
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-slate-800">{person.full_name}</span><span className="text-xs text-slate-400">@{person.username}</span></span>
                    <span className={`flex h-5 w-5 items-center justify-center rounded-md border ${checked ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 text-transparent"}`}><Check className="h-3 w-3" /></span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="button" disabled={!selectedIds.length || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? <Spinner /> : <UserPlus className="h-4 w-4" />} Add {selectedIds.length || ""}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
