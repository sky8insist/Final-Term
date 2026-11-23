import type { ProcessingTask } from './index';
export type Lecture = { id:string;subject_id:string;material_id:string;title:string;source_kind:'recording'|'upload';version:number;created_at:string };
export type LectureDetail = Lecture & {status:string;error?:string;task:ProcessingTask|null;segments:Array<{segment_index:number;start_time:number;end_time:number;status:string;attempts:number}>};
export type TranscriptBlock = {id:string;content_text:string;start_time:number|null;end_time:number|null;confidence:number|null;knowledge_point_id:string|null;topic_title:string|null;timestamp_precision:string|null};
export type TranscriptPage = {version:number;total:number;offset:number;blocks:TranscriptBlock[]};
export type LectureCapabilities = {maxRecordingSeconds:number;maxUploadBytes:number;canProcessAudio:boolean;mocked:boolean};
