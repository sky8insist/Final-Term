import { request } from "../utils/request";
import type {
  MistakeRecord,
  ReviewProgress,
  UpdateReviewProgressPayload,
} from "../types/review";

export function getReviewProgress(subjectId: string) {
  return request<ReviewProgress>(`/review/${subjectId}/progress`);
}

export function updateReviewProgress(
  subjectId: string,
  payload: UpdateReviewProgressPayload,
) {
  return request<ReviewProgress>(`/review/${subjectId}/progress`, {
    method: "PATCH",
    body: payload,
  });
}

export function listMistakes(subjectId: string) {
  return request<MistakeRecord[]>(`/subjects/${subjectId}/mistakes`);
}
