import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bot,
  ChevronLeft,
  ChevronRight,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Search,
  Settings,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Avatar } from "../ui/avatar";
import { authApi } from "../../services/api/auth-api";
import { groupsApi } from "../../services/api/groups-api";
import { Button } from "../ui/button";
import { GlobalSearchDialog } from "./global-search-dialog";
import { NotificationBell } from "../../features/notifications/components/notification-bell";
import { useAuthStore } from "../../stores/auth-store";
import { cn } from "../../utils/cn";

const navigation = [
  { label: "Dashboard", to: "/dashboard", icon: LayoutDashboard },
  { label: "My Groups", to: "/groups", icon: UsersRound },
  { label: "Connections", to: "/connections", icon: UsersRound },
  { label: "AI Agents", to: "/agents", icon: Bot },
  { label: "Documents", to: "/documents", icon: FileText },
  { label: "Settings", to: "/settings", icon: Settings },
];

const routeTitles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/groups": "My Groups",
  "/connections": "Connections",
  "/agents": "AI Agents",
  "/documents": "Documents",
  "/notifications": "Notifications",
  "/settings": "Settings",
};

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const clearSession = useAuthStore((state) => state.clearSession);
  const location = useLocation();
  const navigate = useNavigate();
  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: groupsApi.list,
    enabled: Boolean(useAuthStore.getState().accessToken),
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const profileQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: authApi.me,
    enabled: Boolean(useAuthStore.getState().accessToken),
    retry: false,
  });
  useEffect(() => {
    if (profileQuery.data) setUser(profileQuery.data);
  }, [profileQuery.data, setUser]);

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      clearSession();
      navigate("/login", { replace: true });
    },
  });

  const pageTitle = location.pathname.startsWith("/groups/")
    ? "Group workspace"
    : routeTitles[location.pathname] ?? "TeamSpace";

  const sidebar = (
    <aside className={cn(
      "flex h-full flex-col border-r border-slate-800 bg-slate-950 text-slate-300 transition-[width] duration-200",
      collapsed ? "w-[76px]" : "w-[248px]",
    )}>
      <div className={cn("flex h-[72px] items-center border-b border-slate-800", collapsed ? "justify-center px-3" : "justify-between px-5")}>
        <NavLink to="/dashboard" className="flex items-center gap-3 overflow-hidden" aria-label="AI TeamSpace home">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-500 text-white"><span className="text-sm font-bold">AI</span></span>
          {!collapsed && <span className="whitespace-nowrap text-[15px] font-bold tracking-tight text-white">TeamSpace</span>}
        </NavLink>
        <button type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="hidden rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-white lg:block">
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
      <div className="px-3 pt-6">
        {!collapsed && <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">Workspace</p>}
        <Button
          type="button"
          size={collapsed ? "icon" : "md"}
          className={cn("mb-5 w-full bg-brand-500 text-white hover:bg-brand-400", collapsed && "h-10 w-10 p-0")}
          title={collapsed ? "Create a group" : undefined}
          aria-label="Create a group"
          onClick={() => { setMobileOpen(false); navigate("/groups", { state: { openCreate: true } }); }}
        >
          <Plus className="h-4 w-4" /> {!collapsed && "Create a group"}
        </Button>
        <nav className="space-y-1" aria-label="Main navigation">
          {navigation.map(({ label, to, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => cn(
                "group flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition",
                isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-white",
                collapsed && "justify-center px-0",
              )}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>
        {!collapsed && (
          <section className="mt-7">
            <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">Recent groups</p>
            {groupsQuery.isPending ? <p className="px-3 py-2 text-xs text-slate-500">Loading…</p> :
              groupsQuery.isError ? <p className="px-3 py-2 text-xs text-rose-300">Groups unavailable</p> :
              (groupsQuery.data?.items ?? []).slice(0, 4).map((group) => <NavLink key={group.group_id} to={`/groups/${group.group_id}/chat`} onClick={() => setMobileOpen(false)} className={({ isActive }) => cn("flex h-9 items-center gap-2.5 rounded-lg px-3 text-xs transition", isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-white")}><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-slate-800 text-[10px] font-bold text-slate-300">{group.name.slice(0, 1).toUpperCase()}</span><span className="truncate">{group.name}</span></NavLink>)}
          </section>
        )}
      </div>
      <div className="mt-auto border-t border-slate-800 p-3">
        <div className={cn("flex items-center gap-3 rounded-xl p-2", collapsed && "justify-center")}>
          <Avatar name={user?.full_name ?? user?.username ?? "TeamSpace"} className="h-9 w-9 bg-slate-700 text-white" />
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-white">{user?.full_name ?? user?.username ?? "Your profile"}</p>
              <p className="truncate text-xs text-slate-500">@{user?.username ?? ""}</p>
            </div>
          )}
        </div>
        <button type="button" onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending} title={collapsed ? "Log out" : undefined} className={cn("mt-1 flex h-10 w-full items-center gap-3 rounded-xl px-3 text-sm font-medium text-slate-400 transition hover:bg-slate-900 hover:text-white disabled:opacity-50", collapsed && "justify-center px-0")}>
          <LogOut className="h-[18px] w-[18px]" /> {!collapsed && "Log out"}
        </button>
      </div>
    </aside>
  );

  return (
    <div className="min-h-screen bg-[#f8f9fc]">
      <div className="fixed inset-y-0 left-0 z-30 hidden lg:block">{sidebar}</div>
      <div className={cn("min-h-screen transition-[padding] duration-200", collapsed ? "lg:pl-[76px]" : "lg:pl-[248px]")}>
        <header className="sticky top-0 z-20 flex h-[68px] items-center justify-between border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur sm:px-7">
          <div className="flex items-center gap-3">
            <button type="button" aria-label="Open navigation" onClick={() => { setCollapsed(false); setMobileOpen(true); }} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 lg:hidden"><Menu className="h-5 w-5" /></button>
            <div>
              <p className="text-sm font-semibold text-slate-800">{pageTitle}</p>
              <p className="hidden text-xs text-slate-400 sm:block">Your collaborative AI workspace</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setSearchOpen(true)} className="hidden h-9 border-slate-200 text-slate-500 sm:inline-flex"><Search className="h-4 w-4" /> Search <kbd className="ml-3 hidden rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-400 md:inline">Ctrl K</kbd></Button>
            <NotificationBell />
            <button type="button" aria-label="Search" onClick={() => setSearchOpen(true)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 sm:hidden"><Search className="h-5 w-5" /></button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] px-3 py-4 sm:px-7 sm:py-9 lg:px-10"><Outlet /></main>
      </div>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="absolute inset-0 bg-slate-950/35" />
          <div className="absolute inset-y-0 left-0 w-[280px] bg-slate-950 shadow-2xl">
            <button type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="absolute right-3 top-4 z-10 rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            {sidebar}
          </div>
        </div>
      )}
      <GlobalSearchDialog open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  );
}
