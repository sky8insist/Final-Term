import type { ChangeEvent } from "react";
import { useState } from "react";
import { validateFile } from "../utils/file";

type FileUploaderProps = {
  disabled?: boolean;
  onSelect: (file: File) => void | Promise<void>;
};

export function FileUploader({ disabled = false, onSelect }: FileUploaderProps) {
  const [error, setError] = useState<string | null>(null);

  async function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const validation = validateFile(file);
    if (!validation.valid) {
      setError(validation.reason ?? "Invalid file");
      event.target.value = "";
      return;
    }

    setError(null);
    await onSelect(file);
    event.target.value = "";
  }

  return (
    <div>
      <input
        type="file"
        accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        disabled={disabled}
        onChange={(event) => void handleChange(event)}
      />
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}
