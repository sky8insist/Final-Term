import type { User } from "../types/user";

export type UserState = {
  user: User | null;
  token: string | null;
};

export const userStore: UserState = {
  user: null,
  token: null,
};
