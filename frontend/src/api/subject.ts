import { request } from "../utils/request";
import type { CreateSubjectPayload, Subject } from "../types/subject";

export function listSubjects() {
  return request<Subject[]>("/subjects");
}

export function getSubject(subjectId: string) {
  return request<Subject>(`/subjects/${subjectId}`);
}

export function createSubject(payload: CreateSubjectPayload) {
  return request<Subject>("/subjects", {
    method: "POST",
    body: payload,
  });
}

export function updateSubject(subjectId: string, payload: Partial<CreateSubjectPayload>) {
  return request<Subject>(`/subjects/${subjectId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function deleteSubject(subjectId: string) {
  return request<void>(`/subjects/${subjectId}`, {
    method: "DELETE",
  });
}
