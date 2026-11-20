import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Plus, Search, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { PageHeader } from "../../../components/shared/page-header";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Input } from "../../../components/ui/input";
import { Skeleton } from "../../../components/ui/skeleton";
import { groupsApi } from "../../../services/api/groups-api";
import { getErrorMessage } from "../../../utils/errors";
import { CreateGroupModal } from "../components/create-group-modal";

export function GroupsPage() {
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ["groups"], queryFn: groupsApi.list });

  useEffect(() => {
    if ((location.state as { openCreate?: boolean } | null)?.openCreate) {
      setCreateOpen(true);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location, navigate]);

  const groups = query.data?.items.filter((group) =>
    `${group.name} ${group.description ?? ""}`.toLowerCase().includes(search.toLowerCase()),
  ) ?? [];

  return (
    <>
      <PageHeader title="My groups" description="Shared spaces for the people and projects you work with." action={<Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create group</Button>} />
      <div className="mb-5 max-w-sm">
        <span className="relative block"><Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search groups" aria-label="Search groups" className="pl-10" /></span>
      </div>
      {query.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[1, 2, 3].map((item) => <Skeleton className="h-44" key={item} />)}</div>
      ) : query.isError ? (
        <ErrorState message={getErrorMessage(query.error, "Could not load groups.")} onRetry={() => void query.refetch()} />
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState
            icon={<UsersRound className="h-5 w-5" />}
            title={search ? "No groups found" : "Your workspace starts here."}
            description={search ? "Try a different search term." : "Create a group and bring your teammates and AI agents together."}
            action={!search && <Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create your first group</Button>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Link key={group.group_id} to={`/groups/${group.group_id}`} className="group">
              <Card className="h-full p-5 transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md">
                <div className="flex items-start gap-3">
                  <Avatar name={group.name} className="h-11 w-11 rounded-xl" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <h2 className="truncate font-semibold text-slate-900 group-hover:text-brand-700">{group.name}</h2>
                      <ArrowUpRight className="h-4 w-4 shrink-0 text-slate-300 group-hover:text-brand-600" />
                    </div>
                    <p className="mt-1 text-xs capitalize text-slate-400">{group.current_user_role} · created {new Date(group.created_at).toLocaleDateString()}</p>
                  </div>
                </div>
                <p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">{group.description || "A shared space for your team’s work."}</p>
                <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-4 text-xs text-slate-500">
                  <UsersRound className="h-4 w-4" /> {group.member_count} members
                  {group.last_message_at && <span className="ml-auto">Active {new Date(group.last_message_at).toLocaleDateString()}</span>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
      <CreateGroupModal open={createOpen} onOpenChange={setCreateOpen} onCreated={(group) => navigate(`/groups/${group.group_id}`)} />
    </>
  );
}
