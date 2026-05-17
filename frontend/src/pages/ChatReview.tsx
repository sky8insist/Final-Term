import { useEffect, useMemo, useState } from "react";

import { askQuestion, listChatHistory } from "../api/chat";
import { getReviewProgress } from "../api/review";
import { listSubjects } from "../api/subject";
import { AnswerCard } from "../components/AnswerCard";
import { ChatBox } from "../components/ChatBox";
import { ProgressBar } from "../components/ProgressBar";
import type { ChatMessage } from "../types/chat";
import type { ReviewProgress } from "../types/review";
import type { Subject } from "../types/subject";

export function ChatReview() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState("");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [isLoadingSubjects, setIsLoadingSubjects] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSubject = useMemo(
    () => subjects.find((subject) => subject.id === selectedSubjectId),
    [selectedSubjectId, subjects],
  );

  useEffect(() => {
    async function loadSubjects() {
      setIsLoadingSubjects(true);
      setError(null);
      try {
        const items = await listSubjects();
        setSubjects(items);
        setSelectedSubjectId((current) => current || items[0]?.id || "");
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load subjects");
      } finally {
        setIsLoadingSubjects(false);
      }
    }

    void loadSubjects();
  }, []);

  useEffect(() => {
    if (!selectedSubjectId) {
      setHistory([]);
      setProgress(null);
      return;
    }

    async function loadSession() {
      setIsLoadingSession(true);
      setError(null);
      try {
        const [messages, reviewProgress] = await Promise.all([
          listChatHistory(selectedSubjectId),
          getReviewProgress(selectedSubjectId),
        ]);
        setHistory(messages);
        setProgress(reviewProgress);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load chat history");
      } finally {
        setIsLoadingSession(false);
      }
    }

    void loadSession();
  }, [selectedSubjectId]);

  async function refreshSession() {
    if (!selectedSubjectId) {
      return;
    }
    const [messages, reviewProgress] = await Promise.all([
      listChatHistory(selectedSubjectId),
      getReviewProgress(selectedSubjectId),
    ]);
    setHistory(messages);
    setProgress(reviewProgress);
  }

  async function handleAsk(question: string) {
    if (!selectedSubjectId) {
      setError("Create a subject before asking about materials");
      return;
    }

    setIsAsking(true);
    setError(null);

    try {
      await askQuestion({
        subjectId: selectedSubjectId,
        question,
      });
      await refreshSession();
    } catch (askError) {
      setError(askError instanceof Error ? askError.message : "Failed to generate answer");
    } finally {
      setIsAsking(false);
    }
  }

  const progressMax = progress?.totalCount || 1;
  const progressValue = progress?.masteredCount || 0;

  return (
    <main>
      <h1>Material Q&A</h1>
      <label>
        Subject
        <select
          value={selectedSubjectId}
          disabled={isLoadingSubjects || isAsking || subjects.length === 0}
          onChange={(event) => setSelectedSubjectId(event.target.value)}
        >
          {subjects.length === 0 ? <option value="">No subjects yet</option> : null}
          {subjects.map((subject) => (
            <option key={subject.id} value={subject.id}>
              {subject.name}
            </option>
          ))}
        </select>
      </label>

      {selectedSubject ? <p>Current subject: {selectedSubject.name}</p> : null}
      {progress ? (
        <ProgressBar
          value={progressValue}
          max={progressMax}
          label={`Review progress ${progress.masteredCount}/${progress.totalCount}`}
        />
      ) : null}

      <ChatBox onSubmit={(question) => void handleAsk(question)} disabled={isAsking} />
      {isLoadingSession ? <p>Loading chat history...</p> : null}
      {isAsking ? <p>Generating answer...</p> : null}
      {error ? <p role="alert">{error}</p> : null}

      <section>
        <h2>Chat history</h2>
        {history.length === 0 ? (
          <p>No questions yet.</p>
        ) : (
          history.map((message) => (
            <article key={message.id}>
              <h3>{message.role === "user" ? "You" : "Assistant"}</h3>
              {message.role === "assistant" ? (
                <AnswerCard answer={message.content} citations={message.citations ?? []} />
              ) : (
                <p>{message.content}</p>
              )}
            </article>
          ))
        )}
      </section>
    </main>
  );
}
