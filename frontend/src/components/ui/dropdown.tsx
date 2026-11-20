import { ChevronDown } from "lucide-react";
import type { PropsWithChildren, ReactNode } from "react";

interface DropdownProps extends PropsWithChildren {
  label: string;
  trigger: ReactNode;
}

export function Dropdown({ label, trigger, children }: DropdownProps) {
  return (
    <details className="group relative">
      <summary aria-label={label} className="flex cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden">
        {trigger}
        <ChevronDown className="h-4 w-4 text-slate-400" aria-hidden="true" />
      </summary>
      <div role="menu" aria-label={label} className="absolute right-0 z-30 mt-2 min-w-48 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
        {children}
      </div>
    </details>
  );
}

export function DropdownItem({ children, onClick, destructive = false }: PropsWithChildren<{ onClick: () => void; destructive?: boolean }>) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center rounded-lg px-3 py-2 text-left text-sm transition ${destructive ? "text-rose-600 hover:bg-rose-50" : "text-slate-700 hover:bg-slate-50"}`}
    >
      {children}
    </button>
  );
}
