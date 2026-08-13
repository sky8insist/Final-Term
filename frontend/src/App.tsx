import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { useAppStore } from './stores/useAppStore';
import { ProtectedRoute } from './auth/ProtectedRoute';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Materials = lazy(() => import('./pages/Materials'));
const AIStudyRoom = lazy(() => import('./pages/AIStudyRoom'));
const MindMap = lazy(() => import('./pages/MindMap'));
const Exams = lazy(() => import('./pages/Exams'));
const WrongQuestions = lazy(() => import('./pages/WrongQuestions'));
const Plan = lazy(() => import('./pages/Plan'));
const AuthPage = lazy(() => import('./pages/Auth'));

function Workspace({ children }: { children: React.ReactNode }) {
  return useAppStore.getState().currentSubject ? children : <Navigate to="/" replace/>;
}

export default function App() {
  return <><div className="desktop-required" role="status"><div><h1>请使用桌面端访问</h1><p>AI 学习工作台目前支持宽度不低于 1024px 的桌面浏览器。</p></div></div><div className="desktop-app"><Suspense fallback={<div className="auth-loading" role="status">正在载入界面…</div>}><Routes>
    <Route path="/auth/:mode" element={<AuthPage/>}/>
    <Route element={<ProtectedRoute/>}>
      <Route path="/" element={<MainLayout/>}>
        <Route index element={<Dashboard/>}/>
        <Route path="materials" element={<Workspace><Materials/></Workspace>}/>
        <Route path="study-room" element={<Workspace><AIStudyRoom/></Workspace>}/>
        <Route path="mind-map" element={<Workspace><MindMap/></Workspace>}/>
        <Route path="exams" element={<Workspace><Exams/></Workspace>}/>
        <Route path="wrong-questions" element={<Workspace><WrongQuestions/></Workspace>}/>
        <Route path="plan" element={<Workspace><Plan/></Workspace>}/>
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes></Suspense></div></>;
}
