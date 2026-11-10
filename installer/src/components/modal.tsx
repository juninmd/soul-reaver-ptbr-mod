import { useEffect, useRef, type ReactNode } from 'react';
import Icon from './icon';

interface Props { open: boolean; onClose: () => void; children: ReactNode }

/**
 * Native modal dialog: focus trap, Escape and backdrop come from the platform.
 * The children stay mounted while closed so the exit transition has content
 * to fade; `inert` keeps them unreachable meanwhile.
 */
export default function Modal({ open, onClose, children }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      previousFocus.current = document.activeElement as HTMLElement | null;
      element.showModal();
    } else if (!open && element.open) {
      element.close();
      previousFocus.current?.focus();
    }
  }, [open]);

  return (
    <dialog ref={dialog} inert={!open} aria-labelledby="dialog-title" onCancel={event => { event.preventDefault(); onClose(); }}>
      {children}
      {/* Last in the document: a modal focuses its first control when it opens,
          and that should be the field or the safe choice, not "close". */}
      <button className="dialog-close" aria-label="Fechar diálogo" onClick={onClose}><Icon name="close" /></button>
    </dialog>
  );
}
