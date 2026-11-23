import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { useAuth } from '../../auth/AuthProvider';
import { api } from '../../api/client';
import { appendUnique, assessedMastery, decimal, percent, points, requestEpoch, type AuditPage, type HistoryPage,
  type LearningOutcomes, type PredictionCoverage, type QualityMetrics } from '../../api/learningMetrics';

const button = 'min-h-11 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-wait disabled:opacity-50';
const cell = 'border-b border-slate-200 px-3 py-3 text-left align-top';
const kinds: Record<string, string> = { guided_session: '引导学习', plan_task: '计划任务', due_flashcard: '到期闪卡安排', quiz_remediation: '引导测验补救' };
const eventNames: Record<string, string> = { 'recommendation.impression': '建议进入可见区域', 'recommendation.clicked': '点击开始',
  'session.accepted': '确认学习计划', 'session.completed': '完成学习会话', 'step.completed': '完成学习步骤' };
const signalNames: Record<string, string> = { mastery: '掌握度', confidence: '证据置信度', attemptCount: '练习次数', correctCount: '正确次数',
  importance: '课程重要度', lastReviewedAt: '上次复习', confidenceMismatch: '答题自信偏差', assessmentCount: '评估证据数',
  misconceptionRisk: '误解风险', dueReview: '复习已到期', examEventId: '关联考试', examUrgency: '考试紧迫度',
  flashcardRecallRisk: '闪卡回忆风险', covered: '已经学习', activeTopicCount: '启用知识点数' };
const time = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '时间未记录' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(parsed);
};
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '读取失败，请重试。';

function DataTable({ label, headings, children }: { label: string; headings: string[]; children: ReactNode }) {
  return <div className="mt-4 overflow-x-auto focus-visible:outline-2 focus-visible:outline-blue-600" tabIndex={0} role="region" aria-label={label}>
    <table className="w-full text-sm tabular-nums"><caption className="sr-only">{label}</caption><thead><tr>{headings.map(heading => <th key={heading} scope="col" className={`${cell} whitespace-nowrap bg-slate-100 font-semibold`}>{heading}</th>)}</tr></thead><tbody>{children}</tbody></table>
  </div>;
}
function Notice({ loading, error, retry }: { loading: boolean; error?: string; retry: () => void }) {
  if (loading) return <p role="status" className="mt-4 text-sm text-slate-600">正在读取学习记录…</p>;
  if (error) return <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 text-sm text-rose-800"><span>读取失败：{error}</span><button type="button" className={button} onClick={retry}>重新读取</button></div>;
  return null;
}
function Values({ values, labels = {} }: { values?: Record<string, unknown>; labels?: Record<string, string> }) {
  const entries = Object.entries(values ?? {});
  if (!entries.length) return <p className="mt-2 text-sm text-slate-600">该记录没有保存这些信息。</p>;
  return <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[minmax(8rem,1fr)_3fr]">{entries.map(([key, value]) => <div key={key} className="contents"><dt className="break-words text-slate-600">{labels[key] ?? key}</dt><dd className="break-all">{value == null ? '未记录' : typeof value === 'boolean' ? value ? '是' : '否' : typeof value === 'number' ? Number.isInteger(value) ? String(value) : value.toFixed(4) : typeof value === 'string' ? value : JSON.stringify(value)}</dd></div>)}</dl>;
}

