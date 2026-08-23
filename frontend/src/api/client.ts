import { supabase } from '../lib/supabase';
import type { ChatMessage, DashboardData, Exam, ExamAttempt, ExamAttemptSummary, ExamDetail, ExamGenerateInput, ExamQuestionType, Material, MindMapData, MindMapGenerateInput, MindMapNode, ProcessingTask, QuestionGradingResult, StudyPlanInput, StudyPlanOverview, StudyPlanPreview, StudyTask, Subject, TutorRole } from '../types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public requestId?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

type BackendSubject = { id: string; name: string; description?: string | null; externalKnowledgeEnabled?: boolean; external_knowledge_enabled?: boolean };
type BackendTask = {
  id: string; subject_id?: string; subjectId?: string; title: string;
  scheduled_date?: string; scheduledDate?: string; estimated_minutes?: number;
  estimatedMinutes?: number; status: string; priority?: number; knowledge_key?: string;
  task_type?: string; source?: 'system' | 'user'; metadata?: StudyTask['metadata'];
};
type BackendMaterial = {
  id: string; subjectId: string; filename: string; contentType: string;
  fileSize: number; status: string; errorMessage?: string | null; createdAt: string;
};
type BackendExam = {
  id: string; title: string; status?: string; created_at?: string; createdAt?: string;
  question_count?: number; questionCount?: number; score?: number | null;
  question_types?: ExamQuestionType[]; questionTypes?: ExamQuestionType[];
  duration_minutes?: number; durationMinutes?: number; total_points?: number; totalPoints?: number;
  questions?: Array<Record<string, unknown>>;
  generation?: import('../types').ExamGeneration | null;
};
type BackendAttempt = {
  id: string; exam_id?: string; examId?: string; status: ExamAttempt['status'];
  started_at?: string; startedAt?: string; expires_at?: string; expiresAt?: string;
  score?: number | null; max_score?: number | null; maxScore?: number | null;
  exam: BackendExam; responses?: Record<string, unknown>; results?: Record<string, Record<string, unknown>>;
};
type BackendArtifact = {
  id?: string;
  title?: string;
  content?: Record<string, unknown> & { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
  citations?: Array<Record<string, unknown>>;
};
type CacheEnvelope<T> = { data: T; cachedAt: string; stale: true };

function announceCache(detail: { resource: string; cachedAt: string } | null) {
  window.dispatchEvent(new CustomEvent('examai-cache-status', { detail }));
}

async function sessionToken(refresh = false): Promise<string> {
  const result = refresh ? await supabase.auth.refreshSession() : await supabase.auth.getSession();
  const session = result.data.session;
  if (!session?.access_token) throw new ApiError('登录状态已失效，请重新登录。', 401, 'session_expired');
  return session.access_token;
}

async function authenticatedFetch(path: string, init?: RequestInit, allowRetry = true, timeoutMs = 45_000): Promise<Response> {
  const token = await sessionToken();
  const isForm = init?.body instanceof FormData;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时，请稍后重试。', 408, 'request_timeout');
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (response.status === 401 && allowRetry) {
    try {
      await sessionToken(true);
      return authenticatedFetch(path, init, false, timeoutMs);
    } catch {
      await supabase.auth.signOut();
      localStorage.removeItem('examai-access-token');
      throw new ApiError('登录状态已失效，请重新登录。', 401, 'session_expired');
    }
  }
  return response;
}

async function apiV1<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const response = await authenticatedFetch(path, init, true, timeoutMs);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error;
    const detail = error?.message || body?.detail;
    const validationMessage = Array.isArray(detail)
      ? detail.map((item) => String(item?.msg || item?.message || '')).filter(Boolean).join('；')
      : String(detail || '');
    throw new ApiError(
      validationMessage.includes('Practice topic is required')
        ? '请输入练习主题后再生成。'
        : validationMessage.includes('Confirmed answer cannot be changed')
          ? '该题答案已经确认，不能再次修改。'
          : validationMessage.includes('Exam attempt has expired')
            ? '本次练习已超时，已保存的答案仍会保留。'
            : validationMessage.includes('Exam attempt is not in progress')
              ? '本次练习已经结束，不能继续修改答案。'
        : validationMessage || `请求失败（${response.status}）`,
      response.status,
      error?.code,
      error?.requestId || response.headers.get('x-request-id') || undefined,
    );
  }
  return response.json() as Promise<T>;
}

