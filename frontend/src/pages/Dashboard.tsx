import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { createSubject, deleteSubject, listSubjects } from "../api/subject";
import { SubjectCard } from "../components/SubjectCard";
import type { Subject } from "../types/subject";

export function Dashboard() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadSubjects() {
    setIsLoading(true);
    setError(null);

    try {
      const items = await listSubjects();
      setSubjects(items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load subjects");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadSubjects();
  }, []);

  async function handleCreateSubject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);

    const form = event.currentTarget;
    const formData = new FormData(form);
    const name = String(formData.get("name") ?? "");
    const description = String(formData.get("description") ?? "");

    try {
      const subject = await createSubject({ name, description });
      setSubjects((current) => [subject, ...current]);
      form.reset();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Failed to create subject");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleDeleteSubject(subjectId: string) {
    setIsLoading(true);
    setError(null);

    try {
      await deleteSubject(subjectId);
      setSubjects((current) => current.filter((subject) => subject.id !== subjectId));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete subject");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <h1>Subjects</h1>
      <form onSubmit={handleCreateSubject}>
        <label>
          Name
          <input name="name" type="text" maxLength={120} required />
        </label>
        <label>
          Description
          <textarea name="description" maxLength={1000} />
        </label>
        <button type="submit" disabled={isLoading}>
          Create subject
        </button>
      </form>
      {error ? <p role="alert">{error}</p> : null}
      {isLoading ? <p>Loading...</p> : null}
      <section>
        {!isLoading && subjects.length === 0 ? (
          <p>Create a subject to start reviewing.</p>
        ) : (
          subjects.map((subject) => (
            <div key={subject.id}>
              <SubjectCard subject={subject} />
              <button
                type="button"
                onClick={() => void handleDeleteSubject(subject.id)}
                disabled={isLoading}
              >
                Delete
              </button>
            </div>
          ))
        )}
      </section>
    </main>
  );
}
