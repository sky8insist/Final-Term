import { supabase } from '../lib/supabase';
import { readVersioned, type ResourceVersion, type VerifiedSnapshot } from './versionedCache';
import type { MaterialPurpose, MaterialProcessing } from '../types';
import type { ChatMessage, DashboardData, DialogueAct, Exam, ExamAttempt, ExamAttemptSummary, ExamDetail, ExamGenerateInput, ExamGeneration, ExamQuestionType, KnowledgePolicy, Material, MindMapData, MindMapGenerateInput, MindMapNode, ProcessingTask, QuestionGradingResult, StudyPlanInput, StudyPlanOverview, StudyPlanPreview, StudyTask, Subject, TutorRole } from '../types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public requestId?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

type BackendSubject = { id: string; name: string; description?: string | null; externalKnowledgeEnabled?: boolean; external_knowledge_enabled?: boolean };
type BackendTask = {
  locked?: boolean;
  id: string; subject_id?: string; subjectId?: string; title: string;
  scheduled_date?: string; scheduledDate?: string; estimated_minutes?: number;
  estimatedMinutes?: number; status: string; priority?: number; knowledge_key?: string;
  task_type?: string; source?: 'system' | 'user'; metadata?: StudyTask['metadata'];
};
type BackendMaterial = {
  id: string; subjectId: string; filename: string; contentType: string;
  fileSize: number; status: string; errorMessage?: string | null; createdAt: string;
  materialPurpose?: MaterialPurpose;
};
type BackendExam = {
  assessment_mode?: 'formal' | 'adaptive';
  id: string; title: string; status?: string; created_at?: string; createdAt?: string;
  question_count?: number; questionCount?: number; score?: number | null;
  question_types?: ExamQuestionType[]; questionTypes?: ExamQuestionType[];
  duration_minutes?: number; durationMinutes?: number; total_points?: number; totalPoints?: number;
  questions?: Array<Record<string, unknown>>;
  generation?: ExamGeneration | null;
};
type BackendAttempt = {
  adaptive_state?: ExamAttempt['adaptiveState'];
  id: string; exam_id?: string; examId?: string; status: ExamAttempt['status'];
  started_at?: string; startedAt?: string; expires_at?: string; expiresAt?: string;
  score?: number | null; max_score?: number | null; maxScore?: number | null;
  exam: BackendExam; responses?: Record<string, unknown>; results?: Record<string, Record<string, unknown>>;
  learnerConfidences?: Record<string, number | null>;
};
type BackendArtifact = {
  subject_id?: string;
  artifact_type?: string;
  version?: number;
  id?: string;
  title?: string;
  content?: Record<string, unknown> & { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
  citations?: Array<Record<string, unknown>>;
};

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

export type DayendActivity = {
  event: 'run_started' | 'agent_started' | 'agent_completed' | 'graph_updated' | 'confirmation_required' | 'run_failed' | 'run_completed';
  data: Record<string, unknown>;
};

async function apiV3<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await sessionToken();
  const response = await fetch(`${baseUrl}/api/v3${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) throw new ApiError((await response.json().catch(() => null))?.detail || `请求失败（${response.status}）`, response.status);
  return response.json() as Promise<T>;
}

async function streamDayendRun(payload: { userInput: string; entryPoint?: string; threadId?: string }, onEvent: (event: DayendActivity) => void) {
  const token = await sessionToken();
  const response = await fetch(`${baseUrl}/api/v3/runs/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) throw new ApiError((await response.json().catch(() => null))?.detail || '无法启动夜间流程。', response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const next = await reader.read();
    if (next.done) break;
    buffer += decoder.decode(next.value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const event = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (event && data) onEvent({ event: event as DayendActivity['event'], data: JSON.parse(data) });
    }
  }
}

async function resourceVersion(resource:string,subjectId?:string):Promise<ResourceVersion> {
  return apiV1(`/workspace/cache/${encodeURIComponent(resource)}/version${subjectId?`?subjectId=${encodeURIComponent(subjectId)}`:''}`,undefined,3000);
}

