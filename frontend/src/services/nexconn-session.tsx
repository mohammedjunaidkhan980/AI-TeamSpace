import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { nexconnApi } from "./api/nexconn-api";
import { useAuthStore } from "../stores/auth-store";

export type NexconnStatus = "connecting" | "connected" | "disconnected" | "disabled" | "error";
const HANDLER_ID = "ai-teamspace-session";
let initializedAppKey: string | null = null;
let connectedUserId: string | null = null;
let connectionQueue: Promise<void> = Promise.resolve();

function connectNexconn(userId: string, token: string) {
  const attempt = connectionQueue.then(async () => {
    if (connectedUserId === userId) return;
    const { NCEngine } = await import("@nexconn/chat");
    if (connectedUserId) {
      await NCEngine.disconnect();
      connectedUserId = null;
    }
    const result = await NCEngine.connect({ token });
    if (!result.isOk || result.data?.userId !== userId) {
      throw new Error("Nexconn connection returned an unexpected user identity");
    }
    connectedUserId = userId;
  });
  connectionQueue = attempt.catch(() => undefined);
  return attempt;
}

function disconnectNexconn() {
  const attempt = connectionQueue.then(async () => {
    if (!connectedUserId) return;
    const { NCEngine } = await import("@nexconn/chat");
    await NCEngine.disconnect();
    connectedUserId = null;
  });
  connectionQueue = attempt.catch(() => undefined);
  return attempt;
}

const NexconnContext = createContext<{ status: NexconnStatus; enabled: boolean }>({
  status: "disconnected",
  enabled: false,
});

export function NexconnSessionProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const accessToken = useAuthStore((state) => state.accessToken);
  const userId = useAuthStore((state) => state.user?.id);
  const [status, setStatus] = useState<NexconnStatus>("disconnected");
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    let engine: typeof import("@nexconn/chat").NCEngine | null = null;
    const invalidateMessages = () => {
      void queryClient.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === "groups" && query.queryKey.includes("messages"),
      });
    };

    if (!accessToken || !userId) {
      setEnabled(false);
      setStatus("disconnected");
      void disconnectNexconn().catch(() => {
        if (active) setStatus("error");
      });
      return () => { active = false; };
    }

    setStatus("connecting");
    void nexconnApi.status().then(async (integration) => {
      if (!integration.enabled) {
        await disconnectNexconn();
        if (active) {
          setEnabled(false);
          setStatus("disabled");
        }
        return null;
      }
      return nexconnApi.token();
    }).then(async (credentials) => {
      if (credentials === null) return;
      if (!active) return;
      if (credentials.nexconn_user_id !== userId) {
        throw new Error("Nexconn identity does not match the authenticated user");
      }
      const { AreaCode, ConnectionStatusHandler, MessageHandler, NCEngine } = await import("@nexconn/chat");
      if (!active) return;
      engine = NCEngine;
      setEnabled(true);
      if (initializedAppKey === null) {
        NCEngine.initialize({ appKey: credentials.app_key, areaCode: AreaCode.SG });
        initializedAppKey = credentials.app_key;
      } else if (initializedAppKey !== credentials.app_key) {
        throw new Error("Nexconn application key changed during this session");
      }
      NCEngine.addConnectionStatusHandler(
        HANDLER_ID,
        new ConnectionStatusHandler({
          onConnectionStatusChanged: ({ status: sdkStatus }) => {
            if (active) {
              const normalized = String(sdkStatus).toLowerCase();
              const connected = sdkStatus === 0 || (normalized.includes("connected") && !normalized.includes("disconnected"));
              const disconnected = sdkStatus === 2 || normalized.includes("disconnected");
              setStatus(connected ? "connected" : disconnected ? "disconnected" : "connecting");
            }
          },
        }),
      );
      NCEngine.addMessageHandler(
        HANDLER_ID,
        new MessageHandler({
          onMessageReceived: invalidateMessages,
          onOfflineMessageSyncCompleted: invalidateMessages,
          onMessagesUpdated: invalidateMessages,
          onMessageDeleted: invalidateMessages,
        }),
      );
      await connectNexconn(userId, credentials.nexconn_token);
      if (!active) return;
      setStatus("connected");
    }).catch(() => {
      if (active) {
        setEnabled(false);
        setStatus("error");
      }
    });

    return () => {
      active = false;
      engine?.removeConnectionStatusHandler(HANDLER_ID);
      engine?.removeMessageHandler(HANDLER_ID);
    };
  }, [accessToken, queryClient, userId]);

  const value = useMemo(() => ({ status, enabled }), [status, enabled]);
  return <NexconnContext.Provider value={value}>{children}</NexconnContext.Provider>;
}

export function useNexconnStatus() {
  return useContext(NexconnContext);
}
