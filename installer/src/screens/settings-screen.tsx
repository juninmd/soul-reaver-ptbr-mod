import Icon from '../components/icon';
import { ipc } from '../installer/ipc';
import type { Settings } from '../installer/settings';
import type { Updater } from '../installer/updater';
import type { ScreenProps } from './screen-props';

interface Props extends ScreenProps { updater: Updater; settings: Settings; onSettings: (patch: Partial<Settings>) => void }

function status(updater: Updater): string {
  const { state } = updater;
  switch (state.phase) {
    case 'checking': return 'Procurando atualizações…';
    case 'current': return `Você está na versão mais recente (verificado às ${new Date(state.checkedAt).toLocaleTimeString('pt-BR')}).`;
    case 'available': return `Versão v${state.version} disponível.`;
    case 'downloading': return `Baixando v${state.version}…`;
    case 'installing': return `Instalando v${state.version}…`;
    case 'error': return `Falha ao atualizar: ${state.message}`;
    default: return updater.supported ? 'Nenhuma verificação feita nesta sessão.' : 'Atualizações estão disponíveis no aplicativo desktop.';
  }
}

export default function SettingsScreen({ installer: i, updater, settings, onSettings }: Props) {
  const { state } = updater;
  const working = state.phase === 'checking' || state.phase === 'downloading' || state.phase === 'installing';
  return (
    <section className="workspace settings-workspace reveal">
      <div className="eyebrow">AJUSTES DO INSTALADOR</div>
      <h1 tabIndex={-1}>Configurações</h1>
      <p className="intro">Versão, atualizações automáticas e arquivos de registro.</p>

      <div className="settings-card">
        <h2>Versão</h2>
        <p><strong>Instalador:</strong> {updater.version ? `v${updater.version}` : '—'}</p>
        {i.bundle && <p><strong>Pacote do mod:</strong> v{i.bundle.version}</p>}
      </div>

      <div className="settings-card">
        <h2>Atualizações</h2>
        <label className="settings-toggle">
          <input type="checkbox" checked={settings.autoUpdate} onChange={e => onSettings({ autoUpdate: e.target.checked })} />
          <span>Procurar atualizações ao abrir o aplicativo</span>
        </label>
        <p role="status" aria-live="polite">{status(updater)}</p>
        <div className="settings-actions">
          <button className="secondary" disabled={!updater.supported || working} onClick={() => void updater.check()}>Verificar agora</button>
          {state.phase === 'available' && <button className="primary" disabled={i.busy} onClick={() => void updater.install()}><Icon name="spark" />Atualizar para v{state.version}</button>}
        </div>
        {state.phase === 'available' && state.notes && <pre className="update-notes">{state.notes}</pre>}
      </div>

      <div className="settings-card">
        <h2>Registros</h2>
        <p>Arquivos de log das operações do instalador.</p>
        <button className="secondary" disabled={!updater.supported} onClick={() => void ipc.openLogsFolder()}><Icon name="folder" />Abrir pasta de logs</button>
      </div>
    </section>
  );
}