export default function LearningMetrics() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const selected = params.get('recommendationId');
  const [days, setDays] = useState(30);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [outcomes, setOutcomes] = useState<LearningOutcomes | null>(null);
  const [quality, setQuality] = useState<QualityMetrics | null>(null);
  const [coverage, setCoverage] = useState<PredictionCoverage | null>(null);
  const [history, setHistory] = useState<HistoryPage | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const [detail, setDetail] = useState<AuditPage | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const historyEpoch = useRef(requestEpoch());
  const detailEpoch = useRef(requestEpoch());
  const historyPending = useRef(false);
  const detailPending = useRef(false);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const historyHeading = useRef<HTMLHeadingElement>(null);
  const historyButtons = useRef(new Map<string, HTMLButtonElement>());
  const previousSelection = useRef(selected);
  const focusDetail = useRef(false);
  const refresh = () => setRevision(value => value+1);

  useEffect(() => {
    let active = true;
    setLoading(true); setErrors({}); setOutcomes(null); setQuality(null); setCoverage(null);
    void Promise.allSettled([api.learningOutcomes(days), api.qualityMetrics(days), api.predictionCoverage(days)]).then(results => {
      if (!active) return;
      const nextErrors: Record<string, string> = {};
      if (results[0].status === 'fulfilled') setOutcomes(results[0].value); else nextErrors.outcomes = errorText(results[0].reason);
      if (results[1].status === 'fulfilled') setQuality(results[1].value); else nextErrors.quality = errorText(results[1].reason);
      if (results[2].status === 'fulfilled') setCoverage(results[2].value); else nextErrors.coverage = errorText(results[2].reason);
      setErrors(nextErrors); setLoading(false);
    });
    return () => { active = false; };
  }, [user?.id, days, revision]);

  useEffect(() => {
    const epoch = historyEpoch.current.reset();
    setHistory(null); setHistoryError(''); setHistoryLoading(true); historyPending.current = true;
    void api.recommendationHistory().then(page => {
      if (historyEpoch.current.accepts(epoch)) setHistory(page);
    }).catch(reason => { if (historyEpoch.current.accepts(epoch)) setHistoryError(errorText(reason)); })
      .finally(() => { if (historyEpoch.current.accepts(epoch)) { setHistoryLoading(false); historyPending.current = false; } });
    return () => { historyEpoch.current.reset(); };
  }, [user?.id, revision]);

  useEffect(() => {
    const epoch = detailEpoch.current.reset();
    setDetail(null); setDetailError(''); setDetailLoading(!!selected); detailPending.current = !!selected;
    if (selected) void api.recommendationAudit(selected).then(page => {
      if (detailEpoch.current.accepts(epoch)) setDetail(page);
    }).catch(reason => { if (detailEpoch.current.accepts(epoch)) setDetailError(errorText(reason)); })
      .finally(() => { if (detailEpoch.current.accepts(epoch)) { setDetailLoading(false); detailPending.current = false; } });
    return () => { detailEpoch.current.reset(); };
  }, [user?.id, selected, revision]);
  useEffect(() => {
    if (detail && focusDetail.current) { detailHeading.current?.focus(); focusDetail.current = false; }
  }, [detail]);
  useEffect(() => {
    const previous = previousSelection.current;
    previousSelection.current = selected;
    if (!selected && previous) {
      const origin = historyButtons.current.get(previous);
      if (origin?.isConnected) origin.focus();
      else historyHeading.current?.focus();
    }
  }, [selected]);

  async function moreHistory() {
    if (!history?.nextCursor || historyPending.current) return;
    const epoch = historyEpoch.current.current();
    historyPending.current = true; setHistoryLoading(true); setHistoryError('');
    try {
      const page = await api.recommendationHistory(history.nextCursor);
      if (historyEpoch.current.accepts(epoch)) setHistory(previous => ({ ...page, items: appendUnique(previous?.items ?? [], page.items) }));
    } catch (reason) { if (historyEpoch.current.accepts(epoch)) setHistoryError(errorText(reason)); }
    finally { if (historyEpoch.current.accepts(epoch)) { historyPending.current = false; setHistoryLoading(false); } }
  }
  async function moreEvents() {
    if (!selected || !detail?.nextCursor || detailPending.current) return;
    const epoch = detailEpoch.current.current();
    detailPending.current = true; setDetailLoading(true); setDetailError('');
    try {
      const page = await api.recommendationAudit(selected, detail.nextCursor);
      if (detailEpoch.current.accepts(epoch)) setDetail(previous => ({ ...page, events: appendUnique(previous?.events ?? [], page.events) }));
    } catch (reason) { if (detailEpoch.current.accepts(epoch)) setDetailError(errorText(reason)); }
    finally { if (detailEpoch.current.accepts(epoch)) { detailPending.current = false; setDetailLoading(false); } }
  }

  return <div className="h-full overflow-y-auto p-6 md:p-8"><div className="mx-auto max-w-6xl space-y-10">
    <header><div className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-3xl font-bold tracking-tight">学习记录</h1><p className="mt-2 max-w-prose text-sm leading-6 text-slate-600">查看学习安排的完成情况、掌握度估计和推荐依据。这里汇总当前账户全部科目。</p></div><div className="flex flex-wrap items-end gap-3"><label className="text-sm font-medium">统计窗口<select value={days} onChange={event => setDays(Number(event.target.value))} className="ml-3 min-h-11 rounded-lg border border-slate-300 bg-white px-3 focus:outline-2 focus:outline-blue-600"><option value={7}>近 7 天</option><option value={30}>近 30 天</option><option value={90}>近 90 天</option></select></label><button type="button" className={`${button} inline-flex items-center gap-2`} disabled={loading} onClick={refresh}><RefreshCw size={16} aria-hidden="true"/>刷新记录</button></div></div>
      <nav aria-label="本页内容" className="mt-5 flex flex-wrap gap-x-5 gap-y-3 text-sm font-medium text-blue-700">{[['completion', '完成情况'], ['calibration', '掌握度与覆盖率'], ['recommendation', '推荐采纳'], ['history', '推荐历史']].map(([id, text]) => <a key={id} href={`#${id}`} className="underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-blue-600">{text}</a>)}</nav>
    </header>

    <section id="completion" aria-labelledby="completion-title"><h2 id="completion-title" className="text-xl font-bold">安排完成了吗</h2><p className="mt-2 max-w-prose text-sm leading-6 text-slate-600">每项安排固定观察 7 天，只用观察期已结束的记录计算完成率。观察中的记录会单列，迟完成不计入按时完成。</p><Notice loading={loading} error={errors.outcomes} retry={refresh}/>
      {outcomes && <>{outcomes.cohorts.length ? <DataTable label="各类安排的完成情况" headings={['安排 / 规则版本', '已开始', '观察期结束', '观察中', '按时完成', '迟完成', '完成率']}>{outcomes.cohorts.map(row => <tr key={`${row.kind}:${row.algorithmVersion}`}><th scope="row" className={cell}>{kinds[row.kind] ?? row.kind}<span className="mt-1 block max-w-72 break-all text-xs font-normal text-slate-600">{row.algorithmVersion}</span></th>{[row.total, row.mature, row.pending, row.completedWithinHorizon, row.late, percent(row.completionRate)].map((value, index) => <td key={index} className={cell}>{value}</td>)}</tr>)}</DataTable> :
        <p className="mt-4 text-sm text-slate-600">还没有进入统计窗口的安排。新记录会在确认学习、创建任务或安排闪卡复习后出现。</p>}<details className="mt-4 text-sm"><summary className="min-h-11 cursor-pointer rounded-sm py-2 font-medium text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">这些数字如何计算</summary><p className="mt-2 max-w-prose leading-6 text-slate-600">计划按每条任务统计；闪卡评价表示完成复习操作，选“忘记”也会计入。测验补救只统计引导学习中首次未达 80% 后，后续测验达标的会话。重排或删除任务会保留原承诺的分母。历史记录未回填，未来安排还未进入统计。</p></details><p className="mt-3 text-xs text-slate-600">统计截至 {time(outcomes.asOf)}（上海时间）</p></>}
    </section>

    <section id="calibration" aria-labelledby="calibration-title"><h2 id="calibration-title" className="text-xl font-bold">掌握度估计有多少依据</h2><Notice loading={loading} error={errors.coverage} retry={refresh}/>
      {coverage && <><p className="mt-3 text-sm leading-6">已发布 {coverage.releasedGrades} 条评分，其中 {coverage.knownOutcomes} 条有明确正确性；{coverage.predictionSamples} 条保存了首次作答时的掌握度，预测覆盖率为 <strong>{percent(coverage.coverageRate)}</strong>。</p><p className="mt-2 max-w-prose text-sm leading-6 text-slate-600">缺少预测 {coverage.missingPrediction} 条（无作答记录 {coverage.noResponse}、无首次快照 {coverage.noSnapshot}）；正确性未定 {coverage.unknownOutcomes} 条，不进入覆盖率分母。只统计本功能启用后发布的评分，历史校准样本可能更多。</p></>}
      <Notice loading={false} error={errors.outcomes} retry={refresh}/>
      {outcomes && <><p className="mt-4 max-w-prose text-sm leading-6 text-slate-600">下面比较首次作答时的掌握度分数与后来发布的答题结果。Brier 和 ECE 越小，表示本组样本中偏差越小；分数还不是经过验证的概率，不同版本的人群也可能不同。</p>{outcomes.masteryCalibration.length ? <DataTable label="掌握度校准与分桶" headings={['规则版本', '样本数', 'Brier', 'ECE', '分桶明细']}>{outcomes.masteryCalibration.map(row => <tr key={row.algorithmVersion}><th scope="row" className={`${cell} max-w-72 break-all font-medium`}>{row.algorithmVersion}</th><td className={cell}>{row.sampleCount}</td><td className={cell}>{decimal(row.brierScore)}</td><td className={cell}>{decimal(row.expectedCalibrationError)}</td><td className={`${cell} min-w-64`}><details><summary className="min-h-11 cursor-pointer rounded-sm py-2 font-medium text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">查看分桶</summary><ul className="mt-2 space-y-2">{row.bins.map(bin => <li key={bin.lower}>{percent(bin.lower)}–{percent(bin.upper)}：{bin.sampleCount} 条，均分 {percent(bin.meanPrediction)} / 正确率 {percent(bin.accuracy)}</li>)}</ul></details></td></tr>)}</DataTable> :
        <p className="mt-4 text-sm text-slate-600">还没有同时具备首次预测和已发布结果的校准样本。</p>}</>}
    </section>

    <section id="recommendation" aria-labelledby="recommendation-title"><h2 id="recommendation-title" className="text-xl font-bold">建议是否被采用</h2><p className="mt-2 max-w-prose text-sm leading-6 text-slate-600">曝光与点击由页面尽力记录，可能漏报。点击率只统计已曝光且点击的推荐，点击总数还可能包含曝光漏报的记录。确认引导学习计划才算采纳；完成率的分母是已曝光且已采纳的推荐。</p><Notice loading={loading} error={errors.quality} retry={refresh}/>
      {quality && <>{quality.recommendationCohorts.length ? <DataTable label="推荐投递与采纳" headings={['推荐规则', '生成', '曝光', '点击', '点击率', '采纳', '采纳率', '完成', '完成率']}>{quality.recommendationCohorts.map(row => <tr key={row.algorithmVersion}><th scope="row" className={`${cell} max-w-72 break-all font-medium`}>{row.algorithmVersion}</th>{[row.delivered, row.impressions, row.clicks, percent(row.clickThroughRate), row.accepted, percent(row.acceptanceRate), row.completed, percent(row.completionRate)].map((value, index) => <td key={index} className={cell}>{value}</td>)}</tr>)}</DataTable> :
        <p className="mt-4 text-sm text-slate-600">本窗口还没有保存的推荐投递记录。</p>}<div className="mt-5 space-y-2 text-sm leading-6"><p>完成会话的平均掌握度变化：<strong>{points(quality.sessionMasteryGain.meanDeltaPoints)}</strong>，可比较样本 {quality.sessionMasteryGain.sampleCount} 个。</p><p>答题自信与正确性的 Brier：<strong>{decimal(quality.learnerConfidenceCalibration.brierScore)}</strong>，样本 {quality.learnerConfidenceCalibration.sampleCount} 条。</p><p className="max-w-prose text-slate-600">缺少前后评估证据的会话不纳入掌握度变化；前后变化不能证明推荐的因果效果。“—”表示没有分母或可比较样本。</p></div></>}
    </section>

    <section id="history" aria-labelledby="history-title"><h2 id="history-title" ref={historyHeading} tabIndex={-1} className="text-xl font-bold focus:outline-2 focus:outline-offset-4 focus:outline-blue-600">当时为什么这样建议</h2><p className="mt-2 text-sm leading-6 text-slate-600">按生成记录回看当时的理由与后续行动。历史不受上方统计窗口筛选。</p><Notice loading={historyLoading && !history} error={historyError} retry={refresh}/>
      {history && <>{history.items.length ? <DataTable label="推荐历史" headings={['生成时间（上海）', '建议 / 科目', '查看']} >{history.items.map(row => <tr key={row.id} className={selected === row.id ? 'bg-blue-50 text-blue-950' : ''}><td className={`${cell} whitespace-nowrap`}>{time(row.created_at)}</td><th scope="row" className={`${cell} break-words font-medium`}>{row.snapshot.title}<span className="mt-1 block text-xs font-normal">{row.snapshot.subjectName}</span></th><td className={cell}><button ref={element => { if (element) historyButtons.current.set(row.id, element); else historyButtons.current.delete(row.id); }} type="button" className={button} aria-expanded={selected === row.id} aria-controls="recommendation-detail" onClick={() => { if (selected === row.id) detailHeading.current?.focus(); else { focusDetail.current = true; setParams({ recommendationId: row.id }); } }}>查看<span className="sr-only">{row.snapshot.title}的依据</span></button></td></tr>)}</DataTable> :
        <p className="mt-4 text-sm text-slate-600">暂无推荐历史。返回仪表盘读取建议后，这里会保存当时的依据。</p>}{history.hasMore && <button type="button" className={`${button} mt-4`} disabled={historyLoading} onClick={() => void moreHistory()}>{historyLoading ? '正在加载…' : '加载更早的推荐'}</button>}</>}
    </section>

    <section hidden={!selected} id="recommendation-detail" aria-labelledby="detail-title" className="border-t border-slate-300 pt-6"><h2 id="detail-title" ref={detailHeading} tabIndex={-1} className="text-xl font-bold focus:outline-2 focus:outline-offset-4 focus:outline-blue-600">推荐依据与后续行动</h2><Notice loading={detailLoading && !detail} error={detailError} retry={refresh}/>
      <button type="button" className={`${button} mt-3`} onClick={() => setParams({})}>关闭详情</button>
      {detail && detail.recommendation.id === selected && <><h3 className="mt-4 text-lg font-semibold">{detail.recommendation.snapshot.title}</h3><p className="mt-1 text-sm text-slate-600">{detail.recommendation.snapshot.subjectName} · {time(detail.recommendation.created_at)}</p><ul className="mt-4 list-disc space-y-2 pl-5 text-sm">{detail.recommendation.snapshot.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul><p className="mt-3 text-sm">当时的优先级分数：{decimal(detail.recommendation.snapshot.priorityScore)}</p><details className="mt-4 text-sm"><summary className="min-h-11 cursor-pointer rounded-sm py-2 font-medium text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">查看计算时的信号与规则</summary><h4 className="mt-4 font-semibold">输入信号</h4><Values values={detail.recommendation.snapshot.inputSignals} labels={signalNames}/><h4 className="mt-4 font-semibold">分项</h4><Values values={detail.recommendation.snapshot.scoreComponents}/><h4 className="mt-4 font-semibold">规则版本</h4><Values values={detail.recommendation.snapshot.algorithmVersions}/></details>
        <h3 className="mt-6 font-semibold">最近行动</h3>{detail.events.length ? <ol className="mt-3 divide-y divide-slate-200">{detail.events.map(event => <li key={event.id} className="py-3 text-sm"><p className="font-medium">{eventNames[event.event_type] ?? event.event_type}</p><time dateTime={event.created_at} className="mt-1 block text-xs text-slate-600">{time(event.created_at)}</time>{event.event_type === 'session.completed' && <p className="mt-2">会话前后掌握度：{percent(assessedMastery(event.payload.before))} → {percent(assessedMastery(event.payload.after))}</p>}</li>)}</ol> :
        <p className="mt-3 text-sm text-slate-600">尚未收到关联行动记录；这不表示用户没有看到或学习。</p>}{detail.hasMore && <button type="button" className={`${button} mt-4`} disabled={detailLoading} onClick={() => void moreEvents()}>{detailLoading ? '正在加载…' : '加载更早的行动'}</button>}</>}
    </section>
  </div></div>;
}
