import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileText,
  LoaderCircle,
  MessageSquareText,
  MoreHorizontal,
  RefreshCw,
  Send,
  Trash2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { Avatar } from "../../../components/ui/avatar";
import { Button } from "../../../components/ui/button";
import { ConfirmationDialog } from "../../../components/ui/confirmation-dialog";
import { EmptyState } from "../../../components/ui/empty-state";
import { ErrorState } from "../../../components/ui/error-state";
import { Dropdown, DropdownItem } from "../../../components/ui/dropdown";
import { Skeleton } from "../../../components/ui/skeleton";
import { toast } from "../../../components/ui/toaster";
import { useAuthStore } from "../../../stores/auth-store";
import type { DocumentCitation, GroupDetails, MessageResponse } from "../../../types/api";
import { getErrorMessage } from "../../../utils/errors";
import { messagesApi } from "../../../services/api/messages-api";
import { groupsApi } from "../../../services/api/groups-api";
import { agentsApi } from "../../../services/api/agents-api";
import { useNexconnStatus } from "../../../services/nexconn-session";

export function GroupChatPanel({ group }: { group: GroupDetails }) {
  const currentUserId = useAuthStore((state) => state.user?.id) ?? "";
  const currentMember = group.members.find((member) => member.user.id === currentUserId);
  const isAdmin = currentMember?.role === "admin";
  const queryClient = useQueryClient();
  const nexconn = useNexconnStatus();
  const bottomRef = useRef<HTMLDivElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<MessageResponse | null>(null);
  const [activeRun, setActiveRun] = useState<{ id: string; messageId: string } | null>(null);
  const [draft, setDraft] = useState("");
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const agentsQuery = useQuery({
    queryKey: ["groups", group.group_id, "agents"],
    queryFn: () => agentsApi.groupAgents(group.group_id),
  });
  const enabledAgents = useMemo(
    () => (agentsQuery.data ?? []).filter((a) => a.enabled),
    [agentsQuery.data],
  );
  const mentionMatches = useMemo(() => {
    if (mentionQuery === null) return [];
    const q = mentionQuery.toLowerCase();
    return enabledAgents.filter((a) => a.name.toLowerCase().includes(q));
  }, [mentionQuery, enabledAgents]);
  const historyQuery = useInfiniteQuery({
    queryKey: ["groups", group.group_id, "messages"],
    queryFn: ({ pageParam }) => messagesApi.history(group.group_id, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 10_000,
  });
  const statsQuery = useQuery({
    queryKey: ["groups", group.group_id, "message-stats"],
    queryFn: () => groupsApi.messageStats(group.group_id),
  });
  const messages = useMemo(
    () => [...(historyQuery.data?.pages ?? [])].reverse().flatMap((page) => page.items),
    [historyQuery.data],
  );
  const deleteMutation = useMutation({
    mutationFn: messagesApi.remove,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "messages"] });
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "message-stats"] });
      toast({ variant: "success", title: "Message deleted" });
      setDeleteTarget(null);
    },
    onError: (error) => toast({ variant: "error", title: "Could not delete message", description: getErrorMessage(error) }),
  });
  const sendMutation = useMutation({
    mutationFn: (content: string) => messagesApi.send(group.group_id, content, crypto.randomUUID()),
    onSuccess: async (message) => {
      setDraft("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "messages"] }),
        queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "message-stats"] }),
      ]);
      if (message.delivery_status === "failed") {
        toast({ variant: "error", title: "Message saved but not delivered", description: "Use Retry in the message actions to send it again." });
      } else {
        toast({ variant: "success", title: "Message sent" });
      }
    },
    onError: (error) => toast({ variant: "error", title: "Could not send message", description: getErrorMessage(error) }),
  });
  const retryMessageMutation = useMutation({
    mutationFn: messagesApi.retry,
    onSuccess: async (message) => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "messages"] });
      toast({
        variant: message.delivery_status === "delivered" ? "success" : "error",
        title: message.delivery_status === "delivered" ? "Message delivered" : "Message still could not be delivered",
      });
    },
    onError: (error) => toast({ variant: "error", title: "Could not retry message", description: getErrorMessage(error) }),
  });
  const processMutation = useMutation({
    mutationFn: (messageId: string) => messagesApi.processWithAi(group.group_id, messageId),
    onSuccess: (result, messageId) => {
      setActiveRun({ id: result.orchestration_id, messageId });
      void queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "messages"] });
      toast({ variant: "success", title: "AI processing started" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not start AI processing", description: getErrorMessage(error) }),
  });
  const runQuery = useQuery({
    queryKey: ["groups", group.group_id, "orchestrations", activeRun?.id],
    queryFn: () => messagesApi.orchestration(group.group_id, activeRun!.id),
    enabled: Boolean(activeRun),
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === "completed" || state === "failed" ? false : 2000;
    },
  });
  const deliveryQuery = useQuery({
    queryKey: ["groups", group.group_id, "orchestrations", activeRun?.id, "delivery"],
    queryFn: () => messagesApi.deliveryStatus(group.group_id, activeRun!.id),
    enabled: Boolean(activeRun && runQuery.data?.status === "completed"),
    refetchInterval: (query) => {
      const state = query.state.data?.delivery_status;
      return state === "delivered" || state === "failed" ? false : 2500;
    },
  });
  const deliveryMutation = useMutation({
    mutationFn: () => messagesApi.deliver(group.group_id, activeRun!.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "orchestrations", activeRun?.id] });
      await queryClient.invalidateQueries({ queryKey: ["groups", group.group_id, "messages"] });
      toast({ variant: "success", title: "AI response delivery queued" });
    },
    onError: (error) => toast({ variant: "error", title: "Could not deliver AI response", description: getErrorMessage(error) }),
  });

  useEffect(() => {
    if (historyQuery.data?.pages.length === 1) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [historyQuery.data?.pages.length]);

  useEffect(() => { setMentionIndex(0); }, [mentionMatches]);

  function handleDraftChange(value: string) {
    setDraft(value);
    const cursor = textareaRef.current?.selectionStart ?? value.length;
    const textUpToCursor = value.slice(0, cursor);
    const match = textUpToCursor.match(/@([\/\w ]*)$/);
    setMentionQuery(match ? match[1].trimEnd() : null);
  }

  function applyMention(agentName: string) {
    const cursor = textareaRef.current?.selectionStart ?? draft.length;
    const before = draft.slice(0, cursor);
    const after = draft.slice(cursor);
    const replaced = before.replace(/@([\/\w ]*)$/, `@${agentName} `);
    setDraft(replaced + after);
    setMentionQuery(null);
    setTimeout(() => {
      textareaRef.current?.focus();
      const pos = replaced.length;
      textareaRef.current?.setSelectionRange(pos, pos);
    }, 0);
  }

  function handleTextareaKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (mentionMatches.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setMentionIndex((i) => (i + 1) % mentionMatches.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); applyMention(mentionMatches[mentionIndex].name); }
    else if (e.key === "Escape") { setMentionQuery(null); }
  }

  return (
    <div className="grid min-h-[min(72vh,760px)] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-panel lg:grid-cols-[minmax(0,1fr)_300px]">
      <section className="flex min-h-[560px] flex-col border-b border-slate-200 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3.5 sm:px-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><MessageSquareText className="h-4 w-4" /></span>
            <div><h2 className="text-sm font-semibold text-slate-900">Conversation</h2><p className="text-xs text-slate-400">{group.member_count} members · persisted history</p></div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`hidden items-center gap-1 text-[10px] font-medium sm:inline-flex ${nexconn.status === "connected" ? "text-emerald-700" : nexconn.status === "error" ? "text-rose-600" : "text-slate-400"}`} title={`Nexconn ${nexconn.status}`}>
              {nexconn.status === "connected" ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />} {nexconn.enabled ? nexconn.status : "offline"}
            </span>
            <Button type="button" variant="ghost" size="icon" aria-label="Refresh messages" onClick={() => void historyQuery.refetch()}><RefreshCw className="h-4 w-4" /></Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {historyQuery.isPending ? (
            <div className="space-y-5">{[1, 2, 3].map((item) => <div key={item} className="flex gap-3"><Skeleton className="h-9 w-9 rounded-full" /><Skeleton className="h-20 flex-1" /></div>)}</div>
          ) : historyQuery.isError ? (
            <ErrorState message={getErrorMessage(historyQuery.error, "Could not load conversation history.")} onRetry={() => void historyQuery.refetch()} />
          ) : messages.length === 0 ? (
            <EmptyState icon={<MessageSquareText className="h-5 w-5" />} title="No messages yet" description="New messages received through the configured chat integration will appear here." />
          ) : (
            <div className="space-y-5">
              {historyQuery.hasNextPage && (
                <div className="flex justify-center">
                  <Button type="button" size="sm" variant="outline" disabled={historyQuery.isFetchingNextPage} onClick={() => void historyQuery.fetchNextPage()}>
                    {historyQuery.isFetchingNextPage ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ChevronDown className="h-4 w-4" />} Load older messages
                  </Button>
                </div>
              )}
              {messages.map((message, index) => {
                const previous = messages[index - 1];
                const newDay = !previous || new Date(previous.created_at).toDateString() !== new Date(message.created_at).toDateString();
                return (
                  <div key={message.message_id}>
                    {newDay && <div className="my-5 flex items-center gap-3"><span className="h-px flex-1 bg-slate-100" /><span className="text-[11px] font-medium text-slate-400">{formatDay(message.created_at)}</span><span className="h-px flex-1 bg-slate-100" /></div>}
                    <MessageItem
                      message={message}
                      currentUserId={currentUserId}
                      isAdmin={isAdmin}
                      onDelete={() => setDeleteTarget(message)}
                      onProcess={() => processMutation.mutate(message.message_id)}
                      onRetry={() => retryMessageMutation.mutate(message.message_id)}
                      processing={processMutation.isPending && processMutation.variables === message.message_id}
                      processed={activeRun?.messageId === message.message_id}
                    />
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <form
          className="relative border-t border-slate-100 bg-slate-50/70 p-4 sm:p-5"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const content = draft.trim();
            if (content && !sendMutation.isPending) sendMutation.mutate(content);
          }}
        >
          {mentionMatches.length > 0 && (
            <div className="absolute bottom-full left-4 right-4 mb-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg sm:left-5 sm:right-5">
              {mentionMatches.map((agent, idx) => (
                <button
                  key={agent.agent_id}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); applyMention(agent.name); }}
                  className={`flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm transition ${
                    idx === mentionIndex ? "bg-brand-50 text-brand-800" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-brand-100 text-brand-700"><Bot className="h-3.5 w-3.5" /></span>
                  <span>
                    <span className="block font-medium">{agent.name}</span>
                    <span className="block text-[11px] text-slate-400 line-clamp-1">{agent.description}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          <div className="rounded-xl border border-slate-200 bg-white p-3.5">
            <textarea
              ref={textareaRef}
              aria-label="Message composer"
              value={draft}
              onChange={(event) => handleDraftChange(event.target.value)}
              onKeyDown={handleTextareaKeyDown}
              disabled={!nexconn.enabled || sendMutation.isPending}
              rows={2}
              maxLength={65536}
              placeholder={nexconn.enabled ? "Write a message… (type @ to mention an agent)" : "Nexconn messaging is not configured for this workspace."}
              className="w-full resize-none border-0 bg-transparent p-0 text-sm text-slate-700 placeholder:text-slate-400 focus:ring-0 disabled:cursor-not-allowed"
            />
            <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3">
              <p className="text-[11px] leading-4 text-slate-400">Messages are stored in TeamSpace and sent via the authenticated Nexconn server integration.</p>
              <Button type="submit" size="icon" disabled={!draft.trim() || !nexconn.enabled || sendMutation.isPending} aria-label="Send message" title={!nexconn.enabled ? "Nexconn is not configured" : "Send message"}><Send className="h-4 w-4" /></Button>
            </div>
          </div>
        </form>
      </section>

      <aside className="space-y-5 bg-slate-50/50 p-4 sm:p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Conversation details</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">Human messages, AI responses, and delivery state are persisted by the backend.</p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SummaryCard label="Messages" value={statsQuery.isError ? "Unavailable" : statsQuery.data?.total_message_count ?? "—"} />
          <SummaryCard label="Members" value={group.member_count} />
        </div>
        {group.ai_agents.length > 0 && (
          <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-3.5">
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-800"><Bot className="h-4 w-4" /> AI teammates</div>
            {enabledAgents.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {enabledAgents.map((agent) => (
                  <li key={agent.agent_id} className="flex items-center gap-2 text-xs text-brand-700">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-brand-100"><Bot className="h-3 w-3" /></span>
                    <span className="font-medium">@{agent.name}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-xs leading-5 text-brand-700">No agents are currently enabled.</p>
            )}
            <p className="mt-2 text-[11px] leading-4 text-brand-600">Type @ in the composer to mention an agent.</p>
          </div>
        )}
        {activeRun && (
          <OrchestrationCard
            run={runQuery.data}
            delivery={deliveryQuery.data}
            error={runQuery.isError ? getErrorMessage(runQuery.error) : null}
            loading={runQuery.isPending}
            delivering={deliveryMutation.isPending}
            onRetryDelivery={() => deliveryMutation.mutate()}
          />
        )}
        {!activeRun && <div className="rounded-xl border border-slate-200 bg-white p-3.5"><div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Clock3 className="h-4 w-4 text-slate-400" />Activity</div><p className="mt-1.5 text-xs leading-5 text-slate-500">No live typing, presence, or notification events are exposed by the current frontend integration.</p></div>}
      </aside>

      <ConfirmationDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => { if (!open) { setDeleteTarget(null); deleteMutation.reset(); } }}
        title="Delete this message?"
        description="The message will be soft-deleted and shown as deleted in future history."
        confirmLabel="Delete message"
        pending={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.message_id)}
      />
      {deleteMutation.isError && <p role="alert" className="sr-only">{getErrorMessage(deleteMutation.error, "Could not delete message.")}</p>}
    </div>
  );
}

function MessageItem({
  message,
  currentUserId,
  isAdmin,
  onDelete,
  onProcess,
  onRetry,
  processing,
  processed,
}: {
  message: MessageResponse;
  currentUserId: string;
  isAdmin: boolean;
  onDelete: () => void;
  onProcess: () => void;
  onRetry: () => void;
  processing: boolean;
  processed: boolean;
}) {
  const isAgent = message.sender.type === "agent";
  const isOwn = message.sender.id === currentUserId;
  const canDelete = !message.is_deleted && (isOwn || isAdmin);
  const canProcess = !message.is_deleted && !processed && message.sender.type === "user" && message.message_type === "text";
  const canRetry = !message.is_deleted && message.sender.type === "user" && message.delivery_status === "failed" && isOwn;

  return (
    <article className="group flex gap-3">
      <Avatar name={message.sender.name} className={`h-9 w-9 ${isAgent ? "rounded-xl bg-brand-100 text-brand-700" : ""}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-semibold text-slate-900">{message.sender.name}</span>
          {isAgent && <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700">{message.agent_name ?? "AI agent"}</span>}
          <time className="text-[11px] text-slate-400" dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time>
          {message.delivery_status && <DeliveryBadge status={message.delivery_status} />}
        </div>
        <div className={`mt-1.5 rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${message.is_deleted ? "bg-slate-50 italic text-slate-400" : isAgent ? "border border-brand-100 bg-brand-50/60 text-slate-800" : isOwn ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-800"}`}>
          <MessageContent content={message.content} isOwn={isOwn} isDeleted={message.is_deleted} />
          {message.attachments.length > 0 && <div className="mt-2 space-y-1">{message.attachments.map((attachment, index) => <a key={`${attachment.url}-${index}`} href={attachment.url} target="_blank" rel="noreferrer" className={`block truncate text-xs underline ${isOwn ? "text-white/80" : "text-brand-700"}`}>{attachment.name ?? attachment.url}</a>)}</div>}
        </div>
        {isAgent && !message.is_deleted && <MessageCitations citations={readCitations(message)} />}
        {message.reply_to_message_id && <p className="mt-1 text-[10px] text-slate-400">Reply to {message.reply_to_message_id}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1 self-start pt-0.5">
        {canProcess && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={processing}
            onClick={onProcess}
            className="h-7 gap-1.5 px-2.5 text-[11px] text-brand-700 border-brand-200 hover:bg-brand-50"
          >
            {processing ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Bot className="h-3 w-3" />}
            {processing ? "Starting…" : "Ask AI"}
          </Button>
        )}
        {(canDelete || canRetry) && (
          <Dropdown label={`Actions for message by ${message.sender.name}`} trigger={<Button type="button" variant="ghost" size="icon" className="h-6 w-6" aria-label={`Actions for message by ${message.sender.name}`}><MoreHorizontal className="h-3.5 w-3.5" /></Button>}>
            {canRetry && <DropdownItem onClick={onRetry}><RefreshCw className="mr-2 h-4 w-4" />Retry delivery</DropdownItem>}
            {canDelete && <DropdownItem destructive onClick={onDelete}><Trash2 className="mr-2 h-4 w-4" />Delete message</DropdownItem>}
          </Dropdown>
        )}
      </div>
    </article>
  );
}

function MessageContent({ content, isOwn, isDeleted }: { content: string; isOwn: boolean; isDeleted: boolean }) {
  if (isDeleted) return <span>{content}</span>;
  const parts = content.split(/(@[\w][\w ]*)/g);
  return (
    <span>
      {parts.map((part, i) =>
        part.startsWith("@") ? (
          <span key={i} className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[11px] font-semibold ${
            isOwn ? "bg-white/20 text-white" : "bg-brand-100 text-brand-700"
          }`}>{part}</span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  );
}

function MessageCitations({ citations }: { citations: DocumentCitation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Sources</p>
      {citations.map((citation) => (
        <Link
          key={`${citation.document_id}-${citation.chunk_index}`}
          to={`/documents?documentId=${encodeURIComponent(citation.document_id)}`}
          title={citation.excerpt}
          className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs transition hover:border-brand-200 hover:bg-brand-50/40"
        >
          <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" />
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-700">{citation.filename}{citation.page_number ? ` · p. ${citation.page_number}` : ""}</span>
            <span className="mt-0.5 line-clamp-2 block text-[10px] leading-4 text-slate-500">{citation.excerpt}</span>
          </span>
        </Link>
      ))}
    </div>
  );
}

function readCitations(message: MessageResponse): DocumentCitation[] {
  const citations = message.metadata.citations;
  if (!Array.isArray(citations)) return [];
  return citations.filter((value): value is DocumentCitation => {
    if (typeof value !== "object" || value === null) return false;
    const citation = value as Record<string, unknown>;
    return (
      typeof citation.document_id === "string" &&
      typeof citation.filename === "string" &&
      typeof citation.chunk_index === "number" &&
      Number.isInteger(citation.chunk_index) &&
      (citation.page_number === null || typeof citation.page_number === "number") &&
      typeof citation.excerpt === "string"
    );
  });
}

function DeliveryBadge({ status }: { status: NonNullable<MessageResponse["delivery_status"]> }) {
  const icon = status === "delivered" ? <CheckCircle2 className="h-3 w-3" /> : status === "failed" ? <AlertCircle className="h-3 w-3" /> : <LoaderCircle className="h-3 w-3 animate-spin" />;
  const style = status === "delivered" ? "text-emerald-700" : status === "failed" ? "text-rose-700" : "text-amber-700";
  return <span className={`inline-flex items-center gap-1 text-[10px] font-medium capitalize ${style}`}>{icon}{status}</span>;
}

function OrchestrationCard({
  run,
  delivery,
  loading,
  error,
  delivering,
  onRetryDelivery,
}: {
  run?: import("../../../types/api").OrchestrationRun;
  delivery?: import("../../../types/api").AIMessageDeliveryStatus;
  loading: boolean;
  error: string | null;
  delivering: boolean;
  onRetryDelivery: () => void;
}) {
  return (
    <div className="rounded-xl border border-brand-100 bg-white p-3.5">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Bot className="h-4 w-4 text-brand-600" /> AI activity</div>
      {loading && <p className="mt-2 inline-flex items-center gap-2 text-xs text-slate-500"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />Loading orchestration…</p>}
      {error && <p role="alert" className="mt-2 text-xs text-rose-700">{error}</p>}
      {run && (
        <>
          <div className="mt-2 flex items-center justify-between"><span className="text-xs text-slate-500">Run status</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold capitalize text-slate-700">{run.status}</span></div>
          {run.agent_results.length > 0 ? <ol className="mt-3 space-y-2 border-l border-brand-100 pl-3">{run.agent_results.map((result) => <li key={result.agent_id} className="relative"><span className={`absolute -left-[17px] top-1 h-2 w-2 rounded-full ${result.status === "completed" ? "bg-emerald-500" : "bg-rose-400"}`} /><p className="text-xs font-medium text-slate-800">{result.agent_name}</p><p className="text-[10px] capitalize text-slate-500">{result.status}{result.execution_time ? ` · ${result.execution_time.toFixed(1)}s` : ""}</p>{result.response && <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-600">{result.response}</p>}</li>)}</ol> : <p className="mt-2 text-xs text-slate-500">The backend has not returned individual agent results yet.</p>}
          {run.final_response && <div className="mt-3 rounded-lg bg-brand-50 p-2.5"><p className="text-[10px] font-semibold uppercase tracking-wide text-brand-700">Final response</p><p className="mt-1 line-clamp-5 whitespace-pre-wrap text-xs leading-5 text-slate-700">{run.final_response}</p></div>}
          <div className="mt-3 flex items-center justify-between gap-2">
            <p className="text-[10px] text-slate-500">Delivery: {delivery?.delivery_status ?? run.delivery_status ?? "not reported"}{delivery ? ` · retries ${delivery.retry_count}` : ""}</p>
            {run.status === "completed" && delivery?.delivery_status === "failed" && (
              <Button type="button" size="sm" variant="outline" disabled={delivering} onClick={onRetryDelivery}>
                {delivering ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Retry
              </Button>
            )}
          </div>
          {delivery?.error_message && <p className="mt-2 break-words text-xs text-rose-700">{delivery.error_message}</p>}
        </>
      )}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-3"><p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 text-lg font-semibold text-slate-900">{value}</p></div>;
}

function formatDay(value: string) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "long", day: "numeric", year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}
