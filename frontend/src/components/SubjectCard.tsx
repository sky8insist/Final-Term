import type { Subject } from "../types/subject";
import { formatDate } from "../utils/format";

type SubjectCardProps = {
  subject: Subject;
};

export function SubjectCard({ subject }: SubjectCardProps) {
  return (
    <article>
      <h2>{subject.name}</h2>
      <p>{subject.description}</p>
      <small>Updated {formatDate(subject.updatedAt)}</small>
    </article>
  );
}
