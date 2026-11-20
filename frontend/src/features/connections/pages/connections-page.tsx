import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, Search, Trash2, UserPlus, UsersRound, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Input } from "../../../components/ui/input";
import { PageHeader } from "../../../components/shared/page-header";
import { Skeleton } from "../../../components/ui/skeleton";
import { toast } from "../../../components/ui/toaster";
import { connectionsApi } from "../../../services/api/connections-api";
import { usersApi } from "../../../services/api/users-api";
import { useAuthStore } from "../../../stores/auth-store";
import type { PublicUserProfile } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";

type Tab = "discover" | "connections" | "requests";

export function ConnectionsPage() {
  const [tab, setTab] = useState<Tab>("discover");
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [pendingAction, setPendingAction] = useState<{ type: "cancel" | "remove"; id: string; name: string } | null>(null);
  const currentUserId = useAuthStore((state) => state.user?.id);
  const queryClient = useQueryClient();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const searchQuery = useQuery({
    queryKey: ["users", "search", debouncedSearch],
    queryFn: () => usersApi.search(debouncedSearch),
    enabled: tab === "discover" && debouncedSearch.length > 0,
  });
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: connectionsApi.list });
  const incomingQuery = useQuery({ queryKey: ["connections", "incoming"], queryFn: connectionsApi.incoming });
  const outgoingQuery = useQuery({ queryKey: ["connections", "outgoing"], queryFn: connectionsApi.outgoing });

  const sendMutation = useMutation({
    mutationFn: connectionsApi.send,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast({ variant: "success", title: result.status === "accepted" ? "Connection added" : "Request sent", description: result.message });
    },
    onError: (error) => toast({ variant: "error", title: "Could not send request", description: getErrorMessage(error) }),
  });
  const acceptMutation = useMutation({
    mutationFn: connectionsApi.accept,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast({ variant: "success", title: "Request accepted" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not accept request", description: getErrorMessage(error) }),
  });
  const rejectMutation = useMutation({
    mutationFn: connectionsApi.reject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      toast({ variant: "success", title: "Request declined" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not decline request", description: getErrorMessage(error) }),
  });
  const cancelMutation = useMutation({
    mutationFn: connectionsApi.cancel,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      setPendingAction(null);
      toast({ variant: "success", title: "Request cancelled" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not cancel request", description: getErrorMessage(error) }),
  });
  const removeMutation = useMutation({
    mutationFn: connectionsApi.remove,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      setPendingAction(null);
      toast({ variant: "success", title: "Connection removed" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not remove connection", description: getErrorMessage(error) }),
  });

  useEffect(() => {
    const initialSearch = searchParams.get("search");
    if (initialSearch) {
      setSearch(initialSearch);
      setTab("discover");
    } else if (searchParams.get("tab") === "requests") {
      setTab("requests");
    }
  }, [searchParams]);

  const connectionIds = useMemo(() => new Set((connectionsQuery.data?.items ?? []).map((person) => person.id)), [connectionsQuery.data]);
  const outgoingByPerson = useMemo(() => new Map((outgoingQuery.data?.items ?? []).map((request) => [request.recipient.id, request])), [outgoingQuery.data]);
  const incomingByPerson = useMemo(() => new Map((incomingQuery.data?.items ?? []).map((request) => [request.sender.id, request])), [incomingQuery.data]);

  const commonLoading = connectionsQuery.isPending || incomingQuery.isPending || outgoingQuery.isPending;
  const commonError = connectionsQuery.error ?? incomingQuery.error ?? outgoingQuery.error;

  return (
    <>
      <PageHeader title="Connections" description="Find teammates, build your network, and invite people into your groups." />
      <div className="mb-5 flex flex-wrap gap-2">
        <TabButton active={tab === "discover"} onClick={() => setTab("discover")} icon={<Search className="h-4 w-4" />}>Discover</TabButton>
        <TabButton active={tab === "connections"} onClick={() => setTab("connections")} icon={<UsersRound className="h-4 w-4" />}>My connections</TabButton>
        <TabButton active={tab === "requests"} onClick={() => setTab("requests")} icon={<UserPlus className="h-4 w-4" />}>Requests{(incomingQuery.data?.items.length ?? 0) > 0 && <span className="rounded-full bg-brand-100 px-1.5 py-0.5 text-[10px] text-brand-700">{incomingQuery.data?.items.length}</span>}</TabButton>
      </div>

      {tab === "discover" && (
        <section>
          <div className="mb-5 max-w-lg">
            <label htmlFor="teammate-search" className="mb-2 block text-sm font-medium text-slate-700">Search by username or name</label>
            <span className="relative block"><Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input id="teammate-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Try a teammate’s name" className="pl-10" /></span>
          </div>
          {debouncedSearch.length === 0 ? <Card><EmptyState icon={<Search className="h-5 w-5" />} title="Find your people" description="Search for a username or full name to discover teammates." /></Card> :
            searchQuery.isPending || commonLoading ? <div className="grid gap-3 md:grid-cols-2">{[1, 2, 3, 4].map((item) => <Skeleton className="h-24" key={item} />)}</div> :
            searchQuery.isError || commonError ? <ErrorState message={getErrorMessage(searchQuery.error ?? commonError, "Could not search teammates.")} onRetry={() => void searchQuery.refetch()} /> :
            searchQuery.data.items.length === 0 ? <Card><EmptyState title="No teammates found" description="Try searching by another name or username." /></Card> :
            <div className="grid gap-3 md:grid-cols-2">
              {searchQuery.data.items.map((person) => (
                <PersonCard key={person.id} person={person}>
                  {connectionIds.has(person.id) ? <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700"><CheckCheck className="h-4 w-4" /> Connected</span> :
                    outgoingByPerson.has(person.id) ? <span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700">Request sent</span> :
                    incomingByPerson.has(person.id) ? <span className="text-xs text-slate-500">They sent you a request</span> :
                    <Button size="sm" onClick={() => sendMutation.mutate(person.id)} disabled={sendMutation.isPending || person.id === currentUserId}><UserPlus className="h-4 w-4" /> Connect</Button>}
                </PersonCard>
              ))}
            </div>}
        </section>
      )}

      {tab === "connections" && (
        <section>
          {connectionsQuery.isPending ? <Skeleton className="h-48" /> : connectionsQuery.isError ? <ErrorState message={getErrorMessage(connectionsQuery.error)} onRetry={() => void connectionsQuery.refetch()} /> : connectionsQuery.data.items.length === 0 ? <Card><EmptyState icon={<UsersRound className="h-5 w-5" />} title="No connections yet" description="Discover teammates and send your first connection request." action={<Button variant="outline" onClick={() => setTab("discover")}>Find teammates</Button>} /></Card> :
            <div className="grid gap-3 md:grid-cols-2">{connectionsQuery.data.items.map((person) => <PersonCard key={person.id} person={person}><div className="flex items-center gap-2"><span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700"><CheckCheck className="h-4 w-4" /> Connected</span><Button variant="ghost" size="icon" aria-label={`Remove ${person.full_name} from connections`} onClick={() => setPendingAction({ type: "remove", id: person.id, name: person.full_name })}><Trash2 className="h-4 w-4 text-slate-400 hover:text-rose-600" /></Button></div></PersonCard>)}</div>}
        </section>
      )}

      {tab === "requests" && (
        <section className="space-y-6">
          {commonError && <ErrorState message={getErrorMessage(commonError, "Could not load connection requests.")} onRetry={() => { void incomingQuery.refetch(); void outgoingQuery.refetch(); }} />}
          {commonLoading ? <Skeleton className="h-40" /> :
            <>
              <div>
                <h2 className="mb-3 text-sm font-semibold text-slate-800">Incoming</h2>
                {incomingQuery.data?.items.length ? <div className="grid gap-3 md:grid-cols-2">{incomingQuery.data.items.map((request) => <PersonCard key={request.id} person={request.sender}><div className="flex gap-2"><Button size="sm" onClick={() => acceptMutation.mutate(request.id)} disabled={acceptMutation.isPending}><Check className="h-4 w-4" /> Accept</Button><Button size="sm" variant="outline" onClick={() => rejectMutation.mutate(request.id)} disabled={rejectMutation.isPending}><X className="h-4 w-4" /> Decline</Button></div></PersonCard>)}</div> : <p className="rounded-xl border border-dashed border-slate-200 bg-white p-5 text-sm text-slate-500">No incoming requests.</p>}
              </div>
              <div>
                <h2 className="mb-3 text-sm font-semibold text-slate-800">Sent</h2>
                {outgoingQuery.data?.items.length ? <div className="grid gap-3 md:grid-cols-2">{outgoingQuery.data.items.map((request) => <PersonCard key={request.id} person={request.recipient}><div className="flex items-center gap-2"><span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700">Pending</span><Button variant="outline" size="sm" onClick={() => setPendingAction({ type: "cancel", id: request.id, name: request.recipient.full_name })}>Cancel</Button></div></PersonCard>)}</div> : <p className="rounded-xl border border-dashed border-slate-200 bg-white p-5 text-sm text-slate-500">No outgoing requests.</p>}
              </div>
            </>}
        </section>
      )}
      <ConfirmationDialog
        open={Boolean(pendingAction)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingAction(null);
            cancelMutation.reset();
            removeMutation.reset();
          }
        }}
        title={pendingAction?.type === "cancel" ? "Cancel connection request?" : "Remove this connection?"}
        description={pendingAction?.type === "cancel"
          ? `Cancel the pending request to ${pendingAction.name}?`
          : `Remove ${pendingAction?.name ?? "this person"} from your connections?`}
        confirmLabel={pendingAction?.type === "cancel" ? "Cancel request" : "Remove connection"}
        pending={cancelMutation.isPending || removeMutation.isPending}
        onConfirm={() => {
          if (pendingAction?.type === "cancel") cancelMutation.mutate(pendingAction.id);
          if (pendingAction?.type === "remove") removeMutation.mutate(pendingAction.id);
        }}
      />
    </>
  );
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return <button type="button" onClick={onClick} className={`inline-flex h-10 items-center gap-2 rounded-xl px-3.5 text-sm font-medium transition ${active ? "bg-brand-600 text-white" : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}>{icon}{children}</button>;
}

function PersonCard({ person, children }: { person: PublicUserProfile; children: ReactNode }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <Avatar name={person.full_name} src={person.profile_picture_url} className="h-11 w-11" />
      <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-900">{person.full_name}</p><p className="truncate text-xs text-slate-500">@{person.username}</p>{person.status_message && <p className="mt-1 truncate text-xs text-slate-400">{person.status_message}</p>}</div>
      {children}
    </Card>
  );
}
