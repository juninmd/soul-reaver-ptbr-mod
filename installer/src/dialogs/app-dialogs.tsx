import { useState, type ReactNode } from 'react';
import Icon from '../components/icon';
import Modal from '../components/modal';
import { componentsFor, resolutionChoices, RENDER_FPS_OPTIONS, type ControllerAction, type OperationKind } from '../installer/model';
import type { Installer } from '../installer/use-installer';
import type { ViewState } from '../app/view-state';

export type ControllerModal = `controller-${Exclude<ControllerAction, 'refresh'>}`;
export type ModalName = 'location' | 'render' | 'review' | 'restore' | 'repair' | 'cancel' | 'close-busy' | 'about' | ControllerModal;

interface Props {
  modal: ModalName | null;
  installer: Installer;
  view: ViewState;
  onClose: () => void;
  onStart: (kind: OperationKind) => void;
}
type BodyProps = Omit<Props, 'modal'>;

function Frame({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return <><div className="eyebrow">{eyebrow}</div><h2 id="dialog-title">{title}</h2>{children}</>;
}

function Destination({ path }: { path: string }) {
  return <div className="review-destination"><Icon name="folder" /><span>{path}</span></div>;
}

function LocationDialog({ installer: i, onClose }: BodyProps) {
  const [path, setPath] = useState(i.gamePath);
  const verify = () => { onClose(); void i.inspect(path); };
  return (
    <Frame eyebrow="LOCALIZE SEU LEGADO" title="Sua cópia de Soul Reaver.">
      <p>Selecione a pasta da edição Steam Classic. A verificação consulta a integridade sem instalar componentes.</p>
      <label className="field-label" htmlFor="game-path">Pasta do jogo</label>
      <input id="game-path" value={path} spellCheck={false} placeholder="D:\Jogos\Legacy of Kain Soul Reaver"
        onChange={event => setPath(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && path.trim()) verify(); }} />
      <div className="dialog-actions">
        <button className="secondary" disabled={i.busy} onClick={() => { onClose(); void i.chooseFolder(); }}><Icon name="folder" />Procurar…</button>
        <button className="primary" disabled={i.busy || !path.trim()} onClick={verify}>Verificar<Icon name="check" /></button>
      </div>
    </Frame>
  );
}

