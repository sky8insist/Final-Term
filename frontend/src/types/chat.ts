export type ChatRole = "user" | "assistant";

export type Citation = {
  id: string;
  materialId: string;
  sourceName: string;
  text: string;
  score?: number | null;
};

export type ChatMessage = {
  id: string;
  subjectId: string;
  role: ChatRole;
  content: string;
  citations?: Citation[];
  createdAt: string;
};

export type ChatRequest = {
  subjectId: string;
  question: string;
};

export type ChatResponse = {
  answer: string;
  citations: Citation[];
  messageId: string;
};
