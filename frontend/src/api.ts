export type Row = Record<string, any>;
export type Kind = 'tasks' | 'logs' | 'changes' | 'risks';
export type RecordKind = Kind | 'communications' | 'configurations' | 'costs' | 'research';
export type ResearchNavigation = {filters: Row; index: number; total: number};
export async function api<T = any>(path: string, method = 'GET', data?: unknown, key?: string): Promise<T> {
  const response = await fetch('/api' + path, {method, headers: {'X-PM-Client':'workbench', ...(data instanceof FormData ? {} : {'Content-Type':'application/json'}), ...(key ? {'Idempotency-Key':key} : {})}, body: data === undefined ? undefined : data instanceof FormData ? data : JSON.stringify(data)});
  if (!response.ok) { const error = await response.json().catch(() => ({detail:'服务连接失败'})); throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail)); }
  if (response.headers.get('X-Backup-Warning')) window.dispatchEvent(new CustomEvent('backup-warning'));
  return response.json();
}
export async function download(path: string) {
  const response = await fetch('/api' + path);
  if (!response.ok) {const error = await response.json(); throw new Error(error.detail);}
  const blob = await response.blob(), url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url;
  const disposition = response.headers.get('Content-Disposition') || '';
  const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i);
  link.download = encoded ? decodeURIComponent(encoded[1]) : disposition.match(/filename="([^"]+)"/)?.[1] || '下载文件';
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
}
export const day = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export const labels: Record<RecordKind,string> = {tasks:'任务',logs:'工作日志',changes:'需求变更',risks:'项目风险',communications:'项目沟通',configurations:'配置记录',costs:'费用',research:'需求调研'};
export const localTime = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ','T');
export const taskStates = ['未开始','进行中','暂停','已完成','已取消'];
export const heads = ['项目概况','本期工作','任务与交付情况','进度偏差','需求变更','风险与待协调事项','后续计划'];

export const expenseItems = ['省际交通费','市内交通费','住宿费','业务招待费','Token','其他'];
export function formatMoney(value:string = '0.00'){const [whole,fraction='00']=value.split('.');return whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+fraction.padEnd(2,'0');}
