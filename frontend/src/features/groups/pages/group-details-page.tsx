import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, ChevronRight, UsersRound } from "lucide-react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Avatar } from "../../../components/ui/avatar";
import { Card } from "../../../components/ui/card";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { groupsApi } from "../../../services/api/groups-api";
import { useAuthStore } from "../../../stores/auth-store";
import { getErrorMessage } from "../../../utils/errors";
import { GroupAgentsPanel } from "../components/group-agents-panel";
import { GroupChatPanel } from "../components/group-chat-panel";
import { GroupDocumentsPanel } from "../components/group-documents-panel";
import { GroupMembersPanel } from "../components/group-members-panel";
import { GroupOverviewPanel } from "../components/group-overview-panel";
import { GroupSettingsPanel } from "../components/group-settings-panel";
import { GroupTabs, type GroupTab } from "../components/group-tabs";

const validTabs = new Set<GroupTab>(["overview", "chat", "members", "agents", "documents", "settings"]);

export function GroupDetailsPage() {
  const { groupId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const currentUserId = useAuthStore((state) => state.user?.id) ?? "";
  const query = useQuery({
    queryKey: ["groups", groupId],
    queryFn: () => groupsApi.get(groupId),
    enabled: Boolean(groupId),
  });
  const group = query.data;
  const requestedTab = searchParams.get("tab") as GroupTab | null;
  const activeTab = location.pathname.endsWith("/chat")
    ? "chat"
    : requestedTab && validTabs.has(requestedTab)
      ? requestedTab
      : "overview";
  const currentMember = group?.members.find((member) => member.user.id === currentUserId);
  const isAdmin = currentMember?.role === "admin";

  if (query.isPending) {
    return <div className="space-y-5"><Skeleton className="h-28" /><Skeleton className="h-12" /><Skeleton className="h-72" /></div>;
  }
  if (query.isError || !group) {
    return <ErrorState message={getErrorMessage(query.error, "Could not load this group.")} onRetry={() => void query.refetch()} />;
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm text-slate-500">
        <Link to="/groups" className="inline-flex items-center gap-1.5 hover:text-slate-900"><ArrowLeft className="h-4 w-4" /> Groups</Link>
        <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
        <span className="truncate font-medium text-slate-700">{group.name}</span>
      </nav>

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-4 p-4 sm:gap-5 sm:p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar name={group.name} src={group.group_picture_url} className="h-14 w-14 rounded-2xl text-lg" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-semibold tracking-tight text-slate-950 sm:text-2xl">{group.name}</h1>
                <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold capitalize ${isAdmin ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-600"}`}>{currentMember?.role ?? "member"}</span>
              </div>
              <p className="mt-1 max-w-2xl truncate text-sm text-slate-500">{group.description || "A shared space for your team’s work."}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pl-[64px] text-sm text-slate-500 sm:shrink-0 sm:pl-0">
            <span className="inline-flex items-center gap-2"><UsersRound className="h-4 w-4 text-slate-400" />{group.member_count} members</span>
            <span className="inline-flex items-center gap-2"><Bot className="h-4 w-4 text-brand-500" />{group.ai_agents.length} agents</span>
          </div>
        </div>
        <GroupTabs groupId={group.group_id} />
      </Card>

      {activeTab === "overview" && <GroupOverviewPanel group={group} currentUserId={currentUserId} />}
      {activeTab === "chat" && <GroupChatPanel group={group} />}
      {activeTab === "members" && <Card className="overflow-hidden"><GroupMembersPanel group={group} currentUserId={currentUserId} isAdmin={isAdmin} /></Card>}
      {activeTab === "agents" && <Card className="overflow-hidden"><GroupAgentsPanel groupId={group.group_id} isAdmin={isAdmin} /></Card>}
      {activeTab === "documents" && <GroupDocumentsPanel group={group} />}
      {activeTab === "settings" && <GroupSettingsPanel group={group} isAdmin={isAdmin} />}
    </div>
  );
}
