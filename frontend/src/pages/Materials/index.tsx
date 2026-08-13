import { ChangeEvent, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, FileText, Loader2, UploadCloud } from 'lucide-react';
import { api } from '../../api/client';
import { useAppStore } from '../../stores/useAppStore';
import type { Material } from '../../types';

export default function Materials() {
  const subject = useAppStore((s) => s.currentSubject)!;
  const [items, setItems] = useState<Material[]>([]);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const load = () => api.materials(subject.id).then(setItems).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, [subject.id]);
  useEffect(() => {
    if (!items.some((item) => item.status === 'queued' || item.status === 'parsing')) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [subject.id, items.some((item) => item.status === 'queued' || item.status === 'parsing')]);
  async function select(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true); setError('');
    try {
      const result = await api.addMaterial(subject.id, file);
      const item = 'material' in result ? result.material : result;
      setItems((rows) => [item, ...rows.filter((row) => row.id !== item.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '上传失败');
    } finally {
      setUploading(false); event.target.value = '';
    }
  }
  return <div className="h-full overflow-y-auto p-6 md:p-8"><header className="mb-8"><h1 className="text-3xl font-bold">资料中心</h1><p className="mt-2 text-slate-500">管理 {subject.name} 的课程文件与解析状态。</p></header>
    <label className="mb-7 flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50/40 p-10 text-center hover:bg-blue-50"><UploadCloud size={34} className="mb-3 text-blue-600"/><b>{uploading ? '正在上传…' : '点击选择资料'}</b><span className="mt-1 text-sm text-slate-500">PDF、Word、PPT、Excel、图片或音频；文档优先使用 MinerU 解析</span><input type="file" disabled={uploading} accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.png,.jpg,.jpeg,.jp2,.webp,.gif,.bmp,.mp3,.wav,.m4a" className="hidden" onChange={select}/></label>
    {error && <p className="mb-4 text-rose-600">{error}</p>}<div className="overflow-hidden rounded-2xl border border-slate-200 bg-white"><div className="grid grid-cols-[1fr_120px_140px] border-b bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-500"><span>文件</span><span>大小</span><span>状态</span></div>{items.length ? items.map((item) => <div key={item.id} className="grid grid-cols-[1fr_120px_140px] items-center border-b border-slate-100 px-5 py-4 last:border-0"><span className="flex items-center font-medium"><FileText size={19} className="mr-3 text-blue-500"/>{item.name}</span><span className="text-sm text-slate-500">{item.size ? `${Math.ceil(item.size / 1024)} KB` : '待上传'}</span><span className="flex items-center text-sm">{item.status === 'indexed' ? <><CheckCircle2 size={16} className="mr-1 text-emerald-500"/>已入库</> : item.status === 'failed' ? <span title={item.errorMessage || undefined} className="flex text-rose-600"><AlertCircle size={16} className="mr-1"/>解析失败</span> : <><Loader2 size={16} className="mr-1 animate-spin text-amber-500"/>{item.status === 'queued' ? '等待解析' : '解析中'}</>}</span></div>) : <div className="p-10 text-center text-slate-400">还没有资料</div>}</div>
  </div>;
}
