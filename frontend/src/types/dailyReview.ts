export type DailyReport = {
  version: string; day: string; timezone: string;
  todaySummary: { completedTasks: Array<{id:string;title:string;minutes:number}>; submittedTodayGradedAttempts:number; learningEvents:Record<string,number> };
  masteryChanges: Array<{topicId:string;title:string;before:number|null;after:number;deltaPoints:number|null;evidenceId:string}>;
  unresolvedProblems: Array<{id:string;title:string;masteryScore:number|null;state:string}>;
  tomorrowTasks: Array<{id:string;title:string;minutes:number;status:string;locked:boolean}>;
  tomorrowExams: Array<{id:string;title:string;date:string}>;
  proposedMoves: Array<{taskId:string;planId:string;title:string;minutes:number;from:string;reason:string}>;
  tomorrowRecommendations: Array<{topicId:string;title:string;reason:string;href:string}>;
  requiresConfirmation:boolean;
  feasibility:{capacityMinutes:number|null;existingMinutes:number;proposedMinutes:number;withinBudget:boolean|null;warnings:string[]};
};
export type DailyReview = {id:string;subject_id:string;day:string;report:DailyReport;status:'pending'|'applied'|'rejected';version:number;created_at:string};
export type DailySchedule = {enabled:boolean;hour:number;version:number;timezone:string;latestJob:{id:string;day:string;status:string;attempts:number;error_code:string|null;result_id:string|null}|null};
