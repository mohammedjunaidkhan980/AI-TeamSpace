import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, LoaderCircle, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "../../../components/shared/page-header";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Skeleton } from "../../../components/ui/skeleton";
import { notificationsApi } from "../../../services/api/notifications-api";
import type { NotificationItem } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { notificationPath } from "../components/notification-bell";

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: ["notifications", "page"],
    queryFn: ({ pageParam }) => notificationsApi.list(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 30_000,
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const unreadCount = query.data?.pages[0]?.unread_count ?? 0;
  const invalidate = async () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useMutation({ mutationFn: notificationsApi.read, onSuccess: invalidate });
  const markAllRead = useMutation({ mutationFn: notificationsApi.readAll, onSuccess: invalidate });
  const remove = useMutation({ mutationFn: notificationsApi.remove, onSuccess: invalidate });

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Updates about connections, groups, messages, AI responses, and documents."
        action={<Button variant="outline" onClick={() => markAllRead.mutate()} disabled={unreadCount === 0 || markAllRead.isPending}><CheckCheck className="h-4 w-4" /> Mark all read</Button>}
      />
      {markRead.isError && <ErrorState message={getErrorMessage(markRead.error, "Could not update notification status.")} />}
      {markAllRead.isError && <ErrorState message={getErrorMessage(markAllRead.error, "Could not mark notifications as read.")} />}
      {remove.isError && <ErrorState message={getErrorMessage(remove.error, "Could not delete notification.")} />}
      {query.isPending ? (
        <div className="space-y-3">{[1, 2, 3].map((item) => <Skeleton className="h-24" key={item} />)}</div>
      ) : query.isError ? (
        <ErrorState message={getErrorMessage(query.error, "Could not load notifications.")} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <Card><EmptyState icon={<Bell className="h-5 w-5" />} title="You’re all caught up" description="New updates will appear here when activity happens in your workspace." /></Card>
      ) : (
        <div className="space-y-3">
          {items.map((item) => <NotificationRow key={item.notification_id} item={item} onRead={() => markRead.mutate(item.notification_id)} onDelete={() => remove.mutate(item.notification_id)} />)}
          {query.hasNextPage && <div className="flex justify-center pt-2"><Button variant="outline" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>{query.isFetchingNextPage && <LoaderCircle className="h-4 w-4 animate-spin" />} Load older notifications</Button></div>}
        </div>
      )}
    </>
  );
}

function NotificationRow({ item, onRead, onDelete }: { item: NotificationItem; onRead: () => void; onDelete: () => void }) {
  const destination = notificationPath(item);
  return (
    <Card className={`flex items-start gap-3 p-4 sm:p-5 ${item.is_read ? "bg-white" : "border-brand-100 bg-brand-50/30"}`}>
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${item.is_read ? "bg-slate-200" : "bg-brand-500"}`} aria-label={item.is_read ? "Read" : "Unread"} />
      <Avatar name={item.title} className="h-9 w-9 rounded-xl" />
      <div className="min-w-0 flex-1">
        <Link to={destination} onClick={() => { if (!item.is_read) onRead(); }} className="text-sm font-semibold text-slate-900 hover:text-brand-700">{item.title}</Link>
        <p className="mt-1 text-sm leading-5 text-slate-600">{item.description}</p>
        <time className="mt-2 block text-xs text-slate-400" dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {!item.is_read && <Button variant="ghost" size="icon" aria-label="Mark as read" onClick={onRead}><CheckCheck className="h-4 w-4" /></Button>}
        <Button variant="ghost" size="icon" aria-label="Delete notification" onClick={onDelete}><Trash2 className="h-4 w-4 text-slate-400 hover:text-rose-600" /></Button>
      </div>
    </Card>
  );
}
