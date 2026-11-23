import type { NoteMode, ProcessingTask } from './index';

export type ConversionSource = { kind: 'material' | 'notes' | 'mind_map_node' | 'wrong_answer'; id: string; version?: number; nodeId?: string; blockIds?:string[] };
export type ConversionTarget = 'notes' | 'flashcards' | 'mind_map' | 'quiz' | 'tutor';
export type ConversionInput = { requestId: string; subjectId: string; source: ConversionSource; target: ConversionTarget; count: number; mode: NoteMode };
export type Conversion = { id: string; subject_id: string; source_kind: ConversionSource['kind']; source_title: string; source_href?: string; source_version?: number; source_node_id?: string; target: ConversionTarget; result_href?: string; warnings?: string[]; task: ProcessingTask };
export type TutorContext = { title: string; content: Record<string, unknown>; source: ConversionSource; topicIds: string[]; citations: Array<{ id: string; sourceName: string; chunkText: string; pageNumber?: number }> };
export const targetNames: Record<ConversionTarget, string> = { notes: '学习笔记', flashcards: '闪卡', mind_map: '思维导图', quiz: '练习测验', tutor: 'Tutor 讲解' };
