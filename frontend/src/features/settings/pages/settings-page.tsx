import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../../../components/shared/page-header";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../../components/ui/card";
import { ErrorState } from "../../../components/ui/error-state";
import { Input } from "../../../components/ui/input";
import { Skeleton } from "../../../components/ui/skeleton";
import { Spinner } from "../../../components/ui/spinner";
import { toast } from "../../../components/ui/toaster";
import { usersApi } from "../../../services/api/users-api";
import { useAuthStore } from "../../../stores/auth-store";
import { getErrorMessage } from "../../../utils/errors";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((state) => state.setUser);
  const query = useQuery({ queryKey: ["users", "me"], queryFn: usersApi.me });
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [bio, setBio] = useState("");
  const [statusMessage, setStatusMessage] = useState("");

  useEffect(() => {
    if (query.data) {
      setFullName(query.data.full_name);
      setUsername(query.data.username);
      setBio(query.data.bio ?? "");
      setStatusMessage(query.data.status_message ?? "");
    }
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: () => usersApi.updateMe({
      full_name: fullName.trim(),
      username: username.trim(),
      bio: bio.trim() || null,
      status_message: statusMessage.trim() || null,
    }),
    onSuccess: async (profile) => {
      setUser(profile);
      await queryClient.invalidateQueries({ queryKey: ["users", "me"] });
      toast({ variant: "success", title: "Profile updated" });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate();
  }

  if (query.isPending) return <div className="space-y-4"><Skeleton className="h-12 w-64" /><Skeleton className="h-80" /></div>;
  if (query.isError || !query.data) return <ErrorState message={getErrorMessage(query.error, "Could not load your profile.")} onRetry={() => void query.refetch()} />;

  return (
    <>
      <PageHeader title="Settings" description="Manage your personal profile and how you appear to teammates." />
      <Card className="max-w-2xl">
        <CardHeader><h2 className="font-semibold text-slate-900">Profile</h2><p className="mt-1 text-sm text-slate-500">Your email address is managed by your account and cannot be changed here.</p></CardHeader>
        <CardContent>
          {mutation.isError && <div className="mb-4"><ErrorState message={getErrorMessage(mutation.error, "Could not update your profile.")} /></div>}
          <form onSubmit={submit} className="space-y-5">
            <label className="block space-y-2 text-sm font-medium text-slate-700">Email address
              <Input type="email" readOnly value={query.data.email} className="bg-slate-50 text-slate-500" />
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Full name
              <Input required minLength={1} maxLength={100} value={fullName} onChange={(event) => setFullName(event.target.value)} />
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Username
              <Input required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" value={username} onChange={(event) => setUsername(event.target.value)} />
              <span className="block text-xs font-normal text-slate-400">3–32 letters, numbers, or underscores</span>
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Bio <span className="font-normal text-slate-400">(optional)</span>
              <textarea maxLength={500} rows={3} value={bio} onChange={(event) => setBio(event.target.value)} className="w-full resize-none rounded-xl border border-slate-200 px-3.5 py-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100" />
            </label>
            <label className="block space-y-2 text-sm font-medium text-slate-700">Status message <span className="font-normal text-slate-400">(optional)</span>
              <Input maxLength={100} value={statusMessage} onChange={(event) => setStatusMessage(event.target.value)} placeholder="What are you focused on?" />
            </label>
            <div className="flex justify-end"><Button type="submit" disabled={mutation.isPending}>{mutation.isPending && <Spinner />} Save profile</Button></div>
          </form>
        </CardContent>
      </Card>
    </>
  );
}
