import { create } from 'zustand';
import type { Subject } from '../types';

const SUBJECT_STORAGE_KEY = 'workbench-subject';
const SUBJECT_OWNER_STORAGE_KEY = 'workbench-subject-owner';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const usesMockSubjects = import.meta.env.VITE_MOCK_APP === 'true';

function isSubject(value: unknown): value is Subject {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<Subject>;
  return typeof candidate.id === 'string'
    && typeof candidate.name === 'string'
    && typeof candidate.description === 'string';
}

function readStoredSubject(): Subject | null {
  try {
    const raw = localStorage.getItem(SUBJECT_STORAGE_KEY);
    if (!raw) return null;
    const subject: unknown = JSON.parse(raw);
    if (!isSubject(subject) || (!usesMockSubjects && !UUID_PATTERN.test(subject.id))) {
      localStorage.removeItem(SUBJECT_STORAGE_KEY);
      return null;
    }
    return subject;
  } catch {
    localStorage.removeItem(SUBJECT_STORAGE_KEY);
    return null;
  }
}

interface AppState {
  currentSubject: Subject | null;
  setCurrentSubject: (subject: Subject | null) => void;
  isSidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentSubject: readStoredSubject(),
  setCurrentSubject: (subject) => {
    if (subject && (usesMockSubjects || UUID_PATTERN.test(subject.id))) {
      localStorage.setItem(SUBJECT_STORAGE_KEY, JSON.stringify(subject));
      set({ currentSubject: subject });
      return;
    }
    localStorage.removeItem(SUBJECT_STORAGE_KEY);
    set({ currentSubject: null });
  },
  isSidebarOpen: true,
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
}));

export function syncWorkspaceOwner(userId: string | null) {
  const previousOwner = localStorage.getItem(SUBJECT_OWNER_STORAGE_KEY);
  if (!userId) {
    localStorage.removeItem(SUBJECT_OWNER_STORAGE_KEY);
    useAppStore.getState().setCurrentSubject(null);
    return;
  }
  if (previousOwner !== userId) useAppStore.getState().setCurrentSubject(null);
  localStorage.setItem(SUBJECT_OWNER_STORAGE_KEY, userId);
}
