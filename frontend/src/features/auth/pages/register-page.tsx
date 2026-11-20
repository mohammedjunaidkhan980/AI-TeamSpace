import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Spinner } from "../../../components/ui/spinner";
import { authApi } from "../../../services/api/auth-api";
import { getErrorMessage } from "../../../utils/errors";
import { AuthShell } from "../components/auth-shell";

export function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [validationError, setValidationError] = useState("");
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: authApi.register,
    onSuccess: () => navigate("/login", { replace: true, state: { registered: true } }),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError("");
    if (password.length < 8) return setValidationError("Password must be at least 8 characters.");
    if (new TextEncoder().encode(password).length > 72) return setValidationError("Password must not exceed 72 UTF-8 bytes.");
    if (password !== confirmPassword) return setValidationError("Passwords do not match.");
    if (!/^[A-Za-z0-9_]{3,32}$/.test(username)) return setValidationError("Username must be 3–32 letters, numbers, or underscores.");
    mutation.mutate({ full_name: fullName.trim(), username, email: email.trim(), password });
  }

  const error = validationError || (mutation.isError ? getErrorMessage(mutation.error, "Unable to create account.") : "");

  return (
    <AuthShell>
      <div>
        <p className="text-sm font-semibold text-brand-600">Get started for free</p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Create your account</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">Set up your space and invite your team when you’re ready.</p>
      </div>
      {error && <p role="alert" className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>}
      <form className="mt-7 space-y-4" onSubmit={submit}>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Full name
          <Input autoComplete="name" required maxLength={100} value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder="Alex Morgan" />
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Username
          <Input autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="alexmorgan" />
          <span className="block text-xs font-normal text-slate-400">3–32 letters, numbers, or underscores</span>
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Email address
          <Input type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Password
          <span className="relative block">
            <Input type={showPassword ? "text" : "password"} autoComplete="new-password" required minLength={8} maxLength={72} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" className="pr-12" />
            <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((value) => !value)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:text-slate-700">
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </span>
        </label>
        <label className="block space-y-2 text-sm font-medium text-slate-700">Confirm password
          <Input type={showPassword ? "text" : "password"} autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Enter your password again" />
        </label>
        <Button type="submit" className="w-full" size="lg" disabled={mutation.isPending}>
          {mutation.isPending && <Spinner />} Create account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">Already have an account? <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">Sign in</Link></p>
    </AuthShell>
  );
}
