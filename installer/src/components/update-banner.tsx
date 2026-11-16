import type { Updater } from '../installer/use-updater';

const mb = (bytes: number) => (bytes / 1048576).toFixed(1);

/** Always-visible update status: offer, live download progress and install hand-off. */
export default function UpdateBanner({ updater: u, blocked }: { updater: Updater; blocked: boolean }) {
  if (u.phase === 'available') return (
    <div className="update-banner" role="status">
      <span>Nova versão <b>v{u.available?.version}</b> disponível.</span>
      <button className="primary" disabled={blocked} title={blocked ? 'Aguarde a operação terminar' : undefined} onClick={() => void u.install()}>Atualizar agora</button>
    </div>
  );
  if (u.phase === 'downloading' || u.phase === 'installing') {
    const { downloaded = 0, total = 0 } = u.progress ?? {};
    const pct = total ? Math.min(100, Math.round(downloaded / total * 100)) : null;
    return (
      <div className="update-banner" role="status" aria-live="polite">
        <span>{u.phase === 'installing' ? 'Instalando e reiniciando…' : `Baixando v${u.available?.version}… ${pct === null ? `${mb(downloaded)} MB` : `${pct}% (${mb(downloaded)}/${mb(total)} MB)`}`}</span>
        <progress max={100} value={pct ?? undefined} aria-label="Progresso da atualização" />
      </div>
    );
  }
  return null;
}
