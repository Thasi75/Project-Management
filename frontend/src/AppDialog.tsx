import {createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode} from 'react';
import {AlertTriangle, FilePenLine, X} from 'lucide-react';

type Options = {title: string; message: string; confirmText?: string; cancelText?: string; danger?: boolean};
type TextOptions = Options & {label: string; initialValue?: string; required?: boolean};
type Request = Options & {mode: 'confirm' | 'text'; label?: string; initialValue?: string; required?: boolean};
type DialogActions = {
  confirmAction: (options: Options) => Promise<boolean>;
  askText: (options: TextOptions) => Promise<string | null>;
};
const DialogContext = createContext<DialogActions | null>(null);

export function useAppDialog() {
  const context = useContext(DialogContext);
  if (!context) throw new Error('System dialog provider is missing');
  return context;
}

export function AppDialogProvider({children}: {children: ReactNode}) {
  const [request, setRequest] = useState<Request | null>(null);
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const pending = useRef<((value: string | null) => void) | null>(null);
  const id = useId();

  const ask = useCallback((options: Request) => {
    // The active modal blocks further actions; do not replace an unresolved request.
    if (pending.current) return Promise.resolve(null);
    return new Promise<string | null>(resolve => {
      pending.current = resolve;
      setValue(options.initialValue ?? '');
      setError('');
      setRequest(options);
    });
  }, []);
  const confirmAction = useCallback(async (options: Options) => (await ask({...options, mode: 'confirm'})) !== null, [ask]);
  const askText = useCallback((options: TextOptions) => ask({...options, mode: 'text'}), [ask]);

  function finish(result: string | null) {
    const resolve = pending.current;
    if (!resolve) return;
    pending.current = null;
    dialog.current?.close();
    setRequest(null);
    resolve(result);
  }

  useEffect(() => {
    if (!request) return;
    dialog.current?.showModal();
    if (request.mode === 'text') input.current?.focus();
    else cancel.current?.focus();
  }, [request]);
  useEffect(() => () => {pending.current?.(null); pending.current = null;}, []);

  return <DialogContext.Provider value={{confirmAction, askText}}>
    {children}
    {request && <dialog ref={dialog} className="modal system-dialog" role="alertdialog"
      aria-labelledby={id + '-title'} aria-describedby={id + '-message'}
      onCancel={event => {event.preventDefault(); finish(null);}}>
      <div className="modal-head">
        <div className="system-dialog-title">
          <span className={'system-dialog-icon ' + (request.danger ? 'warning' : '')}>
            {request.mode === 'text' ? <FilePenLine size={22}/> : <AlertTriangle size={22}/>}
          </span>
          <h2 id={id + '-title'}>{request.title}</h2>
        </div>
        <button type="button" className="icon" aria-label="关闭提示" onClick={() => finish(null)}><X size={20}/></button>
      </div>
      <form noValidate onSubmit={event => {
        event.preventDefault();
        if (request.mode === 'text' && request.required && !value.trim()) {
          setError('请填写' + request.label); input.current?.focus(); return;
        }
        finish(request.mode === 'text' ? value : 'confirmed');
      }}>
        <div className="modal-body">
          <p id={id + '-message'}>{request.message}</p>
          {request.mode === 'text' && <label className="field"><span>{request.label}{request.required && <b> *</b>}</span>
            <textarea ref={input} rows={4} value={value} aria-invalid={!!error} aria-describedby={error ? id + '-error' : undefined}
              onChange={event => {setValue(event.target.value); setError('');}}/>
          </label>}
          {error && <p id={id + '-error'} className="error-text" role="alert">{error}</p>}
        </div>
        <div className="modal-foot">
          <button ref={cancel} type="button" onClick={() => finish(null)}>{request.cancelText || '取消'}</button>
          <button type="submit" className={request.danger ? 'danger-button' : 'primary'}>{request.confirmText || '确定'}</button>
        </div>
      </form>
    </dialog>}
  </DialogContext.Provider>;
}
