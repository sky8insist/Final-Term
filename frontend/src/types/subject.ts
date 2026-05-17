export type Subject = {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
};

export type CreateSubjectPayload = {
  name: string;
  description?: string;
};
