import { useEffect, useState } from "react";

import { listMaterials, uploadMaterial } from "../api/material";
import { listSubjects } from "../api/subject";
import { FileUploader } from "../components/FileUploader";
import type { Material } from "../types/material";
import type { Subject } from "../types/subject";

export function UploadMaterial() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState("");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadSubjects() {
    setIsLoading(true);
    setError(null);

    try {
      const items = await listSubjects();
      setSubjects(items);
      setSelectedSubjectId((current) => current || items[0]?.id || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load subjects");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadMaterials(subjectId: string) {
    if (!subjectId) {
      setMaterials([]);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const items = await listMaterials(subjectId);
      setMaterials(items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load materials");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadSubjects();
  }, []);

  useEffect(() => {
    void loadMaterials(selectedSubjectId);
  }, [selectedSubjectId]);

  async function handleUpload(file: File) {
    if (!selectedSubjectId) {
      setError("Create a subject before uploading materials");
      return;
    }

    setIsUploading(true);
    setError(null);

    try {
      const result = await uploadMaterial(selectedSubjectId, file);
      setMaterials((current) => [result.material, ...current]);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Failed to upload material");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <main>
      <h1>Upload Material</h1>
      <label>
        Subject
        <select
          value={selectedSubjectId}
          disabled={isLoading || subjects.length === 0}
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
      <FileUploader disabled={isUploading || !selectedSubjectId} onSelect={handleUpload} />
      {isUploading ? <p>Processing material...</p> : null}
      {isLoading ? <p>Loading materials...</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <section>
        <h2>Materials</h2>
        {materials.length === 0 ? (
          <p>No materials uploaded for this subject.</p>
        ) : (
          <ul>
            {materials.map((material) => (
              <li key={material.id}>
                <strong>{material.filename}</strong> - {material.status} -{" "}
                {Math.ceil(material.fileSize / 1024)} KB
                {material.errorMessage ? <p role="alert">{material.errorMessage}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
