import { supabase } from '../lib/supabase';
import type { ChatMessage, DashboardData, Exam, Material, MindMapData, Mistake, ProcessingTask, StudyTask, Subject } from '../types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public requestId?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

type BackendSubject = { id: string; name: string; description?: string | null };
type BackendTask = {
  id: string; subject_id?: string; subjectId?: string; title: string;
  scheduled_date?: string; scheduledDate?: string; estimated_minutes?: number;
  estimatedMinutes?: number; status: string;
};
type BackendMaterial = {
  id: string; subjectId: string; filename: string; contentType: string;
  fileSize: number; status: string; errorMessage?: string | null; createdAt: string;
};
type BackendExam = {
  id: string; title: string; status?: string; created_at?: string; createdAt?: string;
  question_count?: number; questionCount?: number; score?: number | null;
};
type BackendWrongAnswer = {
  id: string; error_type?: string; diagnosis?: string; created_at?: string;
  question_id?: string; question?: string; myAnswer?: string; correctAnswer?: string;
  topic?: string; reason?: string; createdAt?: string;
};
type BackendArtifact = { content?: { nodes?: Array<Record<string, unknown>> } };
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

async function authenticatedFetch(path: string, init?: RequestInit, allowRetry = true): Promise<Response> {
  const token = await sessionToken();
  const isForm = init?.body instanceof FormData;
  const response = await fetch(`${baseUrl}/api/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (response.status === 401 && allowRetry) {
    try {
      await sessionToken(true);
      return authenticatedFetch(path, init, false);
    } catch {
      await supabase.auth.signOut();
      localStorage.removeItem('examai-access-token');
      throw new ApiError('登录状态已失效，请重新登录。', 401, 'session_expired');
    }
  }
  return response;
}

async function apiV1<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error;
    throw new ApiError(
      error?.message || body?.detail || `请求失败（${response.status}）`,
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
    await saveCache(resource, data, subjectId);
    return data;
  } catch (error) {
    if (error instanceof ApiError && [401, 403, 404, 422].includes(error.status)) throw error;
    try { return await loadCache<T>(resource, subjectId); }
    catch { throw error; }
  }
}

function subjectFromApi(item: BackendSubject): Subject {
  return { id: item.id, name: item.name, description: item.description || '', progress: 0, mastery: 0 };
}

function taskFromApi(item: BackendTask): StudyTask {
  const minutes = item.estimatedMinutes ?? item.estimated_minutes ?? 0;
  return {
    id: item.id,
    subjectId: item.subjectId ?? item.subject_id ?? '',
    title: item.title,
    time: `${minutes} 分钟`,
    completed: item.status === 'completed',
  };
}

function materialFromApi(item: BackendMaterial): Material {
  const readyStatus = item.status === 'ready' ? 'indexed' : item.status === 'failed' ? 'failed' : item.status === 'queued' ? 'queued' : 'parsing';
  return {
    id: item.id, subjectId: item.subjectId, name: item.filename,
    type: item.filename.includes('.') ? item.filename.split('.').pop()!.toLowerCase() : item.contentType,
    status: readyStatus, size: item.fileSize, uploadedAt: item.createdAt,
    errorMessage: item.errorMessage,
  };
}

function examFromApi(item: BackendExam): Exam {
  return {
    id: item.id, title: item.title, score: item.score,
    questionCount: item.questionCount ?? item.question_count ?? 0,
    createdAt: item.createdAt ?? item.created_at,
    status: item.status,
  };
}

function mindMapFromArtifact(artifact: BackendArtifact | null): MindMapData {
  const rows = artifact?.content?.nodes ?? [];
  const nodes = rows.map((row, index) => ({
    id: String(row.id ?? index),
    label: String(row.title ?? row.label ?? '未命名知识点'),
    level: Number(row.level ?? (row.parentId == null ? 0 : 1)),
    mastery: Number(row.mastery ?? 0),
  }));
  const edges = rows.flatMap((row) => row.parentId == null ? [] : [{ from: String(row.parentId), to: String(row.id) }]);
  return { nodes, edges };
}

function mistakeFromApi(item: BackendWrongAnswer): Mistake {
  return {
    id: item.id,
    topic: item.topic || item.error_type || '待复习知识点',
    question: item.question || `题目 ${item.question_id?.slice(0, 8) || ''}`,
    myAnswer: item.myAnswer || '未记录',
    correctAnswer: item.correctAnswer || '请进入试卷查看参考答案',
    reason: item.reason || item.diagnosis || '需要进一步复习该知识点。',
    createdAt: item.createdAt || item.created_at || '',
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

  materials: async (subjectId: string) => (await apiV1<BackendMaterial[]>(`/materials?subject_id=${encodeURIComponent(subjectId)}`)).map(materialFromApi),
  addMaterial: async (subjectId: string, file: File) => {
    const form = new FormData();
    form.append('subject_id', subjectId);
    form.append('file', file);
    const result = await apiV1<{ material: BackendMaterial; task: ProcessingTask }>('/materials/uploads', { method: 'POST', body: form });
    return { material: materialFromApi(result.material), task: result.task };
  },
  task: (taskId: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(taskId)}`),

  chatHistory: (subjectId: string) => cached<ChatMessage[]>('chat', subjectId, () => apiV1(`/chat/history/${encodeURIComponent(subjectId)}`)),
  chat: async (payload: { subject_id: string; content: string; mode: string }) => {
    const result = await apiV1<{ answer: string; citations?: ChatMessage['citations']; messageId: string }>('/chat/ask', {
      method: 'POST',
      body: JSON.stringify({ subjectId: payload.subject_id, question: payload.content }),
    });
    return { id: result.messageId, role: 'assistant' as const, content: result.answer, createdAt: new Date().toISOString(), citations: result.citations };
  },

  mindMap: (subjectId: string) => cached<MindMapData>('mind-map', subjectId, async () => {
    const artifacts = await apiV1<BackendArtifact[]>(`/artifacts?subject_id=${encodeURIComponent(subjectId)}&artifact_type=mind_map`);
    return mindMapFromArtifact(artifacts[0] ?? null);
  }),
  generateMindMap: async (subjectId: string) => mindMapFromArtifact(await apiV1<BackendArtifact>('/artifacts/mind-maps', { method: 'POST', body: JSON.stringify({ subjectId, count: 20 }) })),

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

  mistakes: (subjectId: string) => cached<Mistake[]>('mistakes', subjectId, async () => (await apiV1<BackendWrongAnswer[]>(`/exams/wrong-answers/${encodeURIComponent(subjectId)}?resolved=false`)).map(mistakeFromApi)),

  plan: (subjectId?: string) => cached('plan', subjectId, async () => {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    const overview = await apiV1<{ tasks: BackendTask[] }>(`/study-plans/overview${query}`);
    const today = new Date();
    const week = Array.from({ length: 7 }, (_, index) => {
      const day = new Date(today); day.setDate(today.getDate() + index); return day.toISOString().slice(0, 10);
    });
    return { date: week[0], tasks: overview.tasks.map(taskFromApi), week };
  }),
  updateTask: async (taskId: string, completed: boolean) => taskFromApi(await apiV1<BackendTask>(`/study-plans/tasks/${encodeURIComponent(taskId)}`, { method: 'PATCH', body: JSON.stringify({ status: completed ? 'completed' : 'pending' }) })),

  saveWorkspaceState: (data: unknown) => saveCache('workspace', data),
};
