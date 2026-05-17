export type MaterialStatus = "uploaded" | "processing" | "ready" | "failed";

export type Material = {
  id: string;
  subjectId: string;
  filename: string;
  contentType: string;
  fileSize: number;
  status: MaterialStatus;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type MaterialUploadResult = {
  material: Material;
};
