export const DEFAULT_MAX_SIZE = 200 * 1024 * 1024;
const DEFAULT_ALLOWED_TYPES = [
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

export type FileValidationResult = {
  valid: boolean;
  reason?: string;
};

export function validateFile(
  file: File,
  allowedTypes = DEFAULT_ALLOWED_TYPES,
  maxSize = DEFAULT_MAX_SIZE,
): FileValidationResult {
  if (!allowedTypes.includes(file.type)) {
    return { valid: false, reason: "Unsupported file type" };
  }

  if (file.size > maxSize) {
    return { valid: false, reason: "File must be 200MB or smaller" };
  }

  return { valid: true };
}
