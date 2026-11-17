import Icon from './icon';
import type { Updater } from '../installer/updater';

/** Always-visible strip while an update exists, downloads or installs. */
export default function UpdateBanner({ updater, busy }: { updater: Updater; busy: boolean }) {
  const { state } = updater;
  if (state.phase !== 'available' && state.phase !== 'downloading' && state.phase !== 'installing') return null;
  const percent = state.phase === 'downloading' && state.total > 0 ? Math.min(100, Math.round(state.received / state.total * 100)) : null;
  return (
    <div className="update-banner" role="status" aria-live="polite">
      <Icon name="spark" />
      {state.phase === 'available' && <>
        <span>Nova versão <b>v{state.version}</b> disponível.</span>
        <button className="primary" disabled={busy} title={busy ? 'Aguarde a operação terminar' : undefined} onClick={() => void updater.install()}>Atualizar agora</button>
      </>}
      {state.phase === 'downloading' && <>
        <span>Baixando <b>v{state.version}</b>{percent !== null ? ` · ${percent}%` : '…'}</span>
        <progress max={100} value={percent ?? undefined} aria-label="Progresso do download" />
      </>}
      {state.phase === 'installing' && <span>Instalando <b>v{state.version}</b>… o aplicativo vai reiniciar.</span>}
    </div>
  );
}
