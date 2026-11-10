import Icon from '../components/icon';
import NosgothScene from '../components/nosgoth-scene';
import Notices from '../components/notices';
import { stageLabel, stagePercent, type OperationKind } from '../installer/model';
import type { ScreenProps } from './screen-props';

const headings: Record<'running' | 'succeeded', Record<OperationKind, string>> = {
  running: { install: 'Nosgoth desperta.', repair: 'Preserve seu legado.', restore: 'O tempo retorna.' },
  succeeded: { install: 'Componentes aplicados.', repair: 'Reparo concluído.', restore: 'De volta à origem.' },
};

export default function ProgressScreen({ installer: i, view, onNavigate, onOpenModal }: ScreenProps) {
  const { succeeded, ended, recovery } = view;
  const kind = i.operation?.kind ?? 'install';
  const installed = succeeded && kind === 'install';
  const percent = stagePercent(i.progress);
  const stage = i.progress ? stageLabel(i.progress.stage) : null;
  const eyebrow = i.running ? i.paused ? 'UM INSTANTE ENTRE OS REINOS' : 'ENTRE DOIS REINOS' : succeeded ? 'RITUAL CONCLUÍDO' : 'A JORNADA PEDE ATENÇÃO';
  const heading = i.running ? headings.running[kind]
    : succeeded ? headings.succeeded[kind]
      : i.operation?.status === 'cancelled' ? 'Jornada interrompida.' : 'A operação não foi concluída.';
  const outcome = !succeeded ? 'A interrupção não desfaz componentes já aplicados. Consulte o diagnóstico e use a restauração quando necessário.'
    : kind === 'restore' ? 'Restauração concluída pelo instalador. Confira os componentes no diagnóstico.'
      : 'A aplicação dos arquivos foi concluída. A cobertura é parcial e o funcionamento no jogo exige validação própria.';
  const still = !i.running || i.paused;
  return <>
    <section className="progress-art">
      <NosgothScene variant="progress" still={still} />
      <div className="progress-quote reveal"><span>LEGACY OF KAIN</span><p>Há destinos<br />que merecem<br />uma nova voz.</p><div className="ornament"><span />◆<span /></div></div>
    </section>
    <section className="progress-panel reveal">
      <div className="eyebrow">{eyebrow}</div>
      <h1 tabIndex={-1}>{heading}</h1>
      <p className="intro" role="status">{i.message}</p>
      <div className={`ritual-seal ${still ? 'still' : ''} ${succeeded ? 'complete' : ''}`}><div /><Icon name={succeeded ? 'check' : 'rune'} /></div>
      {i.running && <>
        <div className="progress-caption"><span>{stage ?? 'Aguardando o início da operação'}</span><strong>{percent ?? '—'}{percent !== null && <small>%</small>}</strong></div>
        {percent === null
          ? <progress max="100" aria-label="Aguardando progresso da etapa" />
          : <progress max="100" value={percent} aria-label={`Progresso da etapa: ${stage ?? 'preparação'}`} />}
        <p className="quiet progress-scope">Percentual da etapa atual. A conclusão da instalação é confirmada ao final de todas as etapas.</p>
        {i.paused && <p className="spectral pause-message">Pausa solicitada entre unidades de trabalho.</p>}
      </>}
      {ended && <div className={`operation-outcome ${succeeded ? 'success' : 'attention'}`}><Icon name={succeeded ? 'shield' : 'restore'} /><p>{outcome}</p></div>}
      <Notices installer={i} />
      <div className="progress-actions">
        {i.running ? <>
          <button className="secondary" disabled={i.stopping || i.controlPending} onClick={() => void i.togglePause()}><Icon name={i.paused ? 'play' : 'pause'} />{i.paused ? 'Retomar' : 'Pausar'}</button>
          <button className="text-button" disabled={i.stopping || i.controlPending} onClick={() => onOpenModal('cancel')}>{i.stopping ? 'Parando com segurança…' : 'Parar operação'}</button>
        </> : <>
          {installed && <button className="primary" disabled={!i.canLaunchGame} onClick={() => void i.launchGame()}>{i.launching ? 'Abrindo…' : !i.gameClosed ? 'Jogo já está aberto' : 'Abrir jogo'}<Icon name="play" /></button>}
          <button className={installed ? 'secondary' : 'primary'} disabled={i.busy} onClick={() => onNavigate('diagnostics')}>Ver diagnóstico<Icon name="arrow" /></button>
          <button className="secondary" disabled={i.busy} onClick={() => onNavigate(recovery ? 'restore' : 'home')}>{recovery ? 'Ver restauração' : 'Voltar à jornada'}</button>
        </>}
      </div>
      <p className="quiet progress-footnote"><Icon name="shield" />{i.loading && ended ? 'Atualizando o estado dos arquivos…' : 'Etapas informadas pelo instalador. Nenhum jogo é aberto automaticamente.'}</p>
    </section>
  </>;
}
