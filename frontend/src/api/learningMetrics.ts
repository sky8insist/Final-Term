export type RecommendationAudit = {
  id: string; created_at: string; algorithm_version: string;
  snapshot: { title: string; subjectName: string; reasons: string[]; priorityScore?: number;
    inputSignals?: Record<string, unknown>; scoreComponents?: Record<string, unknown>; algorithmVersions?: Record<string, string> };
};
export type AuditEvent = { id: string; created_at: string; event_type: string; algorithm_version: string; payload: Record<string, unknown> };
export type HistoryPage = { items: RecommendationAudit[]; hasMore: boolean; nextCursor: string | null };
export type AuditPage = { recommendation: RecommendationAudit; events: AuditEvent[]; hasMore: boolean; nextCursor: string | null };
export type QualityMetrics = {
  since: string; asOf: string;
  recommendationCohorts: Array<{ algorithmVersion: string; delivered: number; impressions: number; clicks: number; exposedClicks: number;
    accepted: number; completed: number; clickThroughRate: number | null; acceptanceRate: number | null; completionRate: number | null }>;
  sessionMasteryGain: { sampleCount: number; meanDeltaPoints: number | null };
  learnerConfidenceCalibration: { sampleCount: number; brierScore: number | null };
};
export type LearningOutcomes = {
  asOf: string; windowDays: number; horizonDays: number;
  cohorts: Array<{ kind: string; algorithmVersion: string; total: number; mature: number; pending: number; late: number; completedWithinHorizon: number; completionRate: number | null }>;
  masteryCalibration: Array<{ algorithmVersion: string; sampleCount: number; brierScore: number; expectedCalibrationError: number;
    bins: Array<{ lower: number; upper: number; sampleCount: number; meanPrediction: number; accuracy: number }> }>;
};
export type PredictionCoverage = {
  asOf: string; windowDays: number; releasedGrades: number; knownOutcomes: number; predictionSamples: number;
  missingPrediction: number; unknownOutcomes: number; noResponse: number; noSnapshot: number; coverageRate: number | null;
};

export function percent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${(value*100).toFixed(1)}%`;
}
export function decimal(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(3);
}
export function points(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)} 个百分点`;
}
export function assessedMastery(value: unknown): number | null {
  if (!value || typeof value !== 'object') return null;
  const state = value as { assessmentCount?: number; masteryScore?: number };
  return typeof state.assessmentCount === 'number' && state.assessmentCount > 0 && typeof state.masteryScore === 'number' && Number.isFinite(state.masteryScore) ? state.masteryScore : null;
}
export function appendUnique<T extends { id: string }>(current: T[], incoming: T[]): T[] {
  const seen = new Set(current.map(row=>row.id));
  return [...current, ...incoming.filter(row=>{if(seen.has(row.id))return false;seen.add(row.id);return true;})];
}
/** A reset invalidates every older in-flight page, including its finally handler. */
export function requestEpoch() {
  let revision = 0;
  return { reset: () => ++revision, current: () => revision, accepts: (value: number) => value === revision };
}
