import type { ScreenProps } from './screen-props';

const labels = { idle: '', checking: 'Procurando atualizações…', uptodate: 'Você está na versão mais recente.', available: 'Nova versão disponível.', downloading: 'Baixando…', installing: 'Instalando…', error: 'Falha ao verificar.' } as const;

export default function SettingsScreen({ updater: u, installer: i }: ScreenProps) {
  const working = u.phase === 'checking' || u.phase === 'downloading' || u.phase === 'installing';
  return (
    <section className="workspace settings-workspace reveal">
      <div className="eyebrow">AJUSTES DO INSTALADOR</div>
      <h1 tabIndex={-1}>Configurações.</h1>
      <p className="intro">Versão, atualizações e informações do pacote.</p>
      <dl className="settings-list">
        <div><dt>Versão do instalador</dt><dd>{u.version ? `v${u.version}` : 'indisponível fora do app desktop'}</dd></div>
        <div><dt>Versão do pacote de vozes</dt><dd>{i.bundle ? `v${i.bundle.version}` : 'não carregado'}</dd></div>
      </dl>
      <h2 className="restore-title">Atualizações</h2>
      <label className="render-row"><span>Verificar atualizações ao abrir</span>
        <input type="checkbox" checked={u.auto} onChange={event => u.setAuto(event.target.checked)} /></label>
      <p className="quiet" role="status">{labels[u.phase]}{u.available && ` v${u.available.version}`}{u.checkedAt && u.phase !== 'checking' ? ` Última verificação: ${u.checkedAt.toLocaleTimeString('pt-BR')}.` : ''}</p>
      {u.available?.notes && <pre className="update-notes">{u.available.notes}</pre>}
      {u.error && <p className="notice danger" role="alert">{u.error}</p>}
      <div className="restore-bottom">
        <button className="secondary" disabled={working} onClick={() => void u.checkNow()}>Verificar agora</button>
        {u.phase === 'available' && <button className="primary" disabled={i.busy} onClick={() => void u.install()}>Atualizar para v{u.available?.version}</button>}
      </div>
      <p className="quiet">As atualizações vêm das releases do GitHub e têm a assinatura verificada antes da instalação. Seus saves e backups não são tocados.</p>
    </section>
  );
}
