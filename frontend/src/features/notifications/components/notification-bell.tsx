import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { DropdownItem } from "../../../components/ui/dropdown";
import { notificationsApi } from "../../../services/api/notifications-api";
import { getErrorMessage } from "../../../utils/errors";
import { toast } from "../../../components/ui/toaster";
import type { NotificationItem } from "../../../types/api";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications", "bell"],
    queryFn: () => notificationsApi.list(),
    refetchInterval: 30_000,
  });
  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  const readAllMutation = useMutation({
    mutationFn: notificationsApi.readAll,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error) => toast({ variant: "error", title: "Could not mark notifications as read", description: getErrorMessage(error) }),
  });
  const readMutation = useMutation({
    mutationFn: notificationsApi.read,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error) => toast({ variant: "error", title: "Could not update notification", description: getErrorMessage(error) }),
  });

  const openNotification = (notification: NotificationItem) => {
    if (!notification.is_read) readMutation.mutate(notification.notification_id);
    setOpen(false);
    navigate(notificationPath(notification));
  };
  const unreadCount = query.data?.unread_count ?? 0;

  return (
    <div className="relative" ref={containerRef}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="notification-popover"
        className="relative"
        onClick={() => {
          const nextOpen = !open;
          setOpen(nextOpen);
          if (nextOpen) void query.refetch();
        }}
      >
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold text-white">{unreadCount > 99 ? "99+" : unreadCount}</span>}
      </Button>
      {open && (
        <div
          id="notification-popover"
          role="menu"
          aria-label="Notifications"
          className="fixed left-3 right-3 top-[4.25rem] z-50 max-h-[70vh] overflow-y-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl sm:absolute sm:left-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[22rem]"
        >
          <div className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-3 py-2">
            <span className="text-xs font-semibold text-slate-800">Notifications</span>
            {unreadCount > 0 && <button type="button" className="text-[10px] font-medium text-brand-700 hover:text-brand-800" onClick={() => readAllMutation.mutate()} disabled={readAllMutation.isPending}>Mark all read</button>}
          </div>
          {query.isPending ? <div className="flex items-center gap-2 px-3 py-4 text-xs text-slate-500"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />Loading notifications…</div> :
            query.isError ? <div className="px-3 py-3"><p role="alert" className="text-xs text-rose-700">Could not load notifications.</p><button type="button" className="mt-2 text-xs font-semibold text-brand-700 hover:text-brand-800" onClick={() => void query.refetch()}>Try again</button></div> :
            query.data.items.length === 0 ? <p className="px-3 py-4 text-xs text-slate-500">You’re all caught up.</p> :
            query.data.items.slice(0, 6).map((notification) => (
              <DropdownItem key={notification.notification_id} onClick={() => openNotification(notification)}>
                <span className={`mr-2 h-2 w-2 shrink-0 rounded-full ${notification.is_read ? "bg-transparent" : "bg-brand-500"}`} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{notification.title}</span>
                  <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-slate-500">{notification.description}</span>
                  <time className="mt-1 block text-[9px] text-slate-400" dateTime={notification.created_at}>{new Date(notification.created_at).toLocaleString()}</time>
                </span>
              </DropdownItem>
            ))}
          <DropdownItem onClick={() => { setOpen(false); navigate("/notifications"); }}><Check className="mr-2 h-3.5 w-3.5" />View all notifications</DropdownItem>
        </div>
      )}
    </div>
  );
}

export function notificationPath(notification: NotificationItem) {
  if (notification.type === "connection_request" || notification.type === "connection_accepted") {
    return "/connections?tab=requests";
  }
  if (notification.type.startsWith("document_") && notification.related_entity_id) {
    return `/documents?documentId=${encodeURIComponent(notification.related_entity_id)}`;
  }
  if (notification.group_id) {
    if (
      notification.type === "new_group_message" ||
      notification.type === "ai_response"
    ) {
      return `/groups/${notification.group_id}/chat`;
    }
    return `/groups/${notification.group_id}`;
  }
  return "/notifications";
}
