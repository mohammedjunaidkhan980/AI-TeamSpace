import { useEffect, useState } from "react";
import { CheckCircle2, X, XCircle } from "lucide-react";

interface ToastMessage {
  id: number;
  title: string;
  description?: string;
  variant: "success" | "error";
}

type ToastInput = Omit<ToastMessage, "id">;

export function toast(message: ToastInput) {
  window.dispatchEvent(new CustomEvent<ToastInput>("teamspace-toast", { detail: message }));
}

export function Toaster() {
  const [messages, setMessages] = useState<ToastMessage[]>([]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<ToastInput>).detail;
      const id = Date.now() + Math.random();
      setMessages((current) => [...current, { ...detail, id }]);
      window.setTimeout(() => setMessages((current) => current.filter((item) => item.id !== id)), 4500);
    };
    window.addEventListener("teamspace-toast", handler);
    return () => window.removeEventListener("teamspace-toast", handler);
  }, []);

  return (
    <div className="fixed bottom-4 right-4 z-[70] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2" aria-live="polite">
      {messages.map((message) => (
        <div key={message.id} className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xl">
          {message.variant === "success" ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" /> : <XCircle className="mt-0.5 h-5 w-5 text-rose-600" />}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-slate-900">{message.title}</p>
            {message.description && <p className="mt-1 text-sm text-slate-500">{message.description}</p>}
          </div>
          <button type="button" aria-label="Dismiss notification" onClick={() => setMessages((current) => current.filter((item) => item.id !== message.id))} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
        </div>
      ))}
    </div>
  );
}
