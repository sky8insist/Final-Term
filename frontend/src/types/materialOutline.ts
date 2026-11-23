export type MaterialSection = {
  sourceBlockId: string | null; title: string; chapterTitle: string | null;
  headingPath: string[]; blockIds: string[]; pageNumber: number | null;
};
export type TopicProposal = {
  id: string; source_block_id: string; title: string; chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected'; version: number;
  knowledge_point_id: string | null;
};
export type MaterialOutline = {
  id: string; stale: boolean; sections: MaterialSection[]; proposals: TopicProposal[];
};
