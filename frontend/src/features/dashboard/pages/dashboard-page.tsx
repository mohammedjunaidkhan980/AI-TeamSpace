import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bot,
  Clock3,
  Plus,
  Sparkles,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { agentsApi } from "../../../services/api/agents-api";
import { groupsApi } from "../../../services/api/groups-api";
import { useAuthStore } from "../../../stores/auth-store";
import { cn } from "../../../utils/cn";
import { getErrorMessage } from "../../../utils/errors";
import { CreateGroupModal } from "../../groups/components/create-group-modal";

const avatarColors = [
  "bg-violet-100 text-violet-700",
  "bg-sky-100 text-sky-700",
  "bg-amber-100 text-amber-700",
  "bg-emerald-100 text-emerald-700",
];

export function DashboardPage() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const [createOpen, setCreateOpen] = useState(false);
  const groupsQuery = useQuery({ queryKey: ["groups"], queryFn: groupsApi.list });
  const groups = groupsQuery.data?.items ?? [];
  const agentQueries = useQueries({
    queries: groups.map((group) => ({
      queryKey: ["groups", group.group_id, "agents"],
      queryFn: () => agentsApi.groupAgents(group.group_id),
      enabled: Boolean(group.group_id),
    })),
  });

  const agentCounts = new Map(
    groups.map((group, index) => [
      group.group_id,
      agentQueries[index]?.data?.filter((agent) => agent.enabled).length ?? null,
    ]),
  );

  return (
    <>
      <section className="relative mb-8 overflow-hidden rounded-2xl border border-slate-200 bg-white px-6 py-7 shadow-panel sm:px-8 sm:py-9">
        <div className="absolute -right-14 -top-20 h-64 w-64 rounded-full border border-brand-100" />
        <div className="absolute -right-2 -top-8 h-44 w-44 rounded-full border border-brand-100/70" />
        <div className="relative z-10 max-w-2xl">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
            <Sparkles className="h-3.5 w-3.5" /> Your workspace, at a glance
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">
            Welcome back, {user?.full_name?.split(" ")[0] ?? "there"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-500 sm:text-base">Your collaborative AI workspace.</p>
        </div>
      </section>

      <section className="mb-8 grid gap-3 sm:grid-cols-3">
        <QuickAction icon={<Plus />} title="Create a group" description="Bring a team together" onClick={() => setCreateOpen(true)} />
        <QuickAction icon={<UserPlus />} title="Find teammates" description="Connect with people" onClick={() => navigate("/connections")} />
        <QuickAction icon={<Bot />} title="Explore AI agents" description="Meet your AI teammates" onClick={() => navigate("/agents")} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.8fr)]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-slate-900">My groups</h2>
              <p className="mt-1 text-sm text-slate-500">The teams and projects you’re part of.</p>
            </div>
            <Link to="/groups" className="inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700">View all <ArrowUpRight className="h-4 w-4" /></Link>
          </CardHeader>
          <CardContent>
            {groupsQuery.isPending ? (
              <div className="grid gap-3 sm:grid-cols-2">{[1, 2].map((item) => <Skeleton key={item} className="h-32" />)}</div>
            ) : groupsQuery.isError ? (
              <ErrorState message={getErrorMessage(groupsQuery.error, "Could not load groups.")} onRetry={() => void groupsQuery.refetch()} />
            ) : groups.length === 0 ? (
              <EmptyState
                icon={<UsersRound className="h-5 w-5" />}
                title="Your workspace starts here."
                description="Create a group and bring your teammates and AI agents together."
                action={<Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create your first group</Button>}
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {groups.slice(0, 4).map((group, index) => (
                  <Link key={group.group_id} to={`/groups/${group.group_id}`} className="group rounded-xl border border-slate-200 p-4 transition hover:border-brand-200 hover:shadow-sm">
                    <div className="flex items-start gap-3">
                      <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold", avatarColors[index % avatarColors.length])}>{group.name.slice(0, 1).toUpperCase()}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <h3 className="truncate text-sm font-semibold text-slate-900 group-hover:text-brand-700">{group.name}</h3>
                          <ArrowUpRight className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-brand-600" />
                        </div>
                        <p className="mt-1 line-clamp-2 min-h-10 text-xs leading-5 text-slate-500">{group.description || "A shared space for your team’s work."}</p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
                      <span className="inline-flex items-center gap-1.5"><UsersRound className="h-3.5 w-3.5" />{group.member_count} members</span>
                      <span className="inline-flex items-center gap-1.5" title={agentQueries[index]?.isError ? "Agent count unavailable" : undefined}><Bot className="h-3.5 w-3.5" />{agentQueries[index]?.isPending ? "…" : agentQueries[index]?.isError ? "Unavailable" : agentCounts.get(group.group_id)} agents</span>
                      {group.last_message_at && <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" />{new Date(group.last_message_at).toLocaleDateString()}</span>}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <h2 className="text-base font-semibold text-slate-900">Recent activity</h2>
            <p className="mt-1 text-sm text-slate-500">A snapshot of what’s moving.</p>
          </CardHeader>
          <CardContent>
            {groups.some((group) => group.last_message_at) ? (
              <ul className="space-y-4">
                {groups.filter((group) => group.last_message_at).sort((a, b) => new Date(b.last_message_at!).getTime() - new Date(a.last_message_at!).getTime()).slice(0, 4).map((group) => (
                  <li key={group.group_id} className="flex gap-3">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
                    <div>
                      <Link to={`/groups/${group.group_id}`} className="text-sm font-medium text-slate-800 hover:text-brand-700">{group.name}</Link>
                      <p className="mt-0.5 text-xs text-slate-500">Latest message {new Date(group.last_message_at!).toLocaleString()}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={<Clock3 className="h-5 w-5" />} title="No recent activity yet" description="Group activity will appear here when the backend provides it." className="py-8" />
            )}
          </CardContent>
        </Card>
      </section>
      <CreateGroupModal open={createOpen} onOpenChange={setCreateOpen} onCreated={(group) => navigate(`/groups/${group.group_id}`)} />
    </>
  );
}

function QuickAction({ icon, title, description, onClick }: { icon: React.ReactNode; title: string; description: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-panel transition hover:-translate-y-0.5 hover:border-brand-200">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-100">{icon}</span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-slate-900">{title}</span>
        <span className="mt-1 block text-xs text-slate-500">{description}</span>
      </span>
      <ArrowUpRight className="ml-auto h-4 w-4 shrink-0 text-slate-300 group-hover:text-brand-600" />
    </button>
  );
}
