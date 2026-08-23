import { Component, lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { useAppStore } from './stores/useAppStore';
import { ProtectedRoute } from './auth/ProtectedRoute';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Materials = lazy(() => import('./pages/Materials'));
const AIStudyRoom = lazy(() => import('./pages/AIStudyRoom'));
const MindMap = lazy(() => import('./pages/MindMap'));
const Exams = lazy(() => import('./pages/Exams'));
const Plan = lazy(() => import('./pages/Plan'));
const AuthPage = lazy(() => import('./pages/Auth'));

class WorkspaceErrorBoundary extends Component<{ children: React.ReactNode }, { error: string }> {
  state = { error: '' };

  static getDerivedStateFromError(error: Error) {
    return { error: error.message || '页面加载失败' };
  }

  componentDidCatch(error: Error) {
    console.error('Workspace page render failed', error);
  }

  render() {
    if (this.state.error) {
      return <div className="h-full overflow-y-auto bg-slate-50 p-6 md:p-8"><div className="mx-auto max-w-3xl rounded-2xl border border-red-200 bg-white p-6 shadow-sm"><h1 className="text-xl font-bold text-slate-900">页面暂时无法显示</h1><p className="mt-2 text-sm leading-6 text-slate-600">页面组件加载时发生异常，请刷新后重试。若问题持续，请保留下方信息。</p><pre className="mt-4 overflow-auto rounded-lg bg-red-50 p-3 text-xs text-red-800">{this.state.error}</pre><button type="button" onClick={() => window.location.reload()} className="mt-5 min-h-10 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700">刷新页面</button></div></div>;
    }
    return this.props.children;
  }
}

function Workspace({ children }: { children: React.ReactNode }) {
  return useAppStore.getState().currentSubject ? <WorkspaceErrorBoundary>{children}</WorkspaceErrorBoundary> : <Navigate to="/" replace/>;
}

export default function App() {
  return <><div className="desktop-required" role="status"><div><h1>请使用桌面端访问</h1><p>AI 学习工作台目前支持宽度不低于 1024px 的桌面浏览器。</p></div></div><div className="desktop-app"><WorkspaceErrorBoundary><Suspense fallback={<div className="auth-loading" role="status">正在载入界面…</div>}><Routes>
    <Route path="/auth/:mode" element={<AuthPage/>}/>
    <Route element={<ProtectedRoute/>}>
      <Route path="/" element={<MainLayout/>}>
        <Route index element={<Dashboard/>}/>
        <Route path="materials" element={<Workspace><Materials/></Workspace>}/>
        <Route path="study-room" element={<Workspace><AIStudyRoom/></Workspace>}/>
        <Route path="mind-map" element={<Workspace><MindMap/></Workspace>}/>
        <Route path="exams" element={<Workspace><Exams/></Workspace>}/>
        <Route path="wrong-questions" element={<Navigate to="/exams" replace/>}/>
        <Route path="plan" element={<Workspace><Plan/></Workspace>}/>
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes></Suspense></WorkspaceErrorBoundary></div></>;
}
