import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Crown, MoreHorizontal, Shield, UserPlus, UserRound, UserRoundX } from "lucide-react";
import { useState } from "react";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { Dropdown, DropdownItem } from "../../../components/ui/dropdown";
import type { GroupDetails, GroupMember } from "../../../types/api";
import { toast } from "../../../components/ui/toaster";
import { groupsApi } from "../../../services/api/groups-api";
import { useAuthStore } from "../../../stores/auth-store";
import { getErrorMessage } from "../../../utils/errors";
import { AddGroupMembersModal } from "./add-group-members-modal";

interface GroupMembersPanelProps {
  group: GroupDetails;
  currentUserId: string;
  isAdmin: boolean;
}

export function GroupMembersPanel({ group, currentUserId, isAdmin }: GroupMembersPanelProps) {
  const currentUserEmail = useAuthStore((state) => state.user?.email);
  const [addOpen, setAddOpen] = useState(false);
  const [confirm, setConfirm] = useState<{ member: GroupMember; action: "remove" | "promote" | "demote" } | null>(null);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async () => {
      if (!confirm) return;
      if (confirm.action === "remove") return groupsApi.removeMember(group.group_id, confirm.member.user.id);
      if (confirm.action === "promote") return groupsApi.promoteAdmin(group.group_id, confirm.member.user.id);
      return groupsApi.demoteAdmin(group.group_id, confirm.member.user.id);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["groups", group.group_id] }),
        queryClient.invalidateQueries({ queryKey: ["groups"] }),
      ]);
      const action = confirm?.action;
      toast({
        variant: "success",
        title: action === "remove" ? "Member removed" : action === "promote" ? "Admin role updated" : "Admin role removed",
      });
      setConfirm(null);
    },
  });

  const existingMemberIds = group.members.map((member) => member.user.id);

  return (
    <>
      <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div><h2 className="text-sm font-semibold text-slate-900">Group members <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">{group.member_count}</span></h2><p className="mt-1 text-xs text-slate-500">Member emails aren’t included in the backend’s group profile response.</p></div>
        {isAdmin && <Button size="sm" onClick={() => setAddOpen(true)}><UserPlus className="h-4 w-4" /> Add members</Button>}
      </div>
      {mutation.isError && <div className="px-5 pt-4 sm:px-6"><p role="alert" className="text-sm text-rose-700">{getErrorMessage(mutation.error, "Could not update group membership.")}</p></div>}
      {group.members.length === 0 ? (
        <EmptyState icon={<UserRound className="h-5 w-5" />} title="No members found" description="Group members will appear here." />
      ) : (
        <ul className="divide-y divide-slate-100 px-5 sm:px-6">
          {group.members.map((member) => {
            const isSelf = member.user.id === currentUserId;
            const isCreator = member.user.id === group.creator_id;
            const roleAction = member.role === "admin" ? "demote" : "promote";
            return (
              <li key={member.user.id} className="flex min-w-0 items-center gap-3 py-4">
                <Avatar name={member.user.full_name} src={member.user.profile_picture_url} className="h-10 w-10" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-semibold text-slate-900">{member.user.full_name}{isSelf && <span className="ml-1 font-normal text-slate-400">(you)</span>}</p>
                    {isCreator && <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700"><Crown className="h-3 w-3" /> Creator</span>}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-slate-500">{isSelf && currentUserEmail ? currentUserEmail : `@${member.user.username}`}</p>
                </div>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${member.role === "admin" ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-600"}`}>
                  {member.role === "admin" ? <Shield className="h-3.5 w-3.5" /> : <UserRound className="h-3.5 w-3.5" />}
                  {member.role}
                </span>
                {isAdmin && !isCreator && !isSelf && (
                  <Dropdown label={`Actions for ${member.user.full_name}`} trigger={<Button type="button" variant="ghost" size="icon" aria-label={`Actions for ${member.user.full_name}`}><MoreHorizontal className="h-4 w-4" /></Button>}>
                    <DropdownItem onClick={() => setConfirm({ member, action: roleAction })}>{roleAction === "promote" ? "Promote to admin" : "Remove admin role"}</DropdownItem>
                    <DropdownItem destructive onClick={() => setConfirm({ member, action: "remove" })}><UserRoundX className="mr-2 h-4 w-4" />Remove from group</DropdownItem>
                  </Dropdown>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <AddGroupMembersModal groupId={group.group_id} existingMemberIds={existingMemberIds} open={addOpen} onOpenChange={setAddOpen} />
      <ConfirmationDialog
        open={Boolean(confirm)}
        onOpenChange={(open) => { if (!open) { setConfirm(null); mutation.reset(); } }}
        title={confirm?.action === "remove" ? "Remove group member?" : confirm?.action === "promote" ? "Promote to admin?" : "Remove admin role?"}
        description={confirm?.action === "remove" ? `${confirm.member.user.full_name} will lose access to this group.` : confirm?.action === "promote" ? `${confirm?.member.user.full_name} will be able to manage this group.` : `${confirm?.member.user.full_name} will no longer be able to manage this group.`}
        confirmLabel={confirm?.action === "remove" ? "Remove member" : confirm?.action === "promote" ? "Promote" : "Remove role"}
        pending={mutation.isPending}
        onConfirm={() => mutation.mutate()}
      />
    </>
  );
}
