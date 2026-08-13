import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  content: string;
}

export function MarkdownViewer({ content }: Props) {
  return (
    <div className="prose prose-slate prose-sm md:prose-base max-w-none prose-headings:font-bold prose-a:text-blue-600 prose-img:rounded-xl">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
