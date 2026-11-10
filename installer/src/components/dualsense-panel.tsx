import Icon from './icon';
import type { ControllerAction, ControllerStatus } from '../installer/model';

type FaceShape = 'triangle' | 'circle' | 'cross' | 'square';

interface Props {
  gamePath: string;
  disabled: boolean;
  status: ControllerStatus | null;
  /** The controller action in flight, if any. */
  action: ControllerAction | null;
  onAction: (action: ControllerAction) => void;
  onOpenLogs?: () => void;
}

const mappings: { shape?: FaceShape; key: string; action: string }[] = [
  { key: 'Analógico / direcional', action: 'Movimentar (padrão: setas)' },
  { shape: 'triangle', key: '△', action: 'Mirar / agarrar (F)' },
  { shape: 'cross', key: '✕', action: 'Pular / nadar (X)' },
  { shape: 'square', key: '□', action: 'Atacar / interagir (A)' },
  { shape: 'circle', key: '○', action: 'Absorver almas (D)' },
  { key: 'L1', action: 'Focar / andar devagar (S)' },
  { key: 'R1', action: 'Agachar (C)' },
  { key: 'Analógico direito', action: 'Olhar para esquerda / direita' },
  { key: 'L2 / R2', action: 'Sem ação atribuída' },
  { key: 'Create', action: 'Menu de glifos / confirmar (Enter)' },
  { key: 'Options', action: 'Pausar / voltar (Esc)' },
];

function FaceIcon({ shape, label }: { shape: FaceShape; label: string }) {
  const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 2.4, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <svg className={`ds-face-icon ds-${shape}`} viewBox="0 0 24 24" role="img" aria-label={label}>
      {shape === 'triangle' && <path {...stroke} d="M12 4 20 19H4L12 4Z" />}
      {shape === 'circle' && <circle {...stroke} cx="12" cy="12" r="7.5" />}
      {shape === 'cross' && <path {...stroke} d="m7 7 10 10M17 7 7 17" />}
      {shape === 'square' && <rect {...stroke} x="5" y="5" width="14" height="14" rx="1.5" />}
    </svg>
  );
}

export default function DualSensePanel({ gamePath, disabled, status, action, onAction, onOpenLogs }: Props) {
  const blocked = disabled || !gamePath;
  const running = status?.running === true;
  return (
    <section className="controller-panel" aria-labelledby="dualsense-title">
      <div className="section-heading">
        <h2 id="dualsense-title">Controle DualSense</h2>
        <div className="dualsense-heading-actions">
          <button className="text-button" disabled={blocked} onClick={() => onAction('refresh')}>{action === 'refresh' ? 'Verificando…' : 'Atualizar status'}</button>
          {onOpenLogs && <button className="text-button" onClick={onOpenLogs}>Abrir pasta de logs</button>}
        </div>
      </div>
      <p className="intro">Suporte ao controle PlayStation 5 nesta instalação do jogo.</p>
      {!gamePath
        ? <p className="notice warning"><Icon name="alert" /><span>Selecione a pasta do jogo para verificar o suporte ao controle.</span></p>
        : status && (
          <div className="controller-status" aria-live="polite">
            <strong>{status.installed ? 'Suporte habilitado' : 'Suporte não habilitado'}</strong>
            <span className={status.connected ? 'spectral' : 'amber'}>{status.connected ? `Controle conectado${status.deviceName ? `: ${status.deviceName}` : ''}` : 'Nenhum DualSense detectado'}</span>
            {running && <span className="amber">Jogo em execução</span>}
            <p>{status.message}</p>
          </div>
        )}
      <div className="controller-actions">
        <button className="secondary" disabled={blocked || !status || status.installed || running} onClick={() => onAction('install')}>{action === 'install' ? 'Habilitando…' : 'Habilitar suporte'}</button>
        <button className="secondary" disabled={blocked || !status?.installed || running} onClick={() => onAction('remove')}>{action === 'remove' ? 'Removendo…' : 'Remover suporte'}</button>
      </div>
      <details className="controller-mapping">
        <summary>Controles de teclado padrão</summary>
        <ul>
          {mappings.map(({ shape, key, action: description }) => (
            <li key={key}>
              <span className={`ds-map-key ${shape ? '' : 'ds-text-key'}`}>{shape ? <FaceIcon shape={shape} label={`Botão ${key}`} /> : <span>{key}</span>}</span>
              <span>{description}</span>
            </li>
          ))}
        </ul>
        <p className="quiet">A faixa de ícones é externa e aparece durante o jogo em janela. Não substitui as dicas originais. Use o modo de teclado padrão para evitar entrada duplicada.</p>
        <p className="quiet">Gatilhos adaptáveis e resposta tátil não estão implementados.</p>
      </details>
      <button className="primary full-width" disabled={blocked || !status?.installed || running} onClick={() => onAction('launch')}>
        {action === 'launch' ? 'Iniciando…' : running ? 'Jogo já está em execução' : 'Jogar com DualSense'}<Icon name="play" />
      </button>
    </section>
  );
}
