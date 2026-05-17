import type { Subject } from "../types/subject";

export type SubjectState = {
  subjects: Subject[];
  currentSubject: Subject | null;
};

export const subjectStore: SubjectState = {
  subjects: [],
  currentSubject: null,
};
