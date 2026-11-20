import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, LogOut, Save, Shield, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../../components/ui/card";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { ErrorState } from "../../../components/ui/error-state";
import { Input } from "../../../components/ui/input";
import { Spinner } from "../../../components/ui/spinner";
import { toast } from "../../../components/ui/toaster";
import { useAuthStore } from "../../../stores/auth-store";
import type { GroupDetails } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { groupsApi } from "../../../services/api/groups-api";

export function GroupSettingsPanel({ group, isAdmin }: { group: GroupDetails; isAdmin: boolean }) {
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description ?? "");
  const [pictureUrl, setPictureUrl] = useState(group.group_picture_url ?? "");
  const [confirmLeave, setConfirmLeave] = useState(false);
  const currentUserId = useAuthStore((state) => state.user?.id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const updateMutation = useMutation({
    mutationFn: () => groupsApi.update(group.group_id, {
      name: name.trim(),
      description: description.trim() || null,
      group_picture_url: pictureUrl.trim() || null,
    }),
    onSuccess: async (updated) => {
      queryClient.setQueryData(["groups", group.group_id], updated);
      await queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast({ variant: "success", title: "Group settings saved" });
    },
  });
  const leaveMutation = useMutation({
    mutationFn: () => groupsApi.removeMember(group.group_id, currentUserId!),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["groups"] });
      toast({ variant: "success", title: "You left the group" });
      navigate("/groups", { replace: true });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateMutation.mutate();
  }

  const isCreator = currentUserId === group.creator_id;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(260px,0.6fr)]">
      <Card>
        <CardHeader><div className="flex items-center gap-2"><Shield className="h-4 w-4 text-brand-600" /><div><h2 className="text-sm font-semibold text-slate-900">Group profile</h2><p className="mt-1 text-xs text-slate-500">{isAdmin ? "Changes are visible to all group members." : "Only group admins can edit these settings."}</p></div></div></CardHeader>
        <CardContent>
          {updateMutation.isError && <div className="mb-4"><ErrorState message={getErrorMessage(updateMutation.error, "Could not update group settings.")} /></div>}
          <form onSubmit={submit} className="space-y-5">
            <label className="block space-y-2 text-sm font-medium text-slate-700">Group name
              <Input required minLength={1} maxLength={100} value={name} onChange={(event) => setName(event.target.value)} disabled={!isAdmin} />
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Description
              <textarea rows={4} maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} disabled={!isAdmin} className="w-full resize-none rounded-xl border border-slate-200 px-3.5 py-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100 disabled:bg-slate-50 disabled:text-slate-500" />
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Group image URL <span className="font-normal text-slate-400">(optional)</span>
              <Input type="url" maxLength={2048} value={pictureUrl} onChange={(event) => setPictureUrl(event.target.value)} disabled={!isAdmin} placeholder="https://example.com/group-image.png" />
              <span className="block text-xs font-normal text-slate-400">Image URLs are supported by the group profile API. File upload is not available.</span>
            </label>
            {isAdmin && <div className="flex justify-end"><Button type="submit" disabled={updateMutation.isPending || !name.trim()}>{updateMutation.isPending ? <Spinner /> : <Save className="h-4 w-4" />} Save changes</Button></div>}
          </form>
        </CardContent>
      </Card>
      <div className="space-y-5">
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-slate-900">Membership</h2><p className="mt-1 text-xs text-slate-500">Leave this group to remove it from your workspace.</p></CardHeader>
          <CardContent>
            {isCreator ? (
              <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-800"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />The group creator cannot leave or be removed. Transfer ownership isn’t available in the backend.</div>
            ) : (
              <>
                {leaveMutation.isError && <div className="mb-3"><ErrorState message={getErrorMessage(leaveMutation.error, "Could not leave this group.")} /></div>}
                <Button variant="outline" className="w-full" onClick={() => setConfirmLeave(true)}><LogOut className="h-4 w-4" /> Leave group</Button>
              </>
            )}
          </CardContent>
        </Card>
        <Card className="border-rose-100">
          <CardHeader><h2 className="text-sm font-semibold text-slate-900">Delete group</h2></CardHeader>
          <CardContent>
            <p className="mb-3 text-xs leading-5 text-slate-500">The backend does not provide a group deletion endpoint. Ask a backend administrator if this group needs removal.</p>
            <Button type="button" variant="outline" className="w-full cursor-not-allowed text-slate-400" disabled><Trash2 className="h-4 w-4" /> Delete unavailable</Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-slate-900">Group access</h2></CardHeader>
          <CardContent className="space-y-3 text-xs text-slate-500">
            <p>Visibility is not configurable through the current backend API.</p>
            <p>Role: <span className="font-semibold capitalize text-slate-800">{group.members.find((member) => member.user.id === currentUserId)?.role ?? "member"}</span></p>
            <p className="break-all font-mono text-[10px]">{group.group_id}</p>
          </CardContent>
        </Card>
      </div>
      <ConfirmationDialog
        open={confirmLeave}
        onOpenChange={(open) => { setConfirmLeave(open); if (!open) leaveMutation.reset(); }}
        title="Leave this group?"
        description="You will lose access to this group and its workspace. You can be added back by a group admin."
        confirmLabel="Leave group"
        pending={leaveMutation.isPending}
        onConfirm={() => leaveMutation.mutate()}
      />
    </div>
  );
}
