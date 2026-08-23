export type Subject = { id: string; name: string; description: string; progress: number; mastery: number; examDate?: string | null; externalKnowledgeEnabled?: boolean };
export type Material = { id: string; subjectId: string; name: string; type: string; status: 'queued' | 'parsing' | 'embedding' | 'indexing' | 'indexed' | 'failed'; size: number; uploadedAt: string; errorMessage?: string | null };
export type ProcessingTask = { id: string; subjectId?: string; materialId?: string | null; taskType?: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; stage: string; progress: number; errorCode?: string | null; errorMessage?: string | null; metadata?: Record<string, unknown> };
export type Citation = { id: string; sourceName: string; pageNumber?: number; text: string; sourceType?: 'material' | 'external' };
export type AnswerGeneration = { provider: string; model: string; mocked: boolean; grounded: boolean; citationCount: number; retrievalSources: string[]; externalUsed?: boolean; evidenceAssessment?: { sufficient: boolean; relevance: number; coverage: number; reason: string } };
export type TutorRole = 'beginner' | 'crash_course' | 'socratic' | 'examiner';
export type KnowledgePolicy = 'course_only' | 'course_first' | 'expanded';
export type DialogueAct = 'answer_to_pending_question' | 'followup_question_same_topic' | 'new_question' | 'request_hint' | 'request_full_solution' | 'confirmation' | 'challenge_or_correction' | 'clarification' | 'meta_command' | 'ambiguous';
export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  citations?: Citation[];
  generation?: AnswerGeneration;
  tutorRole?: { id: string; name: string };
  memoryQueued?: boolean;
  dialogue?: { dialogueAct: DialogueAct; confidence: number; reasonCode?: string };
  interaction?: { id?: string | null; status: string; expectsReply: boolean } | null;
};
export type StudyPhase = { id: string; name: string; goal: string; startDate: string; endDate: string };
export type StudyTaskLink = { type: string; href: string; label: string };
export type StudyTask = {
  id: string; subjectId: string; title: string; time: string; completed: boolean;
  scheduledDate?: string; estimatedMinutes?: number; priority?: number; knowledgeKey?: string;
  taskType?: string; source?: 'system' | 'user'; status?: string;
  metadata?: {
    phaseId?: string; method?: string; reason?: string; successCriteria?: string;
    sourceSignals?: string[]; recommendedQuestionTypes?: string[]; recommendedQuestionCount?: number;
    resourceLinks?: StudyTaskLink[]; masteryAtCreation?: number | null; recentAccuracy?: number | null;
    spacingOccurrence?: number; needScore?: number;
  };
};
export type StudyPlan = {
  id: string; title: string; exam_date?: string; examDate?: string; daily_minutes?: number; dailyMinutes?: number;
  strategy?: { phases?: StudyPhase[]; warnings?: string[]; signalStats?: Record<string, number>; dataSufficient?: boolean; dailyUsage?: Record<string, number> };
};
export type StudyPlanOverview = { plans: StudyPlan[]; activePlan: StudyPlan | null; tasks: StudyTask[]; summary: { total: number; completed: number; completionRate: number; overdue: number; scheduledMinutes: number } };
export type StudyPlanInput = { subjectId: string; examDate: string; dailyMinutes: number; weekendExtra: boolean; reserveFinalDay: boolean; preserveExisting?: boolean; title?: string };
export type StudyPlanPreview = { targetDate: string; daysRemaining: number; dataSufficient: boolean; signalStats: Record<string, number>; estimatedKnowledgePoints: number; estimatedMinutes: number; availableMinutes: number; timeSufficient: boolean; warnings: string[]; phases: StudyPhase[] };
export type DashboardData = { subjects: Subject[]; todayTasks: StudyTask[]; stats: { studyMinutes: number; completedTasks: number; streakDays: number } };
export type MindMapMode = 'question' | 'topic' | 'chapter';
export type MindMapNodeType = 'root' | 'concept' | 'definition' | 'comparison' | 'process' | 'example' | 'exam_point' | 'warning';
export type MindMapNode = {
  id: string; parentId: string | null; label: string; type: MindMapNodeType; level: number;
  importance: number; examImportance: 'high' | 'medium' | 'low'; mastery: number | null;
  description: string; sourceIds: string[]; order: number;
};
export type MindMapEdge = { source: string; target: string; relation: string };
export type MindMapEvaluation = { relevance: number; coverage: number; hierarchy: number; grounding: number; redundancy: number };
export type MindMapSource = { id: string; sourceName: string; pageNumber?: number; text: string };
export type MindMapData = {
  artifactId?: string; title: string; focusQuestion: string; summary: string; mode: MindMapMode;
  evidenceInsufficient: boolean; nodes: MindMapNode[]; edges: MindMapEdge[];
  evaluation?: MindMapEvaluation; sources: MindMapSource[];
};
export type MindMapGenerateInput = {
  subjectId: string; mode: MindMapMode; query?: string; topicId?: string; chapterId?: string;
  maxDepth?: number; includeMastery?: boolean;
};
export type ExamQuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'fill_blank' | 'short_answer' | 'calculation' | 'essay';
export type PracticeQuestionType = Extract<ExamQuestionType, 'single_choice' | 'multiple_choice' | 'true_false' | 'fill_blank' | 'short_answer'>;
export type ExamQuestion = { id: string; questionType: ExamQuestionType; stem: string; options: string[]; knowledgeKey: string; difficulty: string; points: number; sequenceIndex: number };
export type Exam = { id: string; title: string; score?: number | null; questionCount: number; questionTypes?: ExamQuestionType[]; createdAt?: string; difficulty?: string; status?: string };
export type ExamEvidence = { id: string; sourceType: 'material' | 'external'; sourceName?: string; pageNumber?: number; url?: string; relevanceScore?: number; importanceScore?: number };
export type ExamGeneration = {
  knowledgePolicy: KnowledgePolicy;
  retrieval: { courseEvidenceCount?: number; externalEvidenceCount?: number; externalAttempted?: boolean; externalUsed?: boolean; warnings?: string[] };
  evidence: ExamEvidence[];
};
export type ExamDetail = Exam & { durationMinutes: number; totalPoints: number; questions: ExamQuestion[]; generation?: ExamGeneration | null };
export type QuestionGradingResult = {
  questionId: string; earnedPoints: number; maxPoints: number; isCorrect: boolean; feedback: string;
  earnedCriteria: string[]; missingCriteria: string[]; errorType?: string | null;
  correctAnswer: unknown; explanation: string; citations: string[];
};
export type ExamAttempt = {
  id: string; examId: string; status: 'in_progress' | 'submitted' | 'graded' | 'expired';
  startedAt: string; expiresAt: string; score?: number | null; maxScore?: number | null;
  exam: ExamDetail; responses: Record<string, unknown>; results: Record<string, QuestionGradingResult>;
};
export type ExamAttemptSummary = { attemptId: string; score: number; maxScore: number; results: QuestionGradingResult[] };
export type ExamGenerateInput = {
  subjectId: string; title: string; durationMinutes: number; difficulty: string;
  assessmentType: 'practice' | 'stage' | 'mock'; scope?: string; knowledgePolicy?: KnowledgePolicy;
  questionTypes: Array<{ questionType: PracticeQuestionType; count: number; pointsEach: number }>;
};