async function saveCache<T>(resource: string, data: T, subjectId?: string) {
  try {
    await apiV1(`/workspace/cache/${resource}`, {
      method: 'PUT', body: JSON.stringify({ data, subjectId }),
    });
  } catch { /* Cache failure must never fail a successful primary request. */ }
}

async function loadCache<T>(resource: string, subjectId?: string): Promise<T> {
  const query = subjectId ? `?subjectId=${encodeURIComponent(subjectId)}` : '';
  const cached = await apiV1<CacheEnvelope<T>>(`/workspace/cache/${resource}${query}`);
  announceCache({ resource, cachedAt: cached.cachedAt });
  return cached.data;
}

async function cached<T>(resource: string, subjectId: string | undefined, loader: () => Promise<T>): Promise<T> {
  try {
    const data = await loader();
    announceCache(null);
    void saveCache(resource, data, subjectId);
    return data;
  } catch (error) {
    if (error instanceof ApiError && [401, 403, 404, 422].includes(error.status)) throw error;
    try { return await loadCache<T>(resource, subjectId); }
    catch { throw error; }
  }
}

function subjectFromApi(item: BackendSubject): Subject {
  return {
    id: item.id, name: item.name, description: item.description || '', progress: 0, mastery: 0,
    externalKnowledgeEnabled: item.externalKnowledgeEnabled ?? item.external_knowledge_enabled ?? false,
  };
}

function taskFromApi(item: BackendTask): StudyTask {
  const minutes = item.estimatedMinutes ?? item.estimated_minutes ?? 0;
  return {
    id: item.id,
    subjectId: item.subjectId ?? item.subject_id ?? '',
    title: item.title,
    time: `${minutes} 分钟`,
    completed: item.status === 'completed',
    scheduledDate: item.scheduledDate ?? item.scheduled_date,
    estimatedMinutes: Number(minutes), priority: item.priority,
    knowledgeKey: item.knowledge_key, taskType: item.task_type,
    source: item.source, status: item.status, metadata: item.metadata,
  };
}

function materialFromApi(item: BackendMaterial): Material {
  const status: Material['status'] = item.status === 'ready'
    ? 'indexed'
    : item.status === 'failed'
      ? 'failed'
      : item.status === 'queued'
        ? 'queued'
        : item.status === 'embedding'
          ? 'embedding'
          : item.status === 'indexing'
            ? 'indexing'
            : 'parsing';
  return {
    id: item.id, subjectId: item.subjectId, name: item.filename,
    type: item.filename.includes('.') ? item.filename.split('.').pop()!.toLowerCase() : item.contentType,
    status, size: item.fileSize, uploadedAt: item.createdAt,
    errorMessage: item.errorMessage,
  };
}

function examFromApi(item: BackendExam): Exam {
  return {
    id: item.id, title: item.title, score: item.score,
    questionCount: item.questionCount ?? item.question_count ?? 0,
    questionTypes: item.questionTypes ?? item.question_types,
    createdAt: item.createdAt ?? item.created_at,
    status: item.status,
  };
}

function examDetailFromApi(item: BackendExam): ExamDetail {
  return {
    ...examFromApi({ ...item, questionCount: item.questionCount ?? item.question_count ?? item.questions?.length ?? 0 }),
    durationMinutes: Number(item.durationMinutes ?? item.duration_minutes ?? 0),
    totalPoints: Number(item.totalPoints ?? item.total_points ?? 0),
    generation: item.generation ?? null,
    questions: (item.questions ?? []).map((question, index) => ({
      id: String(question.id ?? index),
      questionType: String(question.questionType ?? question.question_type ?? 'single_choice') as ExamQuestionType,
      stem: String(question.stem ?? ''),
      options: Array.isArray(question.options) ? question.options.map(String) : [],
      knowledgeKey: String(question.knowledgeKey ?? question.knowledge_key ?? ''),
      difficulty: String(question.difficulty ?? 'medium'),
      points: Number(question.points ?? 0),
      sequenceIndex: Number(question.sequenceIndex ?? question.sequence_index ?? index),
    })),
  };
}

