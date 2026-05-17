import { request } from "../utils/request";
import type { RetrievalSearchRequest, RetrievalSearchResponse } from "../types/retrieval";

export function searchRetrievalContext(payload: RetrievalSearchRequest) {
  return request<RetrievalSearchResponse>("/retrieval/search", {
    method: "POST",
    body: payload,
  });
}
