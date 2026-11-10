import Icon from './icon';

export type WindowAction = 'minimize' | 'toggleMaximize' | 'close';

interface Props { edition: string; onAction: (action: WindowAction) => void }

/** Custom title bar: the window has no native decorations. */
export default function WindowTitlebar({ edition, onAction }: Props) {
  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="titlebar-brand" data-tauri-drag-region>
        <Icon name="rune" />
        <span data-tauri-drag-region>SOUL REAVER <b data-tauri-drag-region>/ PROJETO PT-BR</b></span>
      </div>
      <div className="window-actions">
        <span className="preview-label">{edition} · NOSGOTH</span>
        <button aria-label="Minimizar janela" onClick={() => onAction('minimize')}><Icon name="minus" /></button>
        <button aria-label="Maximizar ou restaurar janela" onClick={() => onAction('toggleMaximize')}><Icon name="maximize" /></button>
        <button aria-label="Fechar janela" className="close-window" onClick={() => onAction('close')}><Icon name="close" /></button>
      </div>
    </header>
  );
}
