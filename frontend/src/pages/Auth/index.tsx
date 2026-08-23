import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowRight, BookOpenCheck, Check, Eye, EyeOff, KeyRound, LoaderCircle, LockKeyhole, Mail, RefreshCw, UserRound } from 'lucide-react';
import { supabase } from '../../lib/supabase';
import { useAuth } from '../../auth/AuthProvider';

type AuthMode = 'login' | 'register' | 'forgot-password' | 'reset-password' | 'verify-email' | 'verified';
type RegisterMethod = 'email' | 'account';

const API_BASE = String(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const ACCOUNT_PATTERN = /^[a-zA-Z][a-zA-Z0-9_]{2,23}$/;
const copy: Record<AuthMode, { title: string; description: string }> = {
  login: { title: '欢迎回来', description: '使用邮箱或账户名登录。' },
  register: { title: '创建账户', description: '选择适合你的注册方式。' },
  'forgot-password': { title: '找回密码', description: '我们会向注册邮箱发送重置链接。' },
  'reset-password': { title: '设置新密码', description: '新密码至少需要 8 位字符。' },
  'verify-email': { title: '验证邮箱', description: '点击邮件中的链接即可完成注册。' },
  verified: { title: '验证成功', description: '现在可以登录学习工作台。' },
};

function accountEmail(username: string) {
  return `${username.trim().toLowerCase()}@account.examai.local`;
}

function friendlyError(message: string) {
  const normalized = message.toLowerCase();
  if (normalized.includes('invalid login credentials')) return '账户、邮箱或密码不正确。';
  if (normalized.includes('email not confirmed')) return '邮箱尚未验证，请先完成验证。';
  if (normalized.includes('already') || normalized.includes('被使用')) return '该邮箱或账户名已经注册。';
  if (normalized.includes('rate limit')) return '操作过于频繁，请稍后再试。';
  return message || '暂时无法完成操作，请稍后重试。';
}

export default function AuthPage() {
  const params = useParams();
  const mode = (params.mode || 'login') as AuthMode;
  const currentMode: AuthMode = Object.hasOwn(copy, mode) ? mode : 'login';
  const location = useLocation();
  const navigate = useNavigate();
  const { user, isConfigured } = useAuth();
  const [identifier, setIdentifier] = useState(() => String((location.state as { email?: string } | null)?.email || ''));
  const [registerMethod, setRegisterMethod] = useState<RegisterMethod>('email');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [resendCooldown, setResendCooldown] = useState(0);

  const destination = useMemo(() => {
    const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;
    return from?.startsWith('/') ? from : '/';
  }, [location.state]);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = window.setInterval(() => setResendCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  useEffect(() => {
    if (currentMode !== 'verified') return;
    const query = new URLSearchParams(window.location.search);
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const callbackError = query.get('error_description') || fragment.get('error_description');
    if (callbackError) setError(friendlyError(decodeURIComponent(callbackError.replace(/\+/g, ' '))));
  }, [currentMode]);

  if (user && ['login', 'register', 'forgot-password'].includes(currentMode)) return <Navigate to={destination} replace />;

  const emailRedirectTo = `${window.location.origin}/auth/verified`;
  const isStaticState = currentMode === 'verify-email' || currentMode === 'verified';
  const usesEmail = currentMode === 'forgot-password' || currentMode === 'verify-email' || (currentMode === 'register' && registerMethod === 'email');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(''); setNotice('');
    if (!isConfigured) return setError('认证服务尚未配置。');
    if (!identifier.trim() && currentMode !== 'reset-password') return setError('请输入邮箱或账户名。');
    if (['register', 'reset-password'].includes(currentMode) && password.length < 8) return setError('密码至少需要 8 位字符。');
    if (['register', 'reset-password'].includes(currentMode) && password !== confirmPassword) return setError('两次输入的密码不一致。');
    if (currentMode === 'register' && registerMethod === 'account' && !ACCOUNT_PATTERN.test(identifier)) return setError('账户名需以字母开头，仅包含字母、数字或下划线，长度为 3–24 位。');

    setIsSubmitting(true);
    try {
      if (currentMode === 'login') {
        const email = identifier.includes('@') ? identifier.trim() : accountEmail(identifier);
        const { data, error: authError } = await supabase.auth.signInWithPassword({ email, password });
        if (authError) {
          if (authError.message.toLowerCase().includes('email not confirmed')) {
            navigate('/auth/verify-email', { replace: true, state: { email } });
            return;
          }
          throw authError;
        }
        if (!data.user) throw new Error('登录失败');
        navigate(destination, { replace: true });
      } else if (currentMode === 'register' && registerMethod === 'email') {
        const email = identifier.trim();
        const { data, error: authError } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo } });
        if (authError) throw authError;
        if (data.session) { await supabase.auth.signOut(); throw new Error('邮箱自动确认配置异常。'); }
        navigate('/auth/verify-email', { replace: true, state: { email } });
      } else if (currentMode === 'register') {
        const response = await fetch(`${API_BASE}/api/v1/auth/account/register`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: identifier, password }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body?.error?.message || body?.detail || '账户注册失败');
        const { error: authError } = await supabase.auth.signInWithPassword({ email: body.loginIdentifier, password });
        if (authError) throw authError;
        navigate(destination, { replace: true });
      } else if (currentMode === 'forgot-password') {
        if (!identifier.includes('@')) throw new Error('账户名登录暂不支持邮件找回，请使用邮箱账户或联系管理员。');
        const { error: authError } = await supabase.auth.resetPasswordForEmail(identifier.trim(), { redirectTo: `${window.location.origin}/auth/reset-password` });
        if (authError) throw authError;
        setNotice('如果邮箱已注册，重置链接将在几分钟内送达。');
      } else if (currentMode === 'reset-password') {
        const { error: authError } = await supabase.auth.updateUser({ password });
        if (authError) throw authError;
        setNotice('密码已更新，即将返回工作台。');
        window.setTimeout(() => navigate('/', { replace: true }), 900);
      }
    } catch (caught) {
      setError(friendlyError(caught instanceof Error ? caught.message : '认证请求失败'));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function resendVerification() {
    if (!identifier || resendCooldown > 0) return;
    setIsSubmitting(true); setError(''); setNotice('');
    const { error: authError } = await supabase.auth.resend({ type: 'signup', email: identifier, options: { emailRedirectTo } });
    setIsSubmitting(false);
    if (authError) setError(friendlyError(authError.message));
    else { setResendCooldown(60); setNotice('验证邮件已重新发送。'); }
  }

  return <div className="auth-shell">
    <section className="auth-story" aria-label="产品介绍">
      <div className="auth-brand auth-mark"><BookOpenCheck aria-hidden="true" /><span>AI 学习工作台</span></div>
      <div className="auth-story-copy">
        <p className="auth-eyebrow auth-mark">专注学习，持续进步</p>
        <h1 className="auth-mark">让每次学习<br />都有清晰方向</h1>
        <p className="auth-mark">整理资料、练习知识、规划复习，都在一个工作台完成。</p>
      </div>
      <p className="auth-security auth-mark"><LockKeyhole aria-hidden="true" />你的账户和学习数据受到安全保护</p>
    </section>

    <main className="auth-main">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-heading">
          <div className="auth-symbol" aria-hidden="true">{currentMode === 'verified' ? <Check /> : usesEmail ? <Mail /> : currentMode === 'register' ? <UserRound /> : <LockKeyhole />}</div>
          <h2 id="auth-title">{copy[currentMode].title}</h2><p>{copy[currentMode].description}</p>
        </div>
        {error && <div className="auth-message auth-message-error" role="alert">{error}</div>}
        {notice && <div className="auth-message auth-message-success" role="status">{notice}</div>}

        {isStaticState ? <div className="auth-static">
          {currentMode === 'verify-email' ? <>
            <div className="verification-address"><Mail /><span>验证邮件已发送至</span><strong>{identifier || '你的注册邮箱'}</strong></div>
            <button className="auth-secondary" type="button" onClick={() => void resendVerification()} disabled={isSubmitting || resendCooldown > 0}>{isSubmitting ? <LoaderCircle className="spin" /> : <RefreshCw />}{resendCooldown ? `${resendCooldown} 秒后重发` : '重新发送验证邮件'}</button>
            <Link className="auth-text-link" to="/auth/login">返回登录</Link>
          </> : <><div className="verified-seal"><Check /></div><p className="verified-copy">邮箱已经验证，可以安全登录。</p><Link className="auth-primary auth-link-button" to="/auth/login">前往登录<ArrowRight /></Link></>}
        </div> : <form className="auth-form" onSubmit={submit} noValidate>
          {currentMode === 'register' && <div className="auth-method" role="group" aria-label="注册方式"><button type="button" className={registerMethod === 'email' ? 'active' : ''} onClick={() => { setRegisterMethod('email'); setIdentifier(''); setError(''); }}><Mail />邮箱注册</button><button type="button" className={registerMethod === 'account' ? 'active' : ''} onClick={() => { setRegisterMethod('account'); setIdentifier(''); setError(''); }}><UserRound />账户注册</button></div>}
          {currentMode !== 'reset-password' && <label className="auth-field"><span>{currentMode === 'login' ? '邮箱或账户名' : usesEmail ? '邮箱地址' : '账户名'}</span><div>{usesEmail ? <Mail /> : <UserRound />}<input required type={usesEmail ? 'email' : 'text'} value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={currentMode === 'login' ? '邮箱或账户名' : usesEmail ? 'name@example.com' : '例如 study_user'} autoComplete={usesEmail ? 'email' : 'username'} /></div>{currentMode === 'register' && registerMethod === 'account' && <small>3–24 位，以字母开头，可使用数字和下划线。</small>}</label>}
          {['login', 'register', 'reset-password'].includes(currentMode) && <label className="auth-field"><span>{currentMode === 'reset-password' ? '新密码' : '密码'}</span><div><KeyRound /><input required minLength={8} type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 位字符" autoComplete={currentMode === 'login' ? 'current-password' : 'new-password'} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? '隐藏密码' : '显示密码'}>{showPassword ? <EyeOff /> : <Eye />}</button></div></label>}
          {['register', 'reset-password'].includes(currentMode) && <label className="auth-field"><span>确认密码</span><div><KeyRound /><input required minLength={8} type={showPassword ? 'text' : 'password'} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="再次输入密码" autoComplete="new-password" /></div></label>}
          {currentMode === 'login' && <div className="auth-form-meta auth-form-meta-end"><Link to="/auth/forgot-password">忘记密码？</Link></div>}
          <button className="auth-primary" disabled={isSubmitting || !isConfigured} type="submit">{isSubmitting ? <><LoaderCircle className="spin" />正在处理</> : <>{currentMode === 'login' ? '登录' : currentMode === 'register' ? '创建账户' : currentMode === 'forgot-password' ? '发送重置链接' : '更新密码'}<ArrowRight /></>}</button>
        </form>}
        {!isStaticState && <div className="auth-switch">{currentMode === 'login' ? <>还没有账户？<Link to="/auth/register">立即注册</Link></> : currentMode === 'register' ? <>已有账户？<Link to="/auth/login">返回登录</Link></> : <Link to="/auth/login">返回登录</Link>}</div>}
      </section>
      <p className="auth-footer">邮箱登录与账户名登录均受支持</p>
    </main>
  </div>;
}
