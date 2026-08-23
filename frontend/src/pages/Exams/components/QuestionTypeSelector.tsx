import type { PracticeQuestionType } from '../../../types';

export type QuestionTypeCounts = Record<PracticeQuestionType, number>;

const options: Array<{ type: PracticeQuestionType; label: string; description: string }> = [
  { type: 'single_choice', label: '单项选择题', description: '从多个选项中选择一个正确答案' },
  { type: 'multiple_choice', label: '多项选择题', description: '选择两个或以上正确答案' },
  { type: 'true_false', label: '判断题', description: '判断课程结论是否正确' },
  { type: 'fill_blank', label: '填空题', description: '填写关键概念或术语' },
  { type: 'short_answer', label: '问答题', description: '用自己的语言解释概念或关系，由评分量规判定' },
];

type Props = { value: QuestionTypeCounts; disabled: boolean; onChange: (value: QuestionTypeCounts) => void };

export function QuestionTypeSelector({ value, disabled, onChange }: Props) {
  return <fieldset disabled={disabled}>
    <legend className="mb-3 text-sm font-semibold text-slate-800">选择题型</legend>
    <div className="grid gap-3 sm:grid-cols-2">
      {options.map((option) => {
        const enabled = value[option.type] > 0;
        const checkboxId = `question-type-${option.type}`;
        const countId = `question-count-${option.type}`;
        return <div key={option.type} className={`rounded-xl border p-4 transition ${enabled ? 'border-blue-300 bg-blue-50/60' : 'border-slate-200 bg-white'}`}>
          <div className="flex items-start gap-3">
            <input
              id={checkboxId}
              type="checkbox" checked={enabled}
              onChange={(event) => onChange({ ...value, [option.type]: event.target.checked ? 1 : 0 })}
              aria-describedby={`${checkboxId}-description`}
              className="mt-1 h-4 w-4 accent-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            />
            <div className="min-w-0 flex-1"><label htmlFor={checkboxId} className="text-sm font-semibold text-slate-900">{option.label}</label><p id={`${checkboxId}-description`} className="mt-1 text-xs leading-5 text-slate-600">{option.description}</p></div>
            <label htmlFor={countId} className="text-xs text-slate-600">数量<input id={countId} aria-label={`${option.label}数量，0 表示不生成`} type="number" min={0} max={20} value={value[option.type]} onChange={(event) => onChange({ ...value, [option.type]: Math.min(Math.max(Number(event.target.value) || 0, 0), 20) })} className="mt-1 block w-16 rounded-lg border bg-white px-2 py-1.5 text-center text-base font-semibold text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500" /></label>
          </div>
        </div>;
      })}
    </div>
  </fieldset>;
}
