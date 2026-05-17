import { request } from "../utils/request";
import type { Material, MaterialUploadResult } from "../types/material";

export function listMaterials(subjectId?: string) {
  const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : "";
  return request<Material[]>(`/materials${query}`);
}

export function uploadMaterial(subjectId: string, file: File) {
  const formData = new FormData();
  formData.append("subject_id", subjectId);
  formData.append("file", file);

  return request<MaterialUploadResult>("/materials/upload", {
    method: "POST",
    body: formData,
  });
}

export function getMaterial(materialId: string) {
  return request<Material>(`/materials/${materialId}`);
}
