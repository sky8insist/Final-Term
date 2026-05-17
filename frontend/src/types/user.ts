export type User = {
  id: string;
  email: string | null;
  name?: string;
  createdAt?: string;
  role?: string | null;
};

export type LoginPayload = {
  email: string;
  password: string;
};

export type RegisterPayload = LoginPayload & {
  name?: string;
};
