import type { ChatMessage } from "../types/chat";

export type ChatState = {
  messages: ChatMessage[];
  loading: boolean;
};

export const chatStore: ChatState = {
  messages: [],
  loading: false,
};
