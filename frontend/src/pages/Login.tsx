import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import {
  getCurrentSessionUser,
  getCurrentUser,
  login,
  logout,
  register,
} from "../api/auth";
import type { User } from "../types/user";

export function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [user, setUser] = useState<User | null>(null);
  const [backendUser, setBackendUser] = useState<User | null>(null);
  const [status, setStatus] = useState<string>("未登录");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function restoreSession() {
      try {
        const sessionUser = await getCurrentSessionUser();

        if (!isMounted || !sessionUser) {
          return;
        }

        setUser(sessionUser.user);
        setStatus("已恢复登录状态");
      } catch (error) {
        if (isMounted) {
          setStatus(error instanceof Error ? error.message : "恢复登录状态失败");
        }
      }
    }

    void restoreSession();

    return () => {
      isMounted = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setBackendUser(null);

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");
    const name = String(formData.get("name") ?? "");

    try {
      const result =
        mode === "login"
          ? await login({ email, password })
          : await register({ email, password, name });

      setUser(result.user);
      setStatus(mode === "login" ? "登录成功" : "注册成功");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "认证失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCheckBackend() {
    setIsLoading(true);

    try {
      const currentUser = await getCurrentUser();
      setBackendUser(currentUser);
      setStatus("后端已识别当前用户");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "后端认证失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleLogout() {
    setIsLoading(true);

    try {
      await logout();
      setUser(null);
      setBackendUser(null);
      setStatus("已退出登录");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "退出失败");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <h1>Exam AI</h1>
      <div>
        <button type="button" onClick={() => setMode("login")}>
          登录
        </button>
        <button type="button" onClick={() => setMode("register")}>
          注册
        </button>
      </div>
      <form onSubmit={handleSubmit}>
        {mode === "register" ? (
          <label>
            Name
            <input name="name" type="text" autoComplete="name" />
          </label>
        ) : null}
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
        <button type="submit" disabled={isLoading}>
          {mode === "login" ? "Login" : "Register"}
        </button>
      </form>

      <button type="button" onClick={handleCheckBackend} disabled={!user || isLoading}>
        Check backend session
      </button>
      <button type="button" onClick={handleLogout} disabled={!user || isLoading}>
        Logout
      </button>

      <p>{status}</p>
      {user ? <p>Supabase user: {user.email}</p> : null}
      {backendUser ? <p>Backend user id: {backendUser.id}</p> : null}
    </main>
  );
}
