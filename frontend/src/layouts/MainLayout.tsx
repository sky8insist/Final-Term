import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { AlertCircle, BookOpen, Calendar, ChevronLeft, FileText, Info, LayoutDashboard, LogOut, Menu, MessageSquare, Network, PenTool } from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { cn } from '../utils/cn';
import { useAuth } from '../auth/AuthProvider';
import { api } from '../api/client';

const links = [
  { path: '/', label: '仪表盘', icon: LayoutDashboard, global: true },
  { path: '/materials', label: '资料中心', icon: FileText },
  { path: '/study-room', label: 'AI 学习室', icon: MessageSquare },
  { path: '/mind-map', label: '思维导图', icon: Network },
  { path: '/exams', label: '练习考试', icon: PenTool },
  { path: '/wrong-questions', label: '错题本', icon: AlertCircle },
  { path: '/plan', label: '复习计划', icon: Calendar },
];

export function MainLayout() {
  const { currentSubject, isSidebarOpen, toggleSidebar } = useAppStore();
  const { user, signOut } = useAuth();
  const [cachedAt, setCachedAt] = useState<string | null>(null);
  const email = user?.email || '已认证账户';
  const avatar = email.slice(0, 1).toUpperCase();
  useEffect(() => {
    const onCache = (event: Event) => {
      const detail = (event as CustomEvent<{ cachedAt?: string } | null>).detail;
      setCachedAt(detail?.cachedAt ?? null);
    };
    window.addEventListener('examai-cache-status', onCache);
    return () => window.removeEventListener('examai-cache-status', onCache);
  }, []);

  async function handleSignOut() {
    try {
      await api.saveWorkspaceState({
        currentSubjectId: currentSubject?.id ?? null,
        endedAt: new Date().toISOString(),
      });
    } finally {
      await signOut();
    }
  }
  return <div className="flex h-screen overflow-hidden bg-slate-50 text-slate-900">
    <aside className={cn('flex shrink-0 flex-col border-r border-slate-200 bg-white transition-all', isSidebarOpen ? 'w-64' : 'w-18')}>
      <div className="flex h-16 items-center justify-between border-b border-slate-100 px-4">
        {isSidebarOpen && <span className="font-bold text-slate-800">AI 学习工作台</span>}
        <button aria-label="切换侧边栏" onClick={toggleSidebar} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">{isSidebarOpen ? <ChevronLeft size={20}/> : <Menu size={20}/>}</button>
      </div>
      {currentSubject && isSidebarOpen && <div className="border-b border-blue-100 bg-blue-50/60 p-4"><div className="text-xs text-blue-950/60">当前学习科目</div><div className="mt-1 flex items-center font-bold text-blue-700"><BookOpen size={16} className="mr-2"/>{currentSubject.name}</div></div>}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {links.filter((link) => link.global || currentSubject).map(({ path, label, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} className={({ isActive }) => cn('flex items-center rounded-lg px-3 py-2.5 text-sm transition-colors', isActive ? 'bg-blue-50 font-semibold text-blue-700' : 'text-blue-950 hover:bg-slate-100')}><Icon size={19} className={cn('shrink-0', isSidebarOpen && 'mr-3')}/>{isSidebarOpen && label}</NavLink>)}
      </nav>
      <div className="border-t border-slate-100 p-3">
        <div className="flex items-center gap-2">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-blue-100 font-bold text-blue-700">{avatar}</div>
          {isSidebarOpen && <div className="min-w-0 flex-1"><div className="text-sm font-medium">学习者</div><div className="truncate text-xs text-slate-400" title={email}>{email}</div></div>}
          <button aria-label="退出登录" title="退出登录" onClick={() => void handleSignOut()} className="rounded-lg p-2 text-slate-600 transition-colors hover:bg-red-50 hover:text-red-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"><LogOut size={18}/></button>
        </div>
      </div>
    </aside>
    <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
      {cachedAt && <div className="flex items-center gap-2 bg-amber-100 px-4 py-2 text-sm text-amber-950" role="status"><Info size={16}/><span>当前展示最近一次成功保存的内容（{new Date(cachedAt).toLocaleString('zh-CN')}），恢复连接后将自动更新。</span></div>}
      <div className="min-h-0 flex-1 overflow-hidden"><Outlet/></div>
    </main>
  </div>;
}
