import { FormEvent, useEffect, useMemo, useState } from 'react';
import { BookOpen, BrainCircuit, Lightbulb, Send, ShieldCheck, UserCheck } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { MarkdownViewer } from '../../components/MarkdownViewer';
import { useAppStore } from '../../stores/useAppStore';
import type { ChatMessage, KnowledgePolicy, TutorRole } from '../../types';

const modes = [
  { id: 'detail', name: '详细讲解', icon: BookOpen, role: 'beginner' },
  { id: 'quick', name: '快速复习', icon: Lightbulb, role: 'crash_course' },
  { id: 'socratic', name: '苏格拉底', icon: BrainCircuit, role: 'socratic' },
  { id: 'exam', name: '考官模式', icon: UserCheck, role: 'examiner' },
] as const;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function getOrCreateSessionId(userId: string, subjectId: string) {
  const key = `examai-study-session:${userId}:${subjectId}`;
  try {
    const stored = sessionStorage.getItem(key);
    if (stored && UUID_PATTERN.test(stored)) return stored;
    const sessionId = crypto.randomUUID();
    sessionStorage.setItem(key, sessionId);
    return sessionId;
  } catch {
    return crypto.randomUUID();
  }
}

export default function AIStudyRoom() {
  const subject = useAppStore((state) => state.currentSubject)!;
  const [searchParams] = useSearchParams();
  const planTopic = searchParams.get('topic') || '';
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<(typeof modes)[number]['id']>('detail');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [interactionId, setInteractionId] = useState<string | null>(null);
  const [knowledgePolicy, setKnowledgePolicy] = useState<KnowledgePolicy>(
    subject.externalKnowledgeEnabled ? 'course_first' : 'course_only',
  );
  const sessionId = useMemo(
    () => getOrCreateSessionId(user?.id ?? 'unknown-user', subject.id),
    [subject.id, user?.id],
  );

  useEffect(() => {
    api.chatHistory(subject.id).then(setMessages).catch((reason) => setError(reason.message));
    setInteractionId(null);
    setKnowledgePolicy(subject.externalKnowledgeEnabled ? 'course_first' : 'course_only');
  }, [subject.id, subject.externalKnowledgeEnabled]);

  async function changeKnowledgePolicy(next: KnowledgePolicy) {
    setKnowledgePolicy(next);
    try {
      await api.setSubjectExternalKnowledge(subject.id, next !== 'course_only');
    } catch (reason) {
      setKnowledgePolicy('course_only');
      setError(reason instanceof Error ? reason.message : '外部知识设置更新失败。');
    }
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem('message') as HTMLTextAreaElement;
    const content = input.value.trim();
    if (!content) return;

    setError('');
    setMessages((rows) => [
      ...rows,
      { id: crypto.randomUUID(), role: 'user', content, createdAt: new Date().toISOString() },
    ]);
    input.value = '';
    setSending(true);
    try {
      const selectedMode = modes.find((item) => item.id === mode)!;
      const reply = await api.chat({
        subject_id: subject.id,
        content,
        session_id: sessionId,
        role: selectedMode.role as TutorRole,
        interaction_id: interactionId,
        knowledge_policy: knowledgePolicy,
      });
      setInteractionId(reply.interaction?.expectsReply && reply.interaction.id ? reply.interaction.id : null);
      setMessages((rows) => [...rows, reply]);
    } catch (reason) {
      if (!input.value) input.value = content;
      setError(reason instanceof Error ? reason.message : '回答生成失败，请稍后重试。');
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full bg-white">
      <aside className="hidden w-60 shrink-0 border-r bg-slate-50 p-4 lg:block">
        <h2 className="mb-4 font-bold">学习模式</h2>
        <div className="space-y-2">
          {modes.map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              aria-pressed={mode === id}
              className={`flex w-full items-center rounded-xl p-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                mode === id
                  ? 'border border-blue-200 bg-blue-50 font-semibold text-blue-700'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Icon size={17} className="mr-2" />
              {name}
            </button>
          ))}
        </div>
        <label className="mt-6 block text-xs font-semibold text-slate-600" htmlFor="knowledge-policy">知识来源</label>
        <select
          id="knowledge-policy"
          value={knowledgePolicy}
          onChange={(event) => void changeKnowledgePolicy(event.target.value as KnowledgePolicy)}
          className="mt-2 w-full rounded-lg border border-slate-200 bg-white p-2 text-sm"
        >
          <option value="course_only">仅课程资料</option>
          <option value="course_first">课程优先，公开知识补充</option>
          <option value="expanded">扩展检索</option>
        </select>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="border-b px-6 py-4 font-bold">{subject.name} · AI 学习室</header>
        <div className="flex-1 space-y-6 overflow-y-auto p-5 md:p-8" aria-live="polite">
          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : ''}`}>
              <div
                className={`max-w-3xl rounded-2xl p-4 ${
                  message.role === 'user' ? 'bg-blue-600 text-white' : 'border border-slate-100 bg-slate-50'
                }`}
              >
                <MarkdownViewer content={message.content} />
                {message.generation && (
                  <div
                    className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800"
                    title={`模型：${message.generation.model}`}
                  >
                    <ShieldCheck size={15} aria-hidden="true" />
                    <span>真实模型调用</span>
                    <span aria-hidden="true">·</span>
                    <span>{message.generation.externalUsed ? '课程优先，已补充公开知识' : message.generation.grounded ? '基于课程资料' : '资料依据不足'}</span>
                    <span aria-hidden="true">·</span>
                    <span>{message.generation.citationCount} 条引用</span>
                    {message.memoryQueued && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>学习记忆整理中</span>
                      </>
                    )}
                  </div>
                )}
                {message.interaction?.expectsReply && (
                  <div className="mt-3 text-xs font-medium text-blue-700">正在等待你回答当前引导问题</div>
                )}
                {message.citations?.map((citation) => (
                  <div key={citation.id} className="mt-3 rounded-lg border bg-white p-3 text-xs text-slate-600">
                    [{citation.sourceType === 'external' ? '公开知识 · ' : ''}{citation.sourceName}{citation.pageNumber ? ` P${citation.pageNumber}` : ''}] {citation.text}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {sending && <div className="text-sm text-slate-500" role="status">正在检索课程资料并组织回答…</div>}
          {error && <div className="text-rose-600" role="alert">{error}</div>}
        </div>

        <form onSubmit={send} className="border-t p-4">
          <div className="relative mx-auto max-w-4xl">
            <label htmlFor="ai-study-question" className="sr-only">向 AI 提问</label>
            <textarea
              id="ai-study-question"
              name="message"
              rows={3}
              maxLength={4000}
              disabled={sending}
              defaultValue={planTopic ? `请通过苏格拉底追问帮助我检验对“${planTopic}”的理解。` : ''}
              placeholder={`向 AI 提问关于 ${subject.name} 的问题…`}
              className="w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 p-4 pr-14 outline-none transition-colors focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            />
            <button
              disabled={sending}
              aria-label="发送问题"
              className="absolute bottom-3 right-3 rounded-xl bg-blue-600 p-2 text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send size={18} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
