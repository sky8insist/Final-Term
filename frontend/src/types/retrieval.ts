export type RetrievalCitation = {
  materialId: string;
  filename: string;
  chunkIndex: number;
  chunkText: string;
  score?: number | null;
};

export type RetrievalSearchRequest = {
  subjectId: string;
  question: string;
  topK?: number;
};

export type RetrievalSearchResponse = {
  subjectId: string;
  question: string;
  workspace: string;
  rawContext: string;
  citations: RetrievalCitation[];
};
