import { request } from "../utils/request";
import type { ChatMessage, ChatRequest, ChatResponse } from "../types/chat";

export function askQuestion(payload: ChatRequest) {
  return request<ChatResponse>("/chat/ask", {
    method: "POST",
    body: payload,
  });
}

export function listChatHistory(subjectId: string) {
  return request<ChatMessage[]>(`/chat/history/${subjectId}`);
}
