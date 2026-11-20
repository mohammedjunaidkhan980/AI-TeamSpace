import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { UserProfile } from "../types/api";

interface AuthState {
  user: UserProfile | null;
  accessToken: string | null;
  tokenExpiresAt: number | null;
  setSession: (accessToken: string, user: UserProfile, expiresIn: number) => void;
  setUser: (user: UserProfile) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      tokenExpiresAt: null,
      setSession: (accessToken, user, expiresIn) => set({
        accessToken,
        user,
        tokenExpiresAt: Date.now() + expiresIn * 1000,
      }),
      setUser: (user) => set({ user }),
      clearSession: () => set({ user: null, accessToken: null, tokenExpiresAt: null }),
    }),
    {
      name: "ai-teamspace-session",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        tokenExpiresAt: state.tokenExpiresAt,
      }),
    },
  ),
);
