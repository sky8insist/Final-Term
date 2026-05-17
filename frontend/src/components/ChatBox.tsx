import type { FormEvent } from "react";

type ChatBoxProps = {
  onSubmit: (question: string) => void;
  disabled?: boolean;
};

export function ChatBox({ onSubmit, disabled = false }: ChatBoxProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const question = String(formData.get("question") ?? "").trim();

    if (question) {
      onSubmit(question);
      event.currentTarget.reset();
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <textarea name="question" placeholder="Ask about your materials" />
      <button type="submit" disabled={disabled}>
        Send
      </button>
    </form>
  );
}
