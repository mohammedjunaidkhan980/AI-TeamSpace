import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../../../stores/auth-store";

export function GuestRoute() {
  const token = useAuthStore((state) => state.accessToken);
  return token ? <Navigate to="/dashboard" replace /> : <Outlet />;
}
