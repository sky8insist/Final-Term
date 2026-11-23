export type Subject = { id: string; name: string; description: string; progress: number; mastery: number; examDate?: string | null; externalKnowledgeEnabled?: boolean };
export type MaterialPurpose = 'learning' | 'syllabus' | 'reference';
export type Material = { id: string; subjectId: string; name: string; type: string; status: 'queued' | 'parsing' | 'embedding' | 'indexing' | 'indexed' | 'failed'; size: number; uploadedAt: string; errorMessage?: string | null; materialPurpose?: MaterialPurpose };
export type UploadNotesMode = 'summary' | 'standard' | 'comprehensive' | 'exam_focus';
export type UploadNotesStatus = { mode: UploadNotesMode; conversionId: string | null; href: string | null; status: string; error: string | null; warnings: string[]; canRetry: boolean; attempts: number };
export type MaterialProcessing = { materialId: string; task: ProcessingTask | null; sourceAvailable: boolean; notes?: UploadNotesStatus | null };
export type ProcessingTask = { id: string; subjectId?: string; materialId?: string | null; taskType?: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'; stage: string; progress: number; attempts: number; maxAttempts: number; errorCode?: string | null; errorMessage?: string | null; metadata?: Record<string, unknown> };
type Citation = { id: string; sourceName: string; pageNumber?: number; text: string; sourceType?: 'material' | 'external' };
type AnswerGeneration = { provider: string; model: string; mocked: boolean; grounded: boolean; citationCount: number; retrievalSources: string[]; externalUsed?: boolean; evidenceAssessment?: { sufficient: boolean; relevance: number; coverage: number; reason: string } };
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
type StudyTaskLink = { type: string; href: string; label: string };
export type StudyTask = {
  id: string; subjectId: string; title: string; time: string; completed: boolean;
  scheduledDate?: string; estimatedMinutes?: number; priority?: number; knowledgeKey?: string;
  taskType?: string; source?: 'system' | 'user'; status?: string;
  locked?: boolean;
  metadata?: {
    phaseId?: string; method?: string; reason?: string; successCriteria?: string;
    sourceSignals?: string[]; recommendedQuestionTypes?: string[]; recommendedQuestionCount?: number;
    resourceLinks?: StudyTaskLink[]; masteryAtCreation?: number | null; recentAccuracy?: number | null;
    spacingOccurrence?: number; needScore?: number;
  };
};
type StudyPlan = {
  version?: number; mode?: 'CRAM' | 'STANDARD' | 'COMPREHENSIVE'; replan_required?: boolean; replan_reason?: string;
  id: string; title: string; exam_date?: string; examDate?: string; daily_minutes?: number; dailyMinutes?: number;
  strategy?: { mode?: string; autoReplan?: boolean; availableMinutes?: Record<string, number>; phases?: StudyPhase[]; warnings?: string[]; signalStats?: Record<string, number>; dataSufficient?: boolean; dailyUsage?: Record<string, number> };
};
export type StudyPlanOverview = { plans: StudyPlan[]; activePlan: StudyPlan | null; tasks: StudyTask[]; summary: { total: number; completed: number; completionRate: number; overdue: number; scheduledMinutes: number } };
export type StudyPlanInput = { subjectId: string; examDate?: string; examEventId?: string; mode?: 'CRAM' | 'STANDARD' | 'COMPREHENSIVE'; availableMinutes?: Record<string, number>; autoReplan?: boolean; dailyMinutes: number; weekendExtra: boolean; reserveFinalDay: boolean; preserveExisting?: boolean; title?: string };
export type StudyPlanPreview = { targetDate: string; daysRemaining: number; dataSufficient: boolean; signalStats: Record<string, number>; estimatedKnowledgePoints: number; estimatedMinutes: number; availableMinutes: number; timeSufficient: boolean; warnings: string[]; phases: StudyPhase[] };
export type DashboardData = { subjects: Subject[]; todayTasks: StudyTask[]; stats: { studyMinutes: number; completedTasks: number; streakDays: number } };
export type MindMapMode = 'question' | 'topic' | 'chapter';
export type MindMapLearning = {
  bindingVersion: number; knowledgePointId: string | null; topicTitle: string | null; stale: boolean;
  state: TopicLearningState['state'] | 'unbound'; masteryScore: number | null; masteryConfidence: number | null;
  learnerConfidence: number | null; lastReviewAt: string | null; nextReviewAt: string | null;
  misconceptionRisk: number; dueCards: number; reasons: string[];
  exams: Array<{ id: string; title: string; date: string; weight: number }>;
};
type MindMapNodeType = 'root' | 'concept' | 'definition' | 'comparison' | 'process' | 'example' | 'exam_point' | 'warning';
export type MindMapNode = {
  id: string; parentId: string | null; label: string; type: MindMapNodeType; level: number;
  importance: number; examImportance: 'high' | 'medium' | 'low'; mastery: number | null;
  description: string; sourceIds: string[]; order: number; learning?: MindMapLearning;
};
type MindMapEdge = { source: string; target: string; relation: string };
type MindMapEvaluation = { relevance: number; coverage: number; hierarchy: number; grounding: number; redundancy: number };
type MindMapSource = { id: string; sourceName: string; pageNumber?: number; text: string };
export type MindMapData = {
  artifactId?: string; artifactVersion?: number; title: string; focusQuestion: string; summary: string; mode: MindMapMode;
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
type ExamEvidence = { id: string; sourceType: 'material' | 'external'; sourceName?: string; pageNumber?: number; url?: string; relevanceScore?: number; importanceScore?: number };
export type ExamGeneration = {
  knowledgePolicy: KnowledgePolicy;
  retrieval: { courseEvidenceCount?: number; externalEvidenceCount?: number; externalAttempted?: boolean; externalUsed?: boolean; warnings?: string[] };
  evidence: ExamEvidence[];
};
export type ExamDetail = Exam & { assessmentMode: 'formal' | 'adaptive'; durationMinutes: number; totalPoints: number; questions: ExamQuestion[]; generation?: ExamGeneration | null };
export type QuestionGradingResult = {
  questionId: string; earnedPoints: number; maxPoints: number; isCorrect: boolean; feedback: string;
  earnedCriteria: string[]; missingCriteria: string[]; errorType?: string | null;
  correctAnswer: unknown; explanation: string; citations: string[];
  learnerConfidence?: number | null; confidenceMismatch?: number | null;
};
export type ExamAttempt = {
  id: string; examId: string; status: 'in_progress' | 'submitted' | 'graded' | 'expired';
  startedAt: string; expiresAt: string; score?: number | null; maxScore?: number | null;
  exam: ExamDetail; responses: Record<string, unknown>; results: Record<string, QuestionGradingResult>;
  learnerConfidences: Record<string, number | null>;
  adaptiveState: { paused?: boolean; reason?: string; resumeCount?: number };
};
export type ExamAttemptSummary = { attemptId: string; score: number; maxScore: number; results: QuestionGradingResult[] };
export type ExamGenerateInput = {
  assessmentMode?: 'formal' | 'adaptive';
  subjectId: string; title: string; durationMinutes: number; difficulty: string;
  assessmentType: 'practice' | 'stage' | 'mock'; scope?: string; knowledgePolicy?: KnowledgePolicy;
  questionTypes: Array<{ questionType: PracticeQuestionType; count: number; pointsEach: number }>;
};
export type CourseUnit = { id: string; title: string; sequence_index: number };
export type StudySessionStep = {
  id: string; kind: 'notes' | 'socratic' | 'flashcards' | 'quiz' | 'mastery_check' | 'remediation';
  title: string; estimated_minutes: number; status: 'pending' | 'running' | 'ready' | 'completed' | 'skipped';
  output: { answer?: string; id?: string; taskId?: string; attemptId?: string;
    citations?: Array<{ sourceName?: string; page?: number; pageNumber?: number }>;
    content?: { cards?: Array<{ id: string; front: string; back: string }> };
    learnerState?: TopicLearningState; interaction?: { id: string; status: string }; reviewedCardIds?: string[] };
};
export type StudySession = {
  id: string; subject_id: string; goal: string; status: 'planned' | 'active' | 'completed' | 'cancelled';
  version: number; current_step: number; minutes: number; steps: StudySessionStep[];
  summary?: { before?: TopicLearningState; after?: TopicLearningState; extraMinutes?: number; skippedSteps?: number;
    nextActions?: Array<{ id: string; title: string; href: string }> };
};
export type CourseTopic = { id: string; title: string; knowledge_key: string; unit_id: string | null; sequence_index: number; syllabus_weight: number; archived: boolean };
export type CourseStructure = { units: CourseUnit[]; topics: CourseTopic[] };
export type TopicLearningState = { knowledgePointId: string; state: 'not_started' | 'covered' | 'practicing' | 'mastered' | 'at_risk'; masteryScore: number; masteryConfidence: number; learnerConfidence: number | null; assessmentCount: number; reasons: string[] };
export type LearnerState = { stateVersion: string; topics: TopicLearningState[]; counts: Record<TopicLearningState['state'], number> };
export type ExamEvent = { id: string; title: string; exam_date: string; syllabus_id: string | null; status: 'active' | 'completed' | 'archived' };
export type ExamGoals = { exam_events: ExamEvent[]; exam_topic_map: Array<{ exam_event_id: string; knowledge_point_id: string; weight: number }>; syllabi: Array<{ id: string; title: string }>; syllabus_topics: Array<{ syllabus_id: string; knowledge_point_id: string }> };
export type RecommendationData = { algorithmVersion: string; coldStart: boolean; dueReviewCount: number;
  actions: Array<{ id: string; recommendationId?: string; subjectId: string; subjectName: string; title: string; estimatedMinutes: number; reasons: string[]; coldStart: boolean; href: string }>;
  upcomingExams: Array<{ id: string; title: string; subjectId: string; subjectName: string; examDate: string }>;
  weakTopics: Array<{ knowledgePointId: string; subjectId: string; title: string; masteryScore: number }>;
  todayTasks: Array<{ id: string; subjectId: string; title: string; estimatedMinutes: number }>;
};
export type FlashcardState = {
  version: number; content_version: number; review_count: number; lapse_count: number;
  difficulty: number; stability: number; last_review: string | null; next_review: string;
};
export type ScheduledFlashcard = {
  artifact_id: string; card_id: string; subject_id: string; front: string; back: string;
  state: FlashcardState; overdue: boolean;
};
export type FlashcardQueue = {
  cards: ScheduledFlashcard[]; asOf: string; hasMore: boolean; dueCount: number; totalCount: number;
  subjects: Array<{ subject_id: string; subject_name: string; due: number; overdue: number; total: number; next_review: string }>;
};
export type FlashcardReviewLog = {
  id: string; rating: string; reviewed_at: string; state_after: FlashcardState; content_version: number;
};
export type NoteMode = 'summary' | 'standard' | 'comprehensive' | 'exam_focus';
export type NoteSection = { id: string; title: string; body: string; citationIds: string[] };
export type NoteCitation = { id: string; materialId: string; filename: string; chunkText: string; pageNumber: number | null; startTime: number | null; endTime: number | null };
export type NoteArtifact = {
  id: string; subject_id: string; artifact_type: 'notes'; title: string;
  content: { sections: NoteSection[] }; citations: NoteCitation[];
  generation_params: { mode: NoteMode; knowledgePointIds?: string[]; restoredFromVersion?: number };
  version: number; is_user_edited: boolean; updated_at: string;
};
export type NoteVersion = { version: number; created_at: string; snapshot: NoteArtifact };
export type NoteRewrite = { version: number; sectionId: string; selectionStart: number; selectionEnd: number; selectedText: string; replacement: string; citationIds: string[] };