function RenderDialog({ installer: i, onClose }: BodyProps) {
  const set = <K extends keyof typeof i.render>(key: K, value: (typeof i.render)[K]) => i.setRender(current => ({ ...current, [key]: value }));
  return (
    <Frame eyebrow="RENDERIZAÇÃO POR GPU" title="Ajuste a imagem.">
      <p>{i.display?.message || 'Consultando monitor e adaptador…'}</p>
      <div className="render-settings">
        <label className="render-row"><span>Resolução interna</span>
          <select value={i.render.resolution} onChange={event => set('resolution', event.target.value)}>
            {resolutionChoices(i.display, i.render.resolution).map(choice => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
          </select>
        </label>
        <label className="render-row"><span>Sincronização vertical (VSync)</span><input type="checkbox" checked={i.render.vsync} onChange={event => set('vsync', event.target.checked)} /></label>
        <label className="render-row"><span>Limite de quadros</span>
          <select value={i.render.fpsLimit} onChange={event => set('fpsLimit', Number(event.target.value))}>
            {RENDER_FPS_OPTIONS.map(value => <option key={value} value={value}>{value === 0 ? 'Ilimitado' : `${value} FPS`}</option>)}
          </select>
        </label>
        <label className="render-row"><span>Janela sempre no topo</span><input type="checkbox" checked={i.render.alwaysOnTop} onChange={event => set('alwaysOnTop', event.target.checked)} /></label>
      </div>
      <p className="quiet">Gravado no dgVoodoo.conf durante a instalação, conforme o monitor e o adaptador detectados. Render estável e escala suave ainda exigem validação em jogo.</p>
      <div className="dialog-actions">
        <button className="secondary" onClick={onClose}>Voltar</button>
        <button className="primary" onClick={onClose}>Salvar ajustes<Icon name="check" /></button>
      </div>
    </Frame>
  );
}

function ReviewDialog({ installer: i, onClose, onStart }: BodyProps) {
  const chosen = componentsFor(i.bundle).filter(item => i.selectedOptions[item.id]);
  return (
    <Frame eyebrow="ANTES DE CRUZAR O PORTAL" title="Tudo pronto para começar?">
      <p>Os componentes abaixo serão aplicados à instalação selecionada.</p>
      <Destination path={i.gamePath} />
      <ul className="review-list">
        {chosen.map(item => <li key={item.id}><Icon name="check" />{item.title}<span>{item.experimental ? 'EXPERIMENTAL' : item.tag}</span></li>)}
      </ul>
      <div className="security-note"><Icon name="shield" /><p>Os arquivos serão verificados e os originais terão backup. A cobertura de voz é parcial.{chosen.some(item => item.experimental) && ' Sua seleção inclui componentes experimentais ainda sem validação no jogo.'}</p></div>
      <div className="dialog-actions">
        <button className="secondary" onClick={onClose}>Revisar escolhas</button>
        <button className="primary" disabled={i.busy || !i.readyToApply} onClick={() => onStart('install')}>Instalar componentes<Icon name="arrow" /></button>
      </div>
    </Frame>
  );
}

function RecoveryDialog({ kind, installer: i, view, onClose, onStart }: BodyProps & { kind: 'restore' | 'repair' }) {
  const restore = kind === 'restore';
  return (
    <Frame eyebrow={restore ? 'RETORNO À ORIGEM' : 'PRESERVE SEU LEGADO'} title={restore ? 'Restaurar os arquivos originais?' : 'Reparar os componentes instalados?'}>
      <p>{restore
        ? 'Todos os componentes gerenciados, incluindo o suporte DualSense, serão restaurados a partir dos registros e backups. Arquivos alterados posteriormente não serão sobrescritos sem verificação.'
        : 'O instalador verificará e reaplicará os componentes gerenciados conforme seus registros.'}</p>
      {view.unverifiedRecovery && <p className="notice warning"><Icon name="alert" /><span>A inspeção não foi concluída. A restauração só poderá recuperar componentes com registros e backups válidos; arquivos conflitantes serão recusados.</span></p>}
      <Destination path={i.gamePath} />
      <div className="dialog-actions">
        <button className="secondary" onClick={onClose}>Voltar</button>
        <button className="primary" disabled={i.busy} onClick={() => onStart(kind)}>{restore ? 'Restaurar originais' : 'Reparar agora'}<Icon name="restore" /></button>
      </div>
    </Frame>
  );
}

function InterruptDialog({ closing, installer: i, onClose }: BodyProps & { closing: boolean }) {
  return (
    <Frame eyebrow="PAUSA NA JORNADA" title={closing ? 'Aguarde uma conclusão segura.' : 'Interromper a operação?'}>
      <p>{i.running
        ? 'A parada aguarda uma unidade segura de trabalho. Componentes já aplicados permanecem instalados e podem ser restaurados depois.'
        : 'Uma operação ou verificação final ainda está em andamento. Aguarde sua conclusão antes de fechar a janela.'}</p>
      <div className="dialog-actions">
        <button className="secondary" onClick={onClose}>Voltar à operação</button>
        {i.running && <button className="primary" disabled={i.stopping || i.controlPending} onClick={() => { onClose(); void i.cancel(); }}>Parar com segurança<Icon name="pause" /></button>}
      </div>
    </Frame>
  );
}

const controllerCopy: Record<Exclude<ControllerAction, 'refresh'>, { title: string; detail: string; confirm: string }> = {
  install: { title: 'Habilitar o suporte DualSense?', detail: 'O acompanhante será instalado com os registros de propriedade e backup. O jogo não será aberto.', confirm: 'Habilitar suporte' },
  remove: { title: 'Remover o suporte DualSense?', detail: 'O acompanhante gerenciado será removido, após a verificação de propriedade.', confirm: 'Remover suporte' },
  launch: { title: 'Abrir Soul Reaver com DualSense?', detail: 'Esta ação abrirá o jogo. O acompanhante usará o mapeamento de teclado padrão e exibirá a faixa externa de ícones.', confirm: 'Abrir jogo com DualSense' },
};

function ControllerDialog({ action, installer: i, onClose }: BodyProps & { action: Exclude<ControllerAction, 'refresh'> }) {
  const copy = controllerCopy[action];
  return (
    <Frame eyebrow="CONTROLE NAS SUAS MÃOS" title={copy.title}>
      <p>{copy.detail}</p>
      <Destination path={i.gamePath} />
      <div className="dialog-actions">
        <button className="secondary" onClick={onClose}>Voltar</button>
        <button className="primary" disabled={i.busy} onClick={() => { onClose(); void i.runController(action); }}>{copy.confirm}<Icon name={action === 'launch' ? 'play' : 'check'} /></button>
      </div>
    </Frame>
  );
}

function AboutDialog({ onClose }: BodyProps) {
  return (
    <Frame eyebrow="UMA NOVA VOZ PARA NOSGOTH" title="O legado renasce.">
      <p>Instalador da comunidade para Legacy of Kain: Soul Reaver · Steam Classic. Vozes em português brasileiro, localização e melhorias opcionais.</p>
      <p>A cobertura da campanha é parcial. Aplicação dos arquivos, qualidade dos assets e funcionamento no jogo são verificações diferentes. Consulte os componentes experimentais e o diagnóstico.</p>
      <p>Projeto da comunidade, sem afiliação oficial.</p>
      <button className="primary full-width" onClick={onClose}>Voltar à jornada<Icon name="arrow" /></button>
    </Frame>
  );
}

function body(modal: ModalName, props: BodyProps) {
  switch (modal) {
    case 'location': return <LocationDialog {...props} />;
    case 'render': return <RenderDialog {...props} />;
    case 'review': return <ReviewDialog {...props} />;
    case 'restore': case 'repair': return <RecoveryDialog kind={modal} {...props} />;
    case 'cancel': case 'close-busy': return <InterruptDialog closing={modal === 'close-busy'} {...props} />;
    case 'about': return <AboutDialog {...props} />;
    default: return <ControllerDialog action={modal.slice('controller-'.length) as Exclude<ControllerAction, 'refresh'>} {...props} />;
  }
}

/** The single dialog of the application; `modal` selects what it asks. */
export default function AppDialogs({ modal, ...props }: Props) {
  // The last dialog stays rendered while the exit transition runs; every
  // opening remounts the body so each dialog starts from fresh state.
  const [previous, setPrevious] = useState<ModalName | null>(null);
  const [shown, setShown] = useState<{ name: ModalName; opened: number } | null>(null);
  if (modal !== previous) {
    setPrevious(modal);
    if (modal) setShown({ name: modal, opened: (shown?.opened ?? 0) + 1 });
  }
  return <Modal open={!!modal} onClose={props.onClose}>{shown && <div key={shown.opened} className="dialog-body">{body(shown.name, props)}</div>}</Modal>;
}
