import { supabase } from "../lib/supabase";
import type { LoginPayload, RegisterPayload, User } from "../types/user";
import { request } from "../utils/request";

function toUser(user: {
  id: string;
  email?: string;
  created_at?: string;
  user_metadata?: { name?: string };
}): User {
  return {
    id: user.id,
    email: user.email ?? null,
    name: user.user_metadata?.name,
    createdAt: user.created_at,
  };
}

export async function login(payload: LoginPayload) {
  const { data, error } = await supabase.auth.signInWithPassword(payload);

  if (error) {
    throw error;
  }

  if (!data.user || !data.session) {
    throw new Error("Login did not return a session");
  }

  return {
    user: toUser(data.user),
    token: data.session.access_token,
  };
}

export async function register(payload: RegisterPayload) {
  const { data, error } = await supabase.auth.signUp({
    email: payload.email,
    password: payload.password,
    options: {
      data: {
        name: payload.name,
      },
    },
  });

  if (error) {
    throw error;
  }

  if (!data.user || !data.session) {
    throw new Error("Registration did not return a session");
  }

  return {
    user: toUser(data.user),
    token: data.session.access_token,
  };
}

export function getCurrentUser() {
  return request<User>("/auth/me");
}

export async function getCurrentSessionUser() {
  const { data, error } = await supabase.auth.getSession();

  if (error) {
    throw error;
  }

  if (!data.session?.user) {
    return null;
  }

  return {
    user: toUser(data.session.user),
    token: data.session.access_token,
  };
}

export async function logout() {
  const { error } = await supabase.auth.signOut();

  if (error) {
    throw error;
  }
}
