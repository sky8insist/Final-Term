import { create } from 'zustand';
import type { Subject } from '../types';

interface AppState {
  currentSubject: Subject | null;
  setCurrentSubject: (subject: Subject | null) => void;
  isSidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentSubject: JSON.parse(localStorage.getItem('workbench-subject') || 'null'),
  setCurrentSubject: (subject) => { localStorage.setItem('workbench-subject', JSON.stringify(subject)); set({ currentSubject: subject }); },
  isSidebarOpen: true,
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
}));