async function saveCache<T>(resource: string, data: T, subjectId?: string, expectedVersion?:string) {
  try {
    const version=expectedVersion??(await resourceVersion(resource,subjectId)).version;
    await apiV1(`/workspace/cache/${resource}`, {
      method: 'PUT', body: JSON.stringify({ data, subjectId, expectedVersion:version }),
    },3000);
  } catch { /* Cache failure must never fail a successful primary request. */ }
}

async function loadCache<T>(resource: string, subjectId?: string): Promise<VerifiedSnapshot<T>> {
  const query = subjectId ? `?subjectId=${encodeURIComponent(subjectId)}` : '';
  return apiV1<VerifiedSnapshot<T>>(`/workspace/cache/${resource}${query}`,undefined,5000);
}

async function cached<T>(resource: string, subjectId: string | undefined, loader: () => Promise<T>): Promise<T> {
  return readVersioned({resource,subjectId,loader,
    owner:async()=> (await supabase.auth.getSession()).data.session?.user.id??null,
    version:()=>resourceVersion(resource,subjectId),load:()=>loadCache<T>(resource,subjectId),
    save:(data,version)=>saveCache(resource,data,subjectId,version),
    announce:detail=>window.dispatchEvent(new CustomEvent('examai-cache-status',{detail})),
    failure:reason=>new ApiError(reason==='owner_changed'?'登录账户已变化，请重新读取。':'学习记录持续变化，请刷新后重试。',reason==='owner_changed'?401:409),
  });
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
    locked: item.locked ?? false,
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
    materialPurpose: item.materialPurpose ?? 'learning',
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
    assessmentMode: item.assessment_mode ?? 'formal',
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
    learnerConfidence: item.learnerConfidence == null ? null : Number(item.learnerConfidence),
    confidenceMismatch: item.confidenceMismatch == null ? null : Number(item.confidenceMismatch),
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
    learnerConfidences: item.learnerConfidences ?? {},
    adaptiveState: item.adaptive_state ?? {},
    results: Object.fromEntries(Object.entries(item.results ?? {}).map(([questionId, result]) => [questionId, gradingResultFromApi(result)])),
  };
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
    mastery: null,
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
    artifactVersion: artifact?.version,
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

async function mindMapWithLearning(artifact: BackendArtifact | null, subjectId: string, retry = true): Promise<MindMapData> {
  if (!artifact?.id) return mindMapFromArtifact(null);
  if (artifact.subject_id !== subjectId || artifact.artifact_type !== 'mind_map') throw new ApiError('导图不属于当前科目。', 404);
  const overlay = await apiV1<{ artifactVersion: number; nodes: Record<string, import('../types').MindMapLearning> }>(`/artifacts/${encodeURIComponent(artifact.id)}/learning`);
  if (overlay.artifactVersion !== artifact.version) {
    if (retry) return mindMapWithLearning(await apiV1<BackendArtifact>(`/artifacts/${encodeURIComponent(artifact.id)}`), subjectId, false);
    throw new ApiError('导图已变化，请刷新后重试。', 409);
  }
  const map = mindMapFromArtifact(artifact);
  return { ...map, nodes: map.nodes.map(node => ({ ...node, learning: overlay.nodes[node.id], mastery: overlay.nodes[node.id]?.masteryScore ?? null })) };
}

