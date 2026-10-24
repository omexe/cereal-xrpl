import { useEffect, useRef, type ReactNode } from 'react';
import { XClose } from '@untitledui/icons';

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} onCancel={onClose} aria-labelledby="dialog-title"
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="dialog-content">
      <header><h2 id="dialog-title">{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><XClose /></button></header>
      {children}
    </div>
  </dialog>;
}
