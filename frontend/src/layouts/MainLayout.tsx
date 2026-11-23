import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { mergeCacheNotices, type CacheNotice } from '../api/versionedCache';
import { BarChart3, BookOpen, Calendar, ChevronLeft, FileText, Info, LayoutDashboard, LogOut, Menu, MessageSquare, Moon, Network, PenTool } from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { cn } from '../utils/cn';
import { useAuth } from '../auth/AuthProvider';
import { api } from '../api/client';

const links = [
  { path: '/', label: '仪表盘', icon: LayoutDashboard, global: true },
  { path: '/calendar', label: '学习日历', icon: Calendar, global: true },
  { path: '/learning-metrics', label: '学习记录', icon: BarChart3, global: true },
  { path: '/materials', label: '资料中心', icon: FileText },
  { path: '/lectures', label: '课堂录音', icon: BookOpen },
  { path: '/course', label: '课程结构', icon: BookOpen },
  { path: '/notes', label: '学习笔记', icon: FileText },
  { path: '/convert', label: '转换学习方式', icon: Network },
  { path: '/study-room', label: 'AI 学习室', icon: MessageSquare },
  { path: '/mind-map', label: '思维导图', icon: Network },
  { path: '/exams', label: '练习考试', icon: PenTool },
  { path: '/guided-study', label: '引导学习', icon: BookOpen },
  { path: '/flashcards', label: '闪卡复习', icon: BookOpen },
  { path: '/plan', label: '复习计划', icon: Calendar },
  { path: '/daily-review', label: '学习复盘', icon: Moon },
];

export function MainLayout() {
  const { currentSubject, isSidebarOpen, toggleSidebar } = useAppStore();
  const { user, signOut } = useAuth();
  const [cacheFlags, setCacheFlags] = useState<CacheNotice[]>([]);
  const [changed,setChanged]=useState(false);
  const [unverified,setUnverified]=useState(false);
  const baseline=useRef<string|undefined>(undefined);
  const fallbackVersion=useRef<string|undefined>(undefined);
  const location=useLocation();
  const resource=({'/':'dashboard','/study-room':'chat','/exams':'exams','/plan':'plan','/mind-map':'mind-map','/materials':'mind-map','/course':'plan'} as Record<string,string>)[location.pathname];
  const scope=resource==='dashboard'?undefined:currentSubject?.id;
  const visibleCache=cacheFlags.find(flag=>flag.ownerId===user?.id&&flag.resource===resource&&flag.subjectId===scope);
  const email = user?.email || '已认证账户';
  const avatar = email.slice(0, 1).toUpperCase();
  useEffect(() => {
    const onCache = (event: Event) => {
      const detail = (event as CustomEvent<CacheNotice>).detail;
      if(!detail || detail.ownerId!==user?.id)return;
      setCacheFlags(flags=>mergeCacheNotices(flags,detail));
      if(detail.resource===resource&&detail.subjectId===scope) {
        if(detail.dataVersion)baseline.current=detail.dataVersion;
        fallbackVersion.current=detail.cachedAt?detail.version:undefined;
        setChanged(false);setUnverified(false);
      }
    };
    window.addEventListener('examai-cache-status', onCache);
    return () => window.removeEventListener('examai-cache-status', onCache);
  }, [user?.id,resource,scope]);

  useEffect(()=>{setCacheFlags([]);},[user?.id]);
  useEffect(()=>{
    let active=true;
    baseline.current=undefined;fallbackVersion.current=undefined;setChanged(false);setUnverified(false);
    if(!user?.id || !resource || (resource!=='dashboard'&&!scope))return;
    let pending=false;
    async function check() {
      if(pending || document.visibilityState==='hidden')return;
      pending=true;
      try {
        const value=await api.workspaceVersion(resource,scope);
        if(!active)return;
        if(baseline.current && baseline.current!==value.dataVersion)setChanged(true);
        if(fallbackVersion.current&&fallbackVersion.current!==value.version)setChanged(true);
        baseline.current=value.dataVersion;setUnverified(false);
      } catch {if(active)setUnverified(true);}
      finally{pending=false;}
    }
    void check();
    const timer=window.setInterval(()=>void check(),15000);
    const focus=()=>void check();
    window.addEventListener('focus',focus);
    document.addEventListener('visibilitychange',focus);
    return()=>{active=false;window.clearInterval(timer);window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
  },[user?.id,resource,scope]);

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
    <aside className={cn('app-sidebar flex shrink-0 flex-col border-r border-slate-200 bg-white transition-all', isSidebarOpen ? 'w-64' : 'w-18')}>
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
      {(visibleCache||changed)&&<div className="flex flex-wrap items-center gap-2 bg-amber-100 px-4 py-2 text-sm text-amber-950" role="status"><Info size={16}/><span className="min-w-0 flex-1">{changed?'检测到新记录或缓存已过期，请刷新当前页面。':unverified?'主请求暂不可用，当前缓存版本暂时无法复核，请恢复连接后刷新。':`主请求暂不可用，当前展示已校验版本的缓存（${new Date(visibleCache!.cachedAt!).toLocaleString('zh-CN')}）。`}</span><button type="button" className="min-h-11 rounded-lg px-3 font-semibold underline focus-visible:outline-2 focus-visible:outline-amber-950" onClick={()=>window.location.reload()}>刷新当前页</button></div>}
      <div className="min-h-0 flex-1 overflow-hidden"><Outlet key={user?.id}/></div>
    </main>
  </div>;
}
