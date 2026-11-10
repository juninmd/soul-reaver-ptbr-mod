import DualSensePanel from '../components/dualsense-panel';
import GameLocation from '../components/game-location';
import Icon from '../components/icon';
import Notices from '../components/notices';
import { diagnosticLabel } from '../installer/model';
import type { ScreenProps } from './screen-props';

function Badge({ ok, children }: { ok: boolean; children: string }) {
  return <span className={`badge ${ok ? 'spectral' : 'amber'}`}><Icon name={ok ? 'check' : 'alert'} />{children}</span>;
}

export default function DiagnosticsScreen({ installer: i, onOpenModal, onChangeLocation }: ScreenProps) {
  const report = i.diagnostics;
  return (
    <section className="workspace diagnostics-workspace reveal">
      <div className="eyebrow">CONHEÇA CADA DETALHE</div>
      <h1 tabIndex={-1}>Seu legado, em ordem.</h1>
      <p className="intro">Estado dos arquivos, cobertura e suporte ao controle.</p>
      <div className="diagnostics-grid">
        <section className="diagnostic-panel">
          <GameLocation installer={i} onChange={onChangeLocation} />
          <div className="section-heading">
            <h2>Diagnóstico da instalação</h2>
            <button className="text-button" disabled={i.busy || !i.gamePath} onClick={() => void i.refresh()}>{i.loading ? 'Verificando…' : 'Atualizar diagnóstico'}</button>
          </div>
          {report ? <>
            <div className="diagnostic-badges">
              <Badge ok={report.exeSupported}>{report.exeSupported ? 'Executável suportado' : 'Executável incompatível'}</Badge>
              <Badge ok={report.gameClosed}>{report.gameClosed ? 'Jogo fechado' : 'Jogo em execução'}</Badge>
            </div>
            <ul className="diagnostic-list">
              {report.items.map(item => (
                <li key={item.id} className={item.ok ? 'ok' : ''}>
                  <span className="diagnostic-mark" aria-hidden="true">{item.ok ? <Icon name="check" /> : null}</span>
                  <div><strong>{diagnosticLabel(item.id)}</strong><p>{item.detail}</p></div>
                </li>
              ))}
            </ul>
            <details className="integrity-details"><summary>Integridade do executável</summary><code>{report.exeSha256}</code></details>
          </> : <p className="quiet">{i.loading ? 'Conferindo arquivos e compatibilidade…' : 'Escolha uma pasta e atualize o diagnóstico para consultar os arquivos.'}</p>}
          {i.bundle && <p className="quiet package-info">Pacote: {i.bundle.name} · v{i.bundle.version}<br />Dublagem: {i.bundle.voices.replaced}/{i.bundle.voices.total} falas do catálogo · campanha parcial.</p>}
        </section>
        <DualSensePanel gamePath={i.gamePath} status={i.controller} disabled={i.busy || !i.gameInfo || !i.listenersReady} action={i.controllerAction}
          onAction={action => action === 'refresh' ? void i.runController(action) : onOpenModal(`controller-${action}`)} onOpenLogs={i.openLogsFolder} />
      </div>
      <Notices installer={i} />
    </section>
  );
}