function gradingResultFromApi(item: Record<string, unknown>): QuestionGradingResult {
  const earnedCriteria = item.earnedCriteria ?? item.earned_criteria;
  const missingCriteria = item.missingCriteria ?? item.missing_criteria;
  return {
    questionId: String(item.questionId ?? item.question_id ?? ''),
    earnedPoints: Number(item.earnedPoints ?? item.earned_points ?? 0),
    maxPoints: Number(item.maxPoints ?? item.max_points ?? 0),
    isCorrect: Boolean(item.isCorrect ?? item.is_correct),
    feedback: String(item.feedback ?? ''),
    earnedCriteria: Array.isArray(earnedCriteria) ? earnedCriteria.map(String) : [],
    missingCriteria: Array.isArray(missingCriteria) ? missingCriteria.map(String) : [],
    errorType: item.errorType == null && item.error_type == null ? null : String(item.errorType ?? item.error_type),
    correctAnswer: item.correctAnswer ?? item.correct_answer,
    explanation: String(item.explanation ?? ''),
    citations: Array.isArray(item.citations) ? item.citations.map(String) : [],
  };
}

function attemptFromApi(item: BackendAttempt): ExamAttempt {
  return {
    id: item.id,
    examId: String(item.examId ?? item.exam_id ?? item.exam?.id ?? ''),
    status: item.status,
    startedAt: String(item.startedAt ?? item.started_at ?? ''),
    expiresAt: String(item.expiresAt ?? item.expires_at ?? ''),
    score: item.score,
    maxScore: item.maxScore ?? item.max_score,
    exam: examDetailFromApi(item.exam),
    responses: item.responses ?? {},
    results: Object.fromEntries(Object.entries(item.results ?? {}).map(([questionId, result]) => [questionId, gradingResultFromApi(result)])),
  };
}

function finiteMastery(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(Math.max(parsed > 1 ? parsed / 100 : parsed, 0), 1);
}

function mindMapFromArtifact(artifact: BackendArtifact | null): MindMapData {
  const content = artifact?.content ?? {};
  const rows = content.nodes ?? [];
  const nodes: MindMapNode[] = rows.map((row, index) => ({
    id: String(row.id ?? index),
    parentId: row.parentId == null ? null : String(row.parentId),
    label: String(row.label ?? row.title ?? '未命名知识点'),
    type: String(row.type ?? row.nodeType ?? (row.parentId == null ? 'root' : 'concept')) as MindMapNode['type'],
    level: Number(row.level ?? (row.parentId == null ? 0 : 1)),
    importance: Number(row.importance ?? (row.parentId == null ? 1 : 0.5)),
    examImportance: String(row.examImportance ?? 'medium') as MindMapNode['examImportance'],
    mastery: finiteMastery(row.mastery),
    description: String(row.description ?? ''),
    sourceIds: (Array.isArray(row.sourceIds)
      ? row.sourceIds
      : Array.isArray(row.citationIds) ? row.citationIds : []).map(String),
    order: Number(row.order ?? index),
  }));
  const explicitEdges = content.edges ?? [];
  const edges = explicitEdges.length
    ? explicitEdges.map((edge) => ({
      source: String(edge.source ?? edge.from),
      target: String(edge.target ?? edge.to),
      relation: String(edge.relation ?? '关联'),
    }))
    : rows.flatMap((row) => row.parentId == null ? [] : [{
      source: String(row.parentId), target: String(row.id), relation: '包含',
    }]);
  const citations = artifact?.citations ?? [];
  return {
    artifactId: artifact?.id,
    title: String(content.title ?? artifact?.title ?? ''),
    focusQuestion: String(content.focusQuestion ?? ''),
    summary: String(content.summary ?? ''),
    mode: String(content.mode ?? 'topic') as MindMapData['mode'],
    evidenceInsufficient: Boolean(content.evidenceInsufficient),
    nodes,
    edges,
    evaluation: content.evaluation as MindMapData['evaluation'],
    sources: citations.map((item, index) => ({
      id: String(item.id ?? index),
      sourceName: String(item.filename ?? item.sourceName ?? '课程资料'),
      pageNumber: item.pageNumber == null ? undefined : Number(item.pageNumber),
      text: String(item.chunkText ?? item.text ?? ''),
    })),
  };
}

