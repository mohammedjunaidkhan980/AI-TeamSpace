import {
  ArrowDown,
  ArrowRight,
  Bot,
  FileText,
  MessageSquareText,
  UsersRound,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useAuthStore } from "../../../stores/auth-store";
import "./landing-page.css";

const features = [
  {
    number: "01",
    icon: MessageSquareText,
    title: "Talk where the work is",
    description:
      "Keep group conversations connected to the people, files, and decisions they belong to.",
    color: "coral",
  },
  {
    number: "02",
    icon: FileText,
    title: "Bring the docs along",
    description:
      "Upload shared documents and let AI search relevant passages when the team asks a question.",
    color: "blue",
  },
  {
    number: "03",
    icon: Bot,
    title: "Add the right brain",
    description:
      "Bring in focused AI teammates for research, writing, coding, analysis, and planning.",
    color: "green",
  },
];

const workflow = [
  { number: "01", label: "Your group asks" },
  { number: "02", label: "Context gets found" },
  { number: "03", label: "Agents get to work" },
  { number: "04", label: "The answer comes back" },
];

export function LandingPage() {
  const isAuthenticated = Boolean(useAuthStore((state) => state.accessToken));

  return (
    <main className="landing-root">
      <section className="landing-hero relative isolate flex min-h-[82vh] flex-col overflow-hidden text-white">
        <img
          className="absolute inset-0 -z-20 h-full w-full object-cover object-center"
          src="https://images.unsplash.com/photo-1521737711867-e3b97375f902?auto=format&fit=crop&w=2400&q=85"
          alt="A team working together around a table"
          fetchPriority="high"
        />
        <div className="absolute inset-0 -z-10 bg-[#10231f]/65" />

        <header className="mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-12">
          <Link to="/" className="flex items-center gap-2.5" aria-label="AI TeamSpace home">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#d7f45b] font-bold text-[#172525]">TS</span>
            <span className="landing-display text-sm font-bold tracking-wide">AI TeamSpace</span>
          </Link>
          <nav className="flex items-center gap-3 sm:gap-6" aria-label="Main navigation">
            <a className="hidden text-sm text-white/80 transition hover:text-white sm:inline" href="#workspace">The workspace</a>
            <Link className="text-sm font-medium text-white/90 transition hover:text-white" to="/login">Sign in</Link>
            <Link className="landing-nav-cta inline-flex items-center gap-2 rounded-full bg-[#d7f45b] px-4 py-2.5 text-sm font-bold text-[#172525] transition hover:bg-white" to={isAuthenticated ? "/dashboard" : "/register"}>
              {isAuthenticated ? "Open workspace" : "Get started"}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </nav>
        </header>

        <div className="landing-hero-copy mx-auto flex w-full max-w-7xl flex-1 flex-col justify-center px-5 pb-12 pt-10 sm:px-8 lg:px-12">
          <p className="mb-5 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[#d7f45b] sm:text-sm">
            <span className="h-2 w-2 rounded-full bg-[#ff7771]" />
            Less context switching. More team momentum.
          </p>
          <h1 className="landing-display max-w-4xl text-6xl font-bold leading-[0.94] sm:text-7xl lg:text-8xl">
            AI TeamSpace<span className="text-[#d7f45b]">.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-7 text-white/85 sm:text-xl sm:leading-8">
            Your group chat, shared docs, and specialist AI teammates - all in the same context.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link className="inline-flex min-h-12 items-center gap-2 rounded-full bg-[#d7f45b] px-6 text-sm font-bold text-[#172525] transition hover:bg-white" to={isAuthenticated ? "/dashboard" : "/register"}>
              {isAuthenticated ? "Go to your workspace" : "Create your workspace"}
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a className="inline-flex min-h-12 items-center gap-2 rounded-full border border-white/40 px-5 text-sm font-semibold text-white transition hover:border-white hover:bg-white/10" href="#workspace">
              Take a look <ArrowDown className="h-4 w-4" />
            </a>
          </div>
          <div className="mt-12 flex flex-wrap gap-x-7 gap-y-3 text-sm font-medium text-white/75">
            <span className="inline-flex items-center gap-2"><MessageSquareText className="h-4 w-4 text-[#d7f45b]" /> Group chat</span>
            <span className="inline-flex items-center gap-2"><FileText className="h-4 w-4 text-[#ff7771]" /> Shared knowledge</span>
            <span className="inline-flex items-center gap-2"><Bot className="h-4 w-4 text-[#9db3ff]" /> AI teammates</span>
          </div>
        </div>
        <div className="landing-hero-index mx-auto flex w-full max-w-7xl items-center justify-between px-5 pb-5 text-[10px] font-semibold uppercase tracking-[0.15em] text-white/55 sm:px-8 lg:px-12">
          <span>One space for the whole team</span>
          <span className="hidden sm:inline">Built to keep the thread</span>
        </div>
      </section>

      <section id="workspace" className="bg-[#f5f6ed] px-5 py-20 sm:px-8 sm:py-24 lg:px-12">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#486bff]">The work stays connected</p>
            <h2 className="landing-display mt-4 text-4xl font-bold leading-tight text-[#172525] sm:text-5xl">
              Less hunting for context.<br className="hidden sm:block" /> More moving things forward.
            </h2>
          </div>
          <div className="mt-14 grid gap-10 border-t border-[#cbd4ca] pt-8 md:grid-cols-3 md:gap-7">
            {features.map(({ number, icon: Icon, title, description, color }) => (
              <article className="landing-feature" key={number}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold tracking-widest text-[#71847c]">{number}</span>
                  <Icon className={`h-5 w-5 landing-icon-${color}`} strokeWidth={1.8} />
                </div>
                <h3 className="landing-display mt-8 text-2xl font-bold text-[#172525]">{title}</h3>
                <p className="mt-3 max-w-sm text-base leading-7 text-[#526660]">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[#172525] px-5 py-20 text-white sm:px-8 sm:py-24 lg:px-12">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-end">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#d7f45b]">From question to next step</p>
            <h2 className="landing-display mt-4 max-w-xl text-4xl font-bold leading-tight sm:text-5xl">A shared brain, not another tab.</h2>
            <p className="mt-5 max-w-lg text-base leading-7 text-white/65">TeamSpace brings group conversation and relevant document context into AI workflows, so the answer can start closer to where your team already is.</p>
          </div>
          <ol className="grid gap-0 sm:grid-cols-2">
            {workflow.map((step, index) => (
              <li className="landing-step flex items-start gap-4 border-t border-white/20 py-5" key={step.number}>
                <span className={`landing-step-number ${index === 2 ? "text-[#ff7771]" : "text-[#d7f45b]"}`}>{step.number}</span>
                <span className="landing-display text-lg font-semibold text-white">{step.label}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="bg-[#d7f45b] px-5 py-16 sm:px-8 lg:px-12">
        <div className="mx-auto flex max-w-7xl flex-col gap-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#486bff]">Your team's next move</p>
            <h2 className="landing-display mt-3 max-w-2xl text-4xl font-bold leading-tight text-[#172525] sm:text-5xl">Keep good work in motion.</h2>
          </div>
          <Link className="inline-flex min-h-12 w-fit items-center gap-3 rounded-full bg-[#172525] px-6 text-sm font-bold text-white transition hover:bg-[#344a43]" to={isAuthenticated ? "/dashboard" : "/register"}>
            {isAuthenticated ? "Open workspace" : "Join AI TeamSpace"}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <footer className="bg-[#f5f6ed] px-5 py-7 sm:px-8 lg:px-12">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 text-sm text-[#526660] sm:flex-row sm:items-center sm:justify-between">
          <Link to="/" className="landing-display flex items-center gap-2 font-bold text-[#172525]">
            <UsersRound className="h-4 w-4 text-[#486bff]" /> AI TeamSpace
          </Link>
          <span>Your team. Your context. One shared space.</span>
          <div className="flex gap-5">
            <Link className="hover:text-[#172525]" to="/login">Sign in</Link>
            <Link className="hover:text-[#172525]" to="/register">Create account</Link>
          </div>
        </div>
      </footer>
    </main>
  );
}