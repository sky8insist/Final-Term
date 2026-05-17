import type { Citation } from "../types/chat";
import { CitationBlock } from "./CitationBlock";

type AnswerCardProps = {
  answer: string;
  citations: Citation[];
};

export function AnswerCard({ answer, citations }: AnswerCardProps) {
  return (
    <article>
      <p>{answer}</p>
      {citations.map((citation) => (
        <CitationBlock key={citation.id} citation={citation} />
      ))}
    </article>
  );
}
