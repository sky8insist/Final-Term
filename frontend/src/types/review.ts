export type ReviewProgress = {
  subjectId: string;
  masteredCount: number;
  totalCount: number;
  updatedAt: string | null;
};

export type UpdateReviewProgressPayload = {
  masteredCount?: number;
  totalCount?: number;
};

export type MistakeRecord = {
  id: string;
  subjectId: string;
  question: string;
  answer: string;
  note?: string;
  createdAt: string;
};
