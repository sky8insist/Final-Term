import { ProgressBar } from "../components/ProgressBar";

export function SubjectDetail() {
  return (
    <main>
      <h1>Subject Detail</h1>
      <ProgressBar value={0} max={100} label="Review progress" />
    </main>
  );
}
