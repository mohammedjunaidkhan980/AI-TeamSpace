import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, UsersRound } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Modal } from "../../../components/ui/modal";
import { Spinner } from "../../../components/ui/spinner";
import { connectionsApi } from "../../../services/api/connections-api";
import { groupsApi } from "../../../services/api/groups-api";
import type { GroupDetails } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { Avatar } from "../../../components/ui/avatar";
import { toast } from "../../../components/ui/toaster";

interface CreateGroupModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (group: GroupDetails) => void;
}

export function CreateGroupModal({ open, onOpenChange, onCreated }: CreateGroupModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: connectionsApi.list,
    enabled: open,
  });
  const mutation = useMutation({
    mutationFn: groupsApi.create,
    onSuccess: async (group) => {
      await queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast({ variant: "success", title: "Group created", description: `${group.name} is ready for your team.` });
      onOpenChange(false);
      setName("");
      setDescription("");
      setSelectedIds([]);
      onCreated?.(group);
    },
  });

  useEffect(() => {
    if (!open) mutation.reset();
  }, [open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ name: name.trim(), description: description.trim() || null, member_ids: selectedIds });
  }

  function toggleMember(id: string) {
    setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Create a group" description="Start a shared workspace and bring connected teammates in.">
      <form className="space-y-5" onSubmit={submit}>
        {mutation.isError && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800">{getErrorMessage(mutation.error, "Could not create the group.")}</p>}
        <label className="block space-y-2 text-sm font-medium text-slate-700">Group name
          <Input required minLength={1} maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Product launch" />
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Description <span className="font-normal text-slate-400">(optional)</span>
          <textarea maxLength={1000} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What will this group work on?" className="w-full resize-none rounded-xl border border-slate-200 px-3.5 py-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100" />
        </label>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-sm font-medium text-slate-700">Invite connected teammates</label>
            <span className="text-xs text-slate-400">{selectedIds.length} selected</span>
          </div>
          <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-200">
            {connectionsQuery.isPending ? (
              <p className="p-4 text-sm text-slate-500">Loading connections…</p>
            ) : connectionsQuery.isError ? (
              <p className="p-4 text-sm text-rose-700">Could not load connections: {getErrorMessage(connectionsQuery.error)}</p>
            ) : connectionsQuery.data.items.length === 0 ? (
              <div className="p-4 text-center">
                <UsersRound className="mx-auto h-5 w-5 text-slate-400" />
                <p className="mt-2 text-sm text-slate-500">No connections yet. You can invite people later.</p>
              </div>
            ) : connectionsQuery.data.items.map((person) => {
              const checked = selectedIds.includes(person.id);
              return (
                <button key={person.id} type="button" onClick={() => toggleMember(person.id)} className="flex w-full items-center gap-3 border-b border-slate-100 px-3 py-2.5 text-left last:border-0 hover:bg-slate-50">
                  <Avatar name={person.full_name} src={person.profile_picture_url} className="h-8 w-8 text-xs" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-slate-800">{person.full_name}</span>
                    <span className="block text-xs text-slate-400">@{person.username}</span>
                  </span>
                  <span className={`flex h-5 w-5 items-center justify-center rounded-md border ${checked ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 text-transparent"}`}><Check className="h-3 w-3" /></span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" disabled={mutation.isPending || !name.trim()}>{mutation.isPending && <Spinner />} Create group</Button>
        </div>
      </form>
    </Modal>
  );
}
