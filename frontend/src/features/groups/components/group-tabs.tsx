import { Bot, FileText, MessageSquare, Settings2, UsersRound, type LucideIcon } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../../../utils/cn";

export type GroupTab = "overview" | "chat" | "members" | "agents" | "documents" | "settings";

const tabs: { id: GroupTab; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: UsersRound },
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "members", label: "Members", icon: UsersRound },
  { id: "agents", label: "AI Agents", icon: Bot },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "settings", label: "Settings", icon: Settings2 },
];

export function GroupTabs({ groupId }: { groupId: string }) {
  const { search, pathname } = useLocation();
  const activeTab = new URLSearchParams(search).get("tab") ?? "overview";
  const isChatRoute = pathname.endsWith("/chat");

  return (
    <nav aria-label="Group workspace tabs" className="-mb-px flex overflow-x-auto border-b border-slate-200">
      {tabs.map(({ id, label, icon: Icon }) => (
        <Link
          key={id}
          to={id === "chat" ? `/groups/${groupId}/chat` : `/groups/${groupId}?tab=${id}`}
          role="tab"
          aria-selected={id === "chat" ? isChatRoute : !isChatRoute && activeTab === id}
          className={cn(
            "inline-flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition",
            (id === "chat" ? isChatRoute : !isChatRoute && activeTab === id)
              ? "border-brand-600 text-brand-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800",
          )}
        >
          <Icon className="h-4 w-4" /> {label}
        </Link>
      ))}
    </nav>
  );
}
