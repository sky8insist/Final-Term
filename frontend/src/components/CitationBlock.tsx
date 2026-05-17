import type { Citation } from "../types/chat";

type CitationBlockProps = {
  citation: Citation;
};

export function CitationBlock({ citation }: CitationBlockProps) {
  return (
    <blockquote>
      <p>{citation.text}</p>
      <footer>{citation.sourceName}</footer>
    </blockquote>
  );
}