export const api = {
  workspaceVersion: resourceVersion,
  dailyPreview: (subjectId:string) => apiV1<import('../types/dailyReview').DailyReport>(`/daily-reviews/preview?subject_id=${encodeURIComponent(subjectId)}`),
  dailyHistory: (subjectId:string,before?:string,beforeId?:string) => apiV1<import('../types/dailyReview').DailyReview[]>(`/daily-reviews?${new URLSearchParams({subject_id:subjectId,...(before?{before}:{}),...(beforeId?{before_id:beforeId}:{})})}`),
  dailyReview: (id:string) => apiV1<import('../types/dailyReview').DailyReview>(`/daily-reviews/${encodeURIComponent(id)}`),
  createDailyReview: (subjectId:string,requestId:string) => apiV1<import('../types/dailyReview').DailyReview>('/daily-reviews',{method:'POST',body:JSON.stringify({subjectId,requestId})}),
  decideDailyReview: (id:string,version:number,approve:boolean) => apiV1<import('../types/dailyReview').DailyReview>(`/daily-reviews/${encodeURIComponent(id)}/decision`,{method:'POST',body:JSON.stringify({version,approve})}),
  dailySchedule: (subjectId:string) => apiV1<import('../types/dailyReview').DailySchedule>(`/daily-reviews/schedule?subject_id=${encodeURIComponent(subjectId)}`),
  retryLearningJob: (id:string) => apiV1(`/learning-jobs/${encodeURIComponent(id)}/retry`,{method:'POST'}),
  saveDailySchedule: (subjectId:string,payload:{enabled:boolean;hour:number;version:number}) => apiV1(`/daily-reviews/schedule?subject_id=${encodeURIComponent(subjectId)}`,{method:'PUT',body:JSON.stringify(payload)}),
  lectureCapabilities: () => apiV1<import('../types/lecture').LectureCapabilities>('/lectures/capabilities'),
  lectures: (subjectId:string) => apiV1<import('../types/lecture').Lecture[]>(`/lectures?subject_id=${encodeURIComponent(subjectId)}`),
  lectureAudioMaterials: (subjectId:string) => apiV1<Array<{id:string;filename:string;status:string}>>(`/lectures/audio-materials?subject_id=${encodeURIComponent(subjectId)}`),
  attachLecture: (subjectId:string,materialId:string,title:string,sourceKind:'recording'|'upload') => apiV1<import('../types/lecture').Lecture>('/lectures',{method:'POST',body:JSON.stringify({subject_id:subjectId,material_id:materialId,title,source_kind:sourceKind})}),
  lecture: (id:string,subjectId:string) => apiV1<import('../types/lecture').LectureDetail>(`/lectures/${encodeURIComponent(id)}?subject_id=${encodeURIComponent(subjectId)}`),
  lectureTranscript: (id:string,offset=0,blockId?:string) => apiV1<import('../types/lecture').TranscriptPage>(`/lectures/${encodeURIComponent(id)}/transcript?${new URLSearchParams({offset:String(offset),limit:'50',...(blockId?{block_id:blockId}:{})})}`),
  alignLectureTopic: (id:string,blockId:string,topicId:string|null,version:number) => apiV1<import('../types/lecture').Lecture>(`/lectures/${encodeURIComponent(id)}/blocks/${encodeURIComponent(blockId)}/topic`,{method:'PUT',body:JSON.stringify({topic_id:topicId,version})}),
  materialSource: (id:string) => apiV1<{url:string;expiresIn:number}>(`/materials/${encodeURIComponent(id)}/source`),
  retryLectureTask: (id:string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(id)}/retry`,{method:'POST'}),
  calendar: (start:string,end:string,subjectId?:string) => apiV1<import('../types/calendar').CalendarData>(`/calendar?${new URLSearchParams({ start,end,...(subjectId ? {subject_id:subjectId}:{}) })}`),
  saveAvailability: (day:string,minutes:number,version:number) => apiV1(`/calendar/availability/${encodeURIComponent(day)}`,{method:'PUT',body:JSON.stringify({minutes,version})}),
  moveCalendarTask: (id:string,day:string,version:number) => apiV1(`/calendar/tasks/${encodeURIComponent(id)}/move`,{method:'POST',body:JSON.stringify({day,version})}),
  proposeCalendarExams: (subjectId:string,materialId:string) => apiV1<{proposals:import('../types/calendar').ExamProposal[];truncated:boolean;warnings:string[]}>(`/calendar/exam-proposals`,{method:'POST',body:JSON.stringify({subject_id:subjectId,material_id:materialId})}),
  confirmCalendarExam: (id:string,values:Record<string,unknown>) => apiV1<{id:string}>(`/calendar/exam-proposals/${encodeURIComponent(id)}/confirm`,{method:'POST',body:JSON.stringify(values)}),
  notes: (subjectId: string) => apiV1<import('../types').NoteArtifact[]>(`/notes?subject_id=${encodeURIComponent(subjectId)}`),
  generateNote: (payload: { subjectId: string; mode: import('../types').NoteMode; scope?: string; materialIds?: string[]; knowledgePointId?: string }) => apiV1<import('../types').NoteArtifact>('/notes', { method: 'POST', body: JSON.stringify(payload) }, 240_000),
  updateNote: (id: string, payload: { version: number; title: string; content: import('../types').NoteArtifact['content'] }) => apiV1<import('../types').NoteArtifact>(`/notes/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  note: (id: string) => apiV1<import('../types').NoteArtifact>(`/notes/${id}`),
  noteVersions: (id: string) => apiV1<Array<Pick<import('../types').NoteVersion, 'version' | 'created_at'>>>(`/notes/${id}/versions`),
  noteVersion: (id: string, version: number) => apiV1<import('../types').NoteVersion>(`/notes/${id}/versions/${version}`),
  restoreNote: (id: string, version: number, targetVersion: number) => apiV1<import('../types').NoteArtifact>(`/notes/${id}/restore`, { method: 'POST', body: JSON.stringify({ version, targetVersion }) }),
  rewriteNote: (id: string, payload: Omit<import('../types').NoteRewrite, 'replacement' | 'citationIds'> & { instruction: string }) => apiV1<import('../types').NoteRewrite>(`/notes/${id}/rewrite`, { method: 'POST', body: JSON.stringify(payload) }, 120_000),
  convertNote: (id: string, version: number, target: 'flashcards' | 'mind_map' | 'quiz') => apiV1<{ target: string; result: { id: string; title?: string }; sourceArtifactId: string; sourceArtifactVersion: number }>(`/notes/${id}/convert`, { method: 'POST', body: JSON.stringify({ version, target, count: 10 }) }, 240_000),
  exportNote: async (id: string) => {
    const response = await authenticatedFetch(`/artifacts/${id}/export?format=markdown`);
    if (!response.ok) throw new ApiError('笔记导出失败，请重试。', response.status);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = `notes-${id}.md`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  nextActions: () => apiV1<import('../types').RecommendationData>('/recommendations/next-actions?audit=true'),
  qualityMetrics: (days: number) => apiV1<import('./learningMetrics').QualityMetrics>(`/recommendations/quality-metrics?days=${days}`),
  learningOutcomes: (days: number) => apiV1<import('./learningMetrics').LearningOutcomes>(`/recommendations/learning-outcomes?days=${days}`),
  predictionCoverage: (days: number) => apiV1<import('./learningMetrics').PredictionCoverage>(`/recommendations/prediction-coverage?days=${days}`),
  recommendationHistory: (cursor?: string) => apiV1<import('./learningMetrics').HistoryPage>(`/recommendations/history?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  recommendationAudit: (id: string, cursor?: string) => apiV1<import('./learningMetrics').AuditPage>(`/recommendations/${encodeURIComponent(id)}/audit?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  recommendationFeedback: (id: string, event: 'impression' | 'clicked') => apiV1<{ recorded: boolean }>(`/recommendations/${id}/feedback`, { method: 'POST', keepalive: true, body: JSON.stringify({ event }) }, 5000),
  examGoals: (subjectId: string) => apiV1<import('../types').ExamGoals>(`/courses/${encodeURIComponent(subjectId)}/exam-goals`),
  saveExamEvent: (subjectId: string, values: Record<string, unknown>, eventId?: string) => apiV1(`/courses/${encodeURIComponent(subjectId)}/exam-events${eventId ? `/${encodeURIComponent(eventId)}` : ''}`, { method: eventId ? 'PUT' : 'POST', body: JSON.stringify(values) }),
  createSyllabus: (subjectId: string, values: Record<string, unknown>) => apiV1(`/courses/${encodeURIComponent(subjectId)}/syllabi`, { method: 'POST', body: JSON.stringify(values) }),
  courseStructure: (subjectId: string) => apiV1<import('../types').CourseStructure>(`/courses/${encodeURIComponent(subjectId)}/structure`),
  learnerState: (subjectId: string) => apiV1<import('../types').LearnerState>(`/courses/${encodeURIComponent(subjectId)}/learner-state`),
  coverTopic: (subjectId: string, topicId: string) => apiV1(`/courses/${encodeURIComponent(subjectId)}/topics/${encodeURIComponent(topicId)}/covered`, { method: 'POST' }),
  createUnit: (subjectId: string, title: string) => apiV1(`/courses/${encodeURIComponent(subjectId)}/units`, { method: 'POST', body: JSON.stringify({ title }) }),
  createTopic: (subjectId: string, title: string, unitId: string | null) => apiV1(`/courses/${encodeURIComponent(subjectId)}/topics`, { method: 'POST', body: JSON.stringify({ title, unit_id: unitId }) }),
  updateTopic: (subjectId: string, topicId: string, values: Record<string, unknown>) => apiV1(`/courses/${encodeURIComponent(subjectId)}/topics/${encodeURIComponent(topicId)}`, { method: 'PATCH', body: JSON.stringify(values) }),
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
  materialProcessing: (subjectId: string) => apiV1<MaterialProcessing[]>(`/materials/processing?subject_id=${encodeURIComponent(subjectId)}`),
  retryUploadNotes: (subjectId: string, materialId: string) => apiV1<{conversionId: string | null}>(`/materials/${encodeURIComponent(materialId)}/notes/retry?subject_id=${encodeURIComponent(subjectId)}`, { method: 'POST' }),
  materialOutline: (subjectId: string, materialId: string) => apiV1<import('../types/materialOutline').MaterialOutline | null>(`/materials/${encodeURIComponent(materialId)}/outline?subject_id=${encodeURIComponent(subjectId)}`),
  prepareMaterialOutline: (subjectId: string, materialId: string) => apiV1<import('../types/materialOutline').MaterialOutline>(`/materials/${encodeURIComponent(materialId)}/outline?subject_id=${encodeURIComponent(subjectId)}`, { method: 'POST' }),
  decideMaterialTopic: (id: string, version: number, action: 'accept' | 'reject', title?: string) => apiV1<import('../types/materialOutline').TopicProposal>(`/materials/topic-proposals/${encodeURIComponent(id)}/decision`, { method: 'POST', body: JSON.stringify({ version, action, title }) }),
  retryMaterialTask: (id: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  addMaterial: async (subjectId: string, file: File, materialPurpose: MaterialPurpose = 'learning', notesMode?: import('../types').UploadNotesMode) => {
    const form = new FormData();
    form.append('subject_id', subjectId);
    form.append('file', file);
    form.append('materialPurpose', materialPurpose);
    if (notesMode) form.append('notesMode', notesMode);
    const result = await apiV1<{ material: BackendMaterial; task: ProcessingTask | null; deduplicated: boolean }>('/materials/uploads', { method: 'POST', body: form });
    return { material: materialFromApi(result.material), task: result.task, deduplicated: result.deduplicated };
  },
  task: (taskId: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(taskId)}`),
  tasks: (subjectId: string, activeOnly = false) => apiV1<ProcessingTask[]>(`/tasks?subject_id=${encodeURIComponent(subjectId)}&active_only=${activeOnly}`),

  chatHistory: (subjectId: string) => cached<ChatMessage[]>('chat', subjectId, () => apiV1(`/chat/history/${encodeURIComponent(subjectId)}`)),
  chat: async (payload: { subject_id: string; content: string; session_id: string; role: TutorRole; interaction_id?: string | null; knowledge_policy?: KnowledgePolicy; dialogue_act_override?: DialogueAct; conversion_id?: string }) => {
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
        conversionId: payload.conversion_id,
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

  conversionCapabilities: () => apiV1<Record<import('../types/conversion').ConversionSource['kind'], import('../types/conversion').ConversionTarget[]>>('/conversions/capabilities'),
  convert: (payload: import('../types/conversion').ConversionInput) => apiV1<import('../types/conversion').Conversion>('/conversions', { method: 'POST', body: JSON.stringify(payload) }),
  conversions: (subjectId: string, objectId?: string) => apiV1<import('../types/conversion').Conversion[]>(`/conversions?${new URLSearchParams({ subject_id: subjectId, ...(objectId ? { object_id: objectId } : {}) })}`),
  conversionTutorContext: (id: string, subjectId: string) => apiV1<import('../types/conversion').TutorContext>(`/conversions/${encodeURIComponent(id)}/tutor-context?subject_id=${encodeURIComponent(subjectId)}`),
  conversionWrongAnswers: (subjectId: string) => apiV1<Array<{ id: string; title: string }>>(`/conversions/wrong-answers?subject_id=${encodeURIComponent(subjectId)}`),
  cancelConversion: (id: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  retryConversion: (id: string) => apiV1<ProcessingTask>(`/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  mindMap: async (subjectId: string, artifactId?: string) => {
    if (artifactId) {
      const artifact = await apiV1<BackendArtifact>(`/artifacts/${encodeURIComponent(artifactId)}`);
      if (artifact.subject_id !== subjectId || artifact.artifact_type !== 'mind_map') throw new ApiError('导图不属于当前科目，请切换到生成时的科目。', 404);
      return mindMapWithLearning(artifact, subjectId);
    }
    const artifacts = await apiV1<BackendArtifact[]>(`/artifacts?subject_id=${encodeURIComponent(subjectId)}&artifact_type=mind_map`);
    return mindMapWithLearning(artifacts[0] ?? null, subjectId);
  },
  bindMindMapTopic: (artifactId: string, nodeId: string, topicId: string | null, artifactVersion: number, bindingVersion: number) => apiV1(`/artifacts/${encodeURIComponent(artifactId)}/nodes/${encodeURIComponent(nodeId)}/topic`, { method: 'PUT', body: JSON.stringify({ topicId, artifactVersion, bindingVersion }) }),
  generateMindMap: async (payload: MindMapGenerateInput) => mindMapWithLearning(await apiV1<BackendArtifact>('/artifacts/mind-maps', {
    method: 'POST',
    body: JSON.stringify({ ...payload, maxDepth: payload.maxDepth ?? 3, includeMastery: payload.includeMastery ?? true, count: 24 }),
  }, 120_000), payload.subjectId),
  generateFlashcards: (subjectId: string, scope: string) => apiV1<BackendArtifact>('/artifacts/flashcards', {
    method: 'POST', body: JSON.stringify({ subjectId, scope, mode: 'knowledge', count: 10 }),
  }, 120_000),

  exams: (subjectId: string) => cached<Exam[]>('exams', subjectId, async () => (await apiV1<BackendExam[]>(`/exams?subject_id=${encodeURIComponent(subjectId)}`)).map(examFromApi)),
  queueExamGeneration: (payload: ExamGenerateInput) => apiV1<ProcessingTask>('/exams/generations', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  exam: async (examId: string) => examDetailFromApi(await apiV1<BackendExam>(`/exams/${encodeURIComponent(examId)}`)),
  startExamAttempt: async (examId: string) => attemptFromApi(await apiV1<BackendAttempt>('/exam-attempts', {
    method: 'POST', body: JSON.stringify({ examId }),
  })),
  examAttempt: async (attemptId: string) => attemptFromApi(await apiV1<BackendAttempt>(`/exam-attempts/${encodeURIComponent(attemptId)}`)),
  saveExamResponse: (attemptId: string, questionId: string, response: unknown, learnerConfidence?: number | null, responseSeconds?: number) => apiV1(`/exam-attempts/${encodeURIComponent(attemptId)}/responses`, {
    method: 'PATCH', body: JSON.stringify({ questionId, response, learnerConfidence, responseSeconds }),
  }),
  confirmExamResponse: async (attemptId: string, questionId: string, response: unknown, learnerConfidence?: number | null, responseSeconds?: number) => gradingResultFromApi(await apiV1<Record<string, unknown>>(`/exam-attempts/${encodeURIComponent(attemptId)}/questions/${encodeURIComponent(questionId)}/confirm`, {
    method: 'POST', body: JSON.stringify({ response, learnerConfidence, responseSeconds }),
  }, 90_000)),
  resumeQuiz: async (attemptId: string, remediationNote: string) => attemptFromApi(await apiV1<BackendAttempt>(`/exam-attempts/${encodeURIComponent(attemptId)}/resume-quiz`, { method: 'POST', body: JSON.stringify({ remediationNote }) })),
  studySessions: (subjectId: string) => apiV1<Array<{ id: string; goal: string; status: string }>>(`/study-sessions?subject_id=${encodeURIComponent(subjectId)}`),
  studySession: (id: string) => apiV1<import('../types').StudySession>(`/study-sessions/${encodeURIComponent(id)}`),
  createStudySession: (subjectId: string, knowledgePointId: string, minutes: number, requestId: string, examEventId?: string, recommendationId?: string) => apiV1<import('../types').StudySession>('/study-sessions', { method: 'POST', body: JSON.stringify({ subjectId, knowledgePointId, minutes, requestId, examEventId, recommendationId }) }),
  sessionAction: (id: string, version: number, action: string, values: Record<string, unknown> = {}) => apiV1<import('../types').StudySession>(`/study-sessions/${encodeURIComponent(id)}/actions`, { method: 'POST', body: JSON.stringify({ version, action, ...values }) }, 180_000),
  sessionMessage: (id: string, message: string) => apiV1<{ answer: string }>(`/study-sessions/${encodeURIComponent(id)}/messages`, { method: 'POST', body: JSON.stringify({ message }) }, 120_000),
  sessionQuizAttempt: async (id: string) => attemptFromApi(await apiV1<BackendAttempt>(`/study-sessions/${encodeURIComponent(id)}/quiz-attempt`, { method: 'POST' })),
  flashcardQueue: (subjectId?: string, artifactId?: string, includeFuture = false) => apiV1<import('../types').FlashcardQueue>(`/flashcards/queue?${new URLSearchParams({ ...(subjectId ? { subject_id: subjectId } : {}), ...(artifactId ? { artifact_id: artifactId } : {}), include_future: String(includeFuture), limit: artifactId ? '200' : '50' })}`),
  flashcardHistory: (artifactId: string, cardId: string) => apiV1<import('../types').FlashcardReviewLog[]>(`/flashcards/${encodeURIComponent(artifactId)}/cards/${encodeURIComponent(cardId)}/history`),
  reviewFlashcard: (artifactId: string, cardId: string, rating: string, requestId?: string, version?: number) => apiV1<{ state: import('../types').FlashcardState; reviewId: string }>(`/artifacts/${encodeURIComponent(artifactId)}/flashcards/reviews`, { method: 'POST', body: JSON.stringify({ cardId, rating, requestId, version }) }),
  submitExamAttempt: async (attemptId: string): Promise<ExamAttemptSummary> => {
    const result = await apiV1<{ attemptId: string; score: number; maxScore: number; results: Array<Record<string, unknown>> }>(`/exam-attempts/${encodeURIComponent(attemptId)}/submit`, { method: 'POST' }, 120_000);
    return { ...result, results: result.results.map(gradingResultFromApi) };
  },

  plan: async (subjectId?: string) => {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    const overview = await apiV1<Omit<StudyPlanOverview, 'tasks'> & { tasks: BackendTask[] }>(`/study-plans/overview${query}`);
    return { ...overview, tasks: overview.tasks.map(taskFromApi) };
  },
  previewPlan: (input: StudyPlanInput) => apiV1<StudyPlanPreview>('/study-plans/preview', { method: 'POST', body: JSON.stringify(input) }),
  generatePlan: (input: StudyPlanInput) => apiV1<ProcessingTask>('/study-plans/generations', { method: 'POST', body: JSON.stringify(input) }),
  planGeneration: (id: string) => apiV1<ProcessingTask>(`/study-plans/generations/${encodeURIComponent(id)}`),
  updateTask: async (taskId: string, completed: boolean) => taskFromApi(await apiV1<BackendTask>(`/study-plans/tasks/${encodeURIComponent(taskId)}`, { method: 'PATCH', body: JSON.stringify({ status: completed ? 'completed' : 'pending' }) })),
  lockTask: async (taskId: string, locked: boolean) => taskFromApi(await apiV1<BackendTask>(`/study-plans/tasks/${encodeURIComponent(taskId)}`, { method: 'PATCH', body: JSON.stringify({ locked }) })),
  replan: (planId: string) => apiV1(`/study-plans/${encodeURIComponent(planId)}/replan`, { method: 'POST' }),
  planEvents: (planId: string) => apiV1<Array<{ id: string; reason: string; event_type: string; created_at: string }>>(`/study-plans/${encodeURIComponent(planId)}/events`),

  streamDayendRun,
  dayendRun: (threadId: string) => apiV3<{ threadId: string; status: string; state?: Record<string, unknown>; next?: string[] }>(`/runs/${encodeURIComponent(threadId)}`),
  resumeDayendRun: (threadId: string, response: Record<string, unknown>) => apiV3<{ threadId: string; state: Record<string, unknown> }>(`/runs/${encodeURIComponent(threadId)}/resume`, { method: 'POST', body: JSON.stringify({ response }) }),

  saveWorkspaceState: (data: unknown) => saveCache('workspace', data),
};
