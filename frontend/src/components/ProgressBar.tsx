type ProgressBarProps = {
  value: number;
  max: number;
  label?: string;
};

export function ProgressBar({ value, max, label }: ProgressBarProps) {
  const safeMax = Math.max(max, 1);
  const percent = Math.round((value / safeMax) * 100);

  return (
    <label>
      {label}
      <progress value={value} max={safeMax} />
      <span>{percent}%</span>
    </label>
  );
}
