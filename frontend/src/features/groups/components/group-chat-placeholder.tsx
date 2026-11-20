import { MessageSquare, Radio } from "lucide-react";
import { Card } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import type { GroupDetails } from "../../../types/api";

export function GroupChatPlaceholder({ group }: { group: GroupDetails }) {
  return (
    <Card>
      <EmptyState
        icon={<MessageSquare className="h-5 w-5" />}
        title="Group chat UI is a separate phase"
        description="This workspace shows the chat entry point, but real-time messages and the Nexconn SDK are intentionally not implemented here."
        action={<span className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${group.nexconn_sync_status === "synced" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}><Radio className="h-3.5 w-3.5" /> Channel {group.nexconn_sync_status}</span>}
      />
    </Card>
  );
}
