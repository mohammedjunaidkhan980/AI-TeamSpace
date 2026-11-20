import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Search, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Avatar } from "../ui/avatar";
import { Input } from "../ui/input";
import { Modal } from "../ui/modal";
import { groupsApi } from "../../services/api/groups-api";
import { usersApi } from "../../services/api/users-api";
import { useAuthStore } from "../../stores/auth-store";

export function GlobalSearchDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [term, setTerm] = useState("");
  const [queryTerm, setQueryTerm] = useState("");
  const currentUserId = useAuthStore((state) => state.user?.id);

  useEffect(() => {
    if (!open) {
      setTerm("");
      setQueryTerm("");
      return;
    }
    const timer = window.setTimeout(() => setQueryTerm(term.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [term, open]);

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: groupsApi.list,
    enabled: open && queryTerm.length > 0,
  });
  const usersQuery = useQuery({
    queryKey: ["users", "search", queryTerm],
    queryFn: () => usersApi.search(queryTerm),
    enabled: open && queryTerm.length > 0,
  });
  const groups = groupsQuery.data?.items.filter((group) =>
    `${group.name} ${group.description ?? ""}`.toLowerCase().includes(queryTerm.toLowerCase()),
  ) ?? [];
  const users = usersQuery.data?.items.filter((person) => person.id !== currentUserId) ?? [];

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Search your workspace" description="Find groups and teammates. Documents and messages are not indexed in global search.">
      <div className="relative">
        <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <Input autoFocus value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Search groups or people…" className="pl-10" aria-label="Search groups and teammates" />
      </div>
      {queryTerm.length === 0 ? (
        <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">Start typing to search your groups and teammates.</div>
      ) : (
        <div className="mt-4 max-h-[50vh] space-y-4 overflow-y-auto">
          {(groupsQuery.isPending || usersQuery.isPending) && <p className="p-3 text-sm text-slate-500">Searching…</p>}
          {groups.length > 0 && <section><h3 className="mb-1 px-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Groups</h3>{groups.map((group) => <Link key={group.group_id} to={`/groups/${group.group_id}`} onClick={() => onOpenChange(false)} className="flex items-center gap-3 rounded-xl p-2.5 hover:bg-slate-50"><Avatar name={group.name} className="h-9 w-9 rounded-lg" /><span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{group.name}</span><ArrowUpRight className="h-4 w-4 text-slate-400" /></Link>)}</section>}
          {users.length > 0 && <section><h3 className="mb-1 px-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Teammates</h3>{users.map((person) => <Link key={person.id} to={`/connections?search=${encodeURIComponent(person.username)}`} onClick={() => onOpenChange(false)} className="flex items-center gap-3 rounded-xl p-2.5 hover:bg-slate-50"><Avatar name={person.full_name} src={person.profile_picture_url} className="h-9 w-9" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-slate-800">{person.full_name}</span><span className="block truncate text-xs text-slate-400">@{person.username}</span></span><UsersRound className="h-4 w-4 text-slate-400" /></Link>)}</section>}
          {!groupsQuery.isPending && !usersQuery.isPending && groups.length === 0 && users.length === 0 && (
            <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">No matching groups or teammates.</p>
          )}
          {(groupsQuery.isError || usersQuery.isError) && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700">Some search results could not be loaded. Try again in a moment.</p>}
        </div>
      )}
    </Modal>
  );
}
