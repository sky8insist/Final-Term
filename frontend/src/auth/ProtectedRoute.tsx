import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { LoaderCircle } from 'lucide-react';
import { useAuth } from './AuthProvider';

export function ProtectedRoute() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <div className="auth-loading" role="status" aria-live="polite">
      <LoaderCircle aria-hidden="true" />
      <span>正在恢复你的学习档案…</span>
    </div>;
  }

  return user ? <Outlet /> : <Navigate to="/auth/login" replace state={{ from: location }} />;
}
