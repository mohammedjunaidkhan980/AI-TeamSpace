import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Spinner } from "../../../components/ui/spinner";
import { authApi } from "../../../services/api/auth-api";
import { useAuthStore } from "../../../stores/auth-store";
import { getErrorMessage } from "../../../utils/errors";
import { AuthShell } from "../components/auth-shell";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuthStore((state) => state.setSession);
  const mutation = useMutation({
    mutationFn: authApi.login,
    onSuccess: (result) => {
      setSession(result.access_token, result.user, result.expires_in);
      navigate("/dashboard", { replace: true });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ email: email.trim(), password });
  }

  const notice = (location.state as { registered?: boolean } | null)?.registered;

  return (
    <AuthShell>
      <div>
        <p className="text-sm font-semibold text-brand-600">Welcome back</p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Sign in to your workspace</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">Pick up where your team left off.</p>
      </div>
      {notice && <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">Account created. Sign in to get started.</div>}
      {mutation.isError && <p role="alert" className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{getErrorMessage(mutation.error, "Unable to sign in.")}</p>}
      <form className="mt-8 space-y-5" onSubmit={submit}>
        <label className="block space-y-2 text-sm font-medium text-slate-700">
          Email address
          <span className="relative block">
            <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input type="email" autoComplete="email" required maxLength={254} placeholder="you@company.com" value={email} onChange={(event) => setEmail(event.target.value)} className="pl-10" />
          </span>
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">
          Password
          <span className="relative block">
            <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input type={showPassword ? "text" : "password"} autoComplete="current-password" required maxLength={72} placeholder="Enter your password" value={password} onChange={(event) => setPassword(event.target.value)} className="pl-10 pr-12" />
            <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((value) => !value)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:text-slate-700">
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </span>
        </label>
        <Button type="submit" className="w-full" size="lg" disabled={mutation.isPending}>
          {mutation.isPending && <Spinner />} Sign in
        </Button>
      </form>
      <p className="mt-7 text-center text-sm text-slate-500">New to TeamSpace? <Link to="/register" className="font-semibold text-brand-600 hover:text-brand-700">Create an account</Link></p>
    </AuthShell>
  );
}
