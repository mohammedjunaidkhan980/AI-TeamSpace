import { useQuery } from "@tanstack/react-query";
import { Bot, Clock3, MessageSquare, UsersRound } from "lucide-react";
import { Card, CardContent, CardHeader } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { groupsApi } from "../../../services/api/groups-api";
import type { GroupDetails } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";

export function GroupOverviewPanel({ group, currentUserId }: { group: GroupDetails; currentUserId: string }) {
  const statsQuery = useQuery({
    queryKey: ["groups", group.group_id, "message-stats"],
    queryFn: () => groupsApi.messageStats(group.group_id),
  });

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(280px,0.7fr)]">
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-slate-900">Workspace activity</h2><p className="mt-1 text-xs text-slate-500">A summary based on the messages currently stored for this group.</p></CardHeader>
        <CardContent>
          {statsQuery.isPending ? <div className="grid gap-3 sm:grid-cols-2">{[1, 2, 3, 4].map((item) => <Skeleton className="h-20" key={item} />)}</div> :
            statsQuery.isError ? <ErrorState message={getErrorMessage(statsQuery.error, "Could not load group activity.")} onRetry={() => void statsQuery.refetch()} /> :
            statsQuery.data.total_message_count === 0 ? <EmptyState icon={<MessageSquare className="h-5 w-5" />} title="No messages yet" description="Message activity will appear here when the group has conversations." className="py-9" /> :
            <div className="grid gap-3 sm:grid-cols-2">
              <Stat icon={<MessageSquare />} label="Messages" value={statsQuery.data.total_message_count} />
              <Stat icon={<UsersRound />} label="Human messages" value={statsQuery.data.human_message_count} />
              <Stat icon={<Bot />} label="AI messages" value={statsQuery.data.ai_message_count} />
              <Stat icon={<Clock3 />} label="Latest message" value={statsQuery.data.latest_message_at ? new Date(statsQuery.data.latest_message_at).toLocaleString() : "—"} />
            </div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-slate-900">About this group</h2></CardHeader>
        <CardContent className="space-y-4">
          <Info label="Created" value={new Date(group.created_at).toLocaleDateString()} />
          <Info label="Your role" value={group.members.find((member) => member.user.id === currentUserId)?.role ?? "Member"} capitalize />
          <Info label="Members" value={group.member_count} />
          <Info label="AI agents" value={group.ai_agents.length} />
          <Info label="Chat channel" value={group.nexconn_sync_status === "synced" ? "Connected" : group.nexconn_sync_status} capitalize />
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-4"><div className="flex items-center gap-2 text-xs font-medium text-slate-500">{icon}{label}</div><p className="mt-2 text-xl font-semibold tracking-tight text-slate-900">{value}</p></div>;
}

function Info({ label, value, capitalize = false }: { label: string; value: string | number; capitalize?: boolean }) {
  return <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3 last:border-0 last:pb-0"><span className="text-xs text-slate-500">{label}</span><span className={`truncate text-xs font-semibold text-slate-800 ${capitalize ? "capitalize" : ""}`}>{value}</span></div>;
}
