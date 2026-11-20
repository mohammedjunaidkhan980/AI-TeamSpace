import { BrainCircuit, Sparkles } from "lucide-react";
import type { PropsWithChildren } from "react";

export function AuthShell({ children }: PropsWithChildren) {
  return (
    <main className="min-h-screen bg-white lg:grid lg:grid-cols-[1fr_0.92fr]">
      <section className="relative hidden overflow-hidden bg-[#f7f7fb] p-12 lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div className="absolute -right-36 -top-32 h-[34rem] w-[34rem] rounded-full border border-brand-100" />
        <div className="absolute -right-12 -top-8 h-[25rem] w-[25rem] rounded-full border border-brand-100/80" />
        <div className="absolute bottom-24 right-24 h-52 w-52 rounded-full bg-brand-100/50 blur-3xl" />
        <div className="relative z-10 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm"><BrainCircuit className="h-5 w-5" /></span>
          <span className="text-lg font-bold tracking-tight text-slate-900">TeamSpace</span>
        </div>
        <div className="relative z-10 max-w-xl">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-brand-100 bg-white/80 px-3 py-1.5 text-xs font-semibold text-brand-700">
            <Sparkles className="h-3.5 w-3.5" /> Collaboration, amplified
          </div>
          <h1 className="text-5xl font-semibold leading-[1.12] tracking-tight text-slate-950 xl:text-6xl">Your team.<br />Your AI agents.<br /><span className="text-brand-600">One workspace.</span></h1>
          <p className="mt-6 max-w-md text-base leading-7 text-slate-500">Bring people and specialized AI teammates together to move meaningful work forward.</p>
        </div>
        <p className="relative z-10 text-sm text-slate-400">A better way to think and build together.</p>
      </section>
      <section className="flex min-h-screen items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white"><BrainCircuit className="h-5 w-5" /></span>
            <span className="text-lg font-bold tracking-tight text-slate-900">TeamSpace</span>
          </div>
          {children}
          <p className="mt-10 text-center text-xs text-slate-400">By continuing, you agree to use TeamSpace responsibly.</p>
        </div>
      </section>
    </main>
  );
}
