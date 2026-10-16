import Icon from './icon';
import type { ControllerStatus } from './installer-model';
import type { ControllerAction } from './use-installer';

interface Props {
  gamePath: string; disabled: boolean; status: ControllerStatus | null; action: ControllerAction | null;
  onAction: (action: ControllerAction) => void;
}
function FaceIcon({ shape, label }: { shape: 'triangle' | 'circle' | 'cross' | 'square'; label: string }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return <svg className={`ds-face-icon ds-${shape}`} viewBox="0 0 24 24" role="img" aria-label={label}>
    {shape === 'triangle' && <path {...common} d="M12 4 20 19H4L12 4Z" />}
    {shape === 'circle' && <circle {...common} cx="12" cy="12" r="7.5" />}
    {shape === 'cross' && <path {...common} d="m7 7 10 10M17 7 7 17" />}
    {shape === 'square' && <rect {...common} x="5" y="5" width="14" height="14" rx="1.5" />}
  </svg>;
}
const mappings = [
  { shape: null, key: 'Analógico / direcional', action: 'Movimentar (padrão: setas)' },
  { shape: 'triangle' as const, key: '△', action: 'Mirar / agarrar (F)' },
  { shape: 'cross' as const, key: '✕', action: 'Pular / nadar (X)' },
  { shape: 'square' as const, key: '□', action: 'Atacar / interagir (A)' },
  { shape: 'circle' as const, key: '○', action: 'Absorver almas (D)' },
  { shape: null, key: 'L1', action: 'Focar / andar devagar (S)' },
  { shape: null, key: 'R1', action: 'Agachar (C)' },
  { shape: null, key: 'Analógico direito', action: 'Olhar para esquerda / direita' },
  { shape: null, key: 'L2 / R2', action: 'Sem ação atribuída' },
  { shape: null, key: 'Create', action: 'Menu de glifos / confirmar (Enter)' },
  { shape: null, key: 'Options', action: 'Pausar / voltar (Esc)' },
];
export default function DualSensePanel({ gamePath, disabled, status, action, onAction }: Props) {
  const busy = disabled || !gamePath;
  return <section className="controller-panel" aria-labelledby="dualsense-title">
    <div className="section-heading"><h2 id="dualsense-title">Controle DualSense</h2><button className="text-button" disabled={busy} onClick={() => onAction('refresh')}>{action === 'refresh' ? 'Verificando…' : 'Atualizar status'}</button></div>
    <p className="intro">Suporte ao controle PlayStation 5 nesta instalação do jogo.</p>
    {!gamePath ? <p className="error-message">Selecione a pasta do jogo para verificar o suporte ao controle.</p> : status && <div className="controller-status" aria-live="polite">
      <strong>{status.installed ? 'Suporte habilitado' : 'Suporte não habilitado'}</strong>
      <span className={status.connected ? 'spectral' : 'amber'}>{status.connected ? `Controle conectado${status.deviceName ? `: ${status.deviceName}` : ''}` : 'Nenhum DualSense detectado'}</span>
      {status.running && <span className="amber">Jogo em execução</span>}
      <p>{status.message}</p>
    </div>}
    <div className="controller-actions"><button className="secondary" disabled={busy || !status || status.installed || status.running} onClick={() => onAction('install')}>{action === 'install' ? 'Habilitando…' : 'Habilitar suporte'}</button><button className="secondary" disabled={busy || !status?.installed || status.running} onClick={() => onAction('remove')}>{action === 'remove' ? 'Removendo…' : 'Remover suporte'}</button></div>
    <details className="controller-mapping"><summary>Controles de teclado padrão</summary><ul>{mappings.map(({ shape, key, action: description }) => <li key={key}><span className={`ds-map-key ${shape ? '' : 'ds-text-key'}`}>{shape ? <FaceIcon shape={shape} label={`Botão ${key}`} /> : <span>{key}</span>}</span><span>{description}</span></li>)}</ul><p className="quiet">A faixa de ícones é externa e aparece durante o jogo em janela. Não substitui as dicas originais. Use o modo de teclado padrão para evitar entrada duplicada.</p><p className="quiet">Gatilhos adaptáveis e resposta tátil não estão implementados.</p></details>
    <button className="primary full-width" disabled={busy || !status?.installed || status.running} onClick={() => onAction('launch')}>{action === 'launch' ? 'Iniciando…' : status?.running ? 'Jogo já está em execução' : 'Jogar com DualSense'}<Icon name="play" /></button>
  </section>;
}