export const api = {
  currentUser: () => apiV1<{ id: string; email: string | null; role: string | null }>('/auth/me'),

  dashboard: () => cached<DashboardData>('dashboard', undefined, async () => {
    const [subjects, rawTasks] = await Promise.all([
      apiV1<BackendSubject[]>('/subjects'),
      apiV1<BackendTask[]>('/study-plans/today'),
    ]);
    const todayTasks = rawTasks.map(taskFromApi);
    return {
      subjects: subjects.map(subjectFromApi), todayTasks,
      stats: {
        studyMinutes: rawTasks.reduce((sum, task) => sum + Number(task.estimatedMinutes ?? task.estimated_minutes ?? 0), 0),
        completedTasks: todayTasks.filter((task) => task.completed).length,
        streakDays: 0,
      },
    };
  }),

  subjects: () => cached('subjects', undefined, async () => (await apiV1<BackendSubject[]>('/subjects')).map(subjectFromApi)),
  createSubject: async (payload: { name: string; description: string }) => subjectFromApi(await apiV1<BackendSubject>('/subjects', { method: 'POST', body: JSON.stringify(payload) })),
  setSubjectExternalKnowledge: (subjectId: string, enabled: boolean) => apiV1<BackendSubject>(`/subjects/${encodeURIComponent(subjectId)}`, {
    method: 'PATCH', body: JSON.stringify({ external_knowledge_enabled: enabled }),
  }),

  materials: async (subjectId: string) => (await apiV1<BackendMaterial[]>(`/materials?subject_id=${encodeURIComponent(subjectId)}`)).map(materialFromApi),
  addMaterial: async (subjectId: string, file: File) => {
    const form = new FormData();
    form.append('subject_id', subjectId);
    form.append('file', file);
    const result = await apiV1<{ material: BackendMaterial; task: ProcessingTask }>('/materials/uploads', { method: 'POST', body: form });
    return { material: materialFromApi(result.material), task: result.task };
  },
  task: (taskId: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(taskId)}`),
  tasks: (subjectId: string, activeOnly = false) => apiV1<ProcessingTask[]>(`/tasks?subject_id=${encodeURIComponent(subjectId)}&active_only=${activeOnly}`),

  chatHistory: (subjectId: string) => cached<ChatMessage[]>('chat', subjectId, () => apiV1(`/chat/history/${encodeURIComponent(subjectId)}`)),
  chat: async (payload: { subject_id: string; content: string; session_id: string; role: TutorRole; interaction_id?: string | null; knowledge_policy?: import('../types').KnowledgePolicy; dialogue_act_override?: import('../types').DialogueAct }) => {
    const result = await apiV1<{
      answer: string;
      citations?: ChatMessage['citations'];
      messageId: string;
      generation?: ChatMessage['generation'];
      role?: { id: string; name: string };
      memoryUpdates?: Array<{ status: string; type: string }>;
      dialogue?: ChatMessage['dialogue'];
      interaction?: ChatMessage['interaction'];
    }>('/assistant/messages', {
      method: 'POST',
      body: JSON.stringify({
        subjectId: payload.subject_id,
        message: payload.content,
        sessionId: payload.session_id,
        role: payload.role,
        interactionId: payload.interaction_id,
        knowledgePolicy: payload.knowledge_policy ?? 'course_only',
        allowExternalKnowledge: payload.knowledge_policy !== 'course_only',
        dialogueActOverride: payload.dialogue_act_override,
      }),
    });
    return {
      id: result.messageId,
      role: 'assistant' as const,
      content: result.answer,
      createdAt: new Date().toISOString(),
      citations: result.citations,
      generation: result.generation,
      tutorRole: result.role,
      memoryQueued: result.memoryUpdates?.some((update) => update.status === 'queued') ?? false,
      dialogue: result.dialogue,
      interaction: result.interaction,
    };
  },

  mindMap: (subjectId: string) => cached<MindMapData>('mind-map', subjectId, async () => {
    const artifacts = await apiV1<BackendArtifact[]>(`/artifacts?subject_id=${encodeURIComponent(subjectId)}&artifact_type=mind_map`);
    return mindMapFromArtifact(artifacts[0] ?? null);
  }),
  generateMindMap: async (payload: MindMapGenerateInput) => mindMapFromArtifact(await apiV1<BackendArtifact>('/artifacts/mind-maps', {
    method: 'POST',
    body: JSON.stringify({ ...payload, maxDepth: payload.maxDepth ?? 3, includeMastery: payload.includeMastery ?? true, count: 24 }),
  }, 120_000)),
  generateFlashcards: (subjectId: string, scope: string) => apiV1<BackendArtifact>('/artifacts/flashcards', {
    method: 'POST', body: JSON.stringify({ subjectId, scope, mode: 'knowledge', count: 10 }),
  }, 120_000),

  exams: (subjectId: string) => cached<Exam[]>('exams', subjectId, async () => (await apiV1<BackendExam[]>(`/exams?subject_id=${encodeURIComponent(subjectId)}`)).map(examFromApi)),
  createExam: async (payload: { subject_id: string; question_count: number; difficulty: string }) => examFromApi(await apiV1<BackendExam>('/exams', {
    method: 'POST',
    body: JSON.stringify({
      subjectId: payload.subject_id,
      title: '阶段练习',
      durationMinutes: Math.max(20, payload.question_count * 2),
      difficulty: payload.difficulty,
      questionTypes: [{ questionType: 'single_choice', count: payload.question_count, pointsEach: 5 }],
    }),
  })),
  queueExamGeneration: (payload: ExamGenerateInput) => apiV1<ProcessingTask>('/exams/generations', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  exam: async (examId: string) => examDetailFromApi(await apiV1<BackendExam>(`/exams/${encodeURIComponent(examId)}`)),
  startExamAttempt: async (examId: string) => attemptFromApi(await apiV1<BackendAttempt>('/exam-attempts', {
    method: 'POST', body: JSON.stringify({ examId }),
  })),
  examAttempt: async (attemptId: string) => attemptFromApi(await apiV1<BackendAttempt>(`/exam-attempts/${encodeURIComponent(attemptId)}`)),
  saveExamResponse: (attemptId: string, questionId: string, response: unknown) => apiV1(`/exam-attempts/${encodeURIComponent(attemptId)}/responses`, {
    method: 'PATCH', body: JSON.stringify({ questionId, response }),
  }),
  confirmExamResponse: async (attemptId: string, questionId: string, response: unknown) => gradingResultFromApi(await apiV1<Record<string, unknown>>(`/exam-attempts/${encodeURIComponent(attemptId)}/questions/${encodeURIComponent(questionId)}/confirm`, {
    method: 'POST', body: JSON.stringify({ response }),
  }, 90_000)),
  submitExamAttempt: async (attemptId: string): Promise<ExamAttemptSummary> => {
    const result = await apiV1<{ attemptId: string; score: number; maxScore: number; results: Array<Record<string, unknown>> }>(`/exam-attempts/${encodeURIComponent(attemptId)}/submit`, { method: 'POST' }, 120_000);
    return { ...result, results: result.results.map(gradingResultFromApi) };
  },

  plan: (subjectId?: string) => cached<StudyPlanOverview>('plan', subjectId, async () => {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    const overview = await apiV1<Omit<StudyPlanOverview, 'tasks'> & { tasks: BackendTask[] }>(`/study-plans/overview${query}`);
    return { ...overview, tasks: overview.tasks.map(taskFromApi) };
  }),
  previewPlan: (input: StudyPlanInput) => apiV1<StudyPlanPreview>('/study-plans/preview', { method: 'POST', body: JSON.stringify(input) }),
  generatePlan: (input: StudyPlanInput) => apiV1<ProcessingTask>('/study-plans/generations', { method: 'POST', body: JSON.stringify(input) }),
  planGeneration: (id: string) => apiV1<ProcessingTask>(`/study-plans/generations/${encodeURIComponent(id)}`),
  updateTask: async (taskId: string, completed: boolean) => taskFromApi(await apiV1<BackendTask>(`/study-plans/tasks/${encodeURIComponent(taskId)}`, { method: 'PATCH', body: JSON.stringify({ status: completed ? 'completed' : 'pending' }) })),

  saveWorkspaceState: (data: unknown) => saveCache('workspace', data),
};
