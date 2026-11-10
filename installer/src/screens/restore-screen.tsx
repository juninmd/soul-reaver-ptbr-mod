import Icon from '../components/icon';
import NosgothScene from '../components/nosgoth-scene';
import Notices from '../components/notices';
import type { ScreenProps } from './screen-props';

const steps = [
  { title: 'Conferir antes de restaurar', detail: 'Verificar a integridade dos arquivos e a propriedade das alterações.' },
  { title: 'Devolver os arquivos originais', detail: 'Recuperar os arquivos gerenciados pelo mod a partir do backup.' },
  { title: 'Preservar a sua história', detail: 'Manter saves e recusar a sobrescrita de arquivos alterados posteriormente.' },
];

export default function RestoreScreen({ installer: i, view, onOpenModal }: ScreenProps) {
  const { partial, unverifiedRecovery, recovery } = view;
  const state = i.anyInstalled ? 'Componentes do mod detectados'
    : unverifiedRecovery ? 'Verificação incompleta'
      : partial ? 'Confira uma operação interrompida'
        : i.gameInfo ? 'Nenhum componente detectado' : 'Selecione sua cópia do jogo';
  const writable = !i.busy && i.gameClosed && i.listenersReady;
  return <>
    <section className="workspace restore-workspace reveal">
      <div className="eyebrow">TODO CAMINHO TEM UMA VOLTA</div>
      <h1 tabIndex={-1}>Preserve seu legado.</h1>
      <p className="intro">Consulte a instalação e o caminho de volta ao original.</p>
      <div className={`restore-state ${i.anyInstalled ? 'active' : ''}`}><Icon name="shield" /><div><h2>{state}</h2><p>{i.gameInfo?.message || 'A integridade e a propriedade dos arquivos são conferidas antes de restaurar.'}</p></div></div>
      <h2 className="restore-title">Como funciona a restauração</h2>
      <ol className="restore-steps">
        {steps.map(step => <li key={step.title}><span aria-hidden="true">◆</span><div><strong>{step.title}</strong><p>{step.detail}</p></div></li>)}
      </ol>
      <Notices installer={i} />
      <div className="restore-bottom">
        <button className="secondary" disabled={i.busy || !i.gamePath} onClick={() => void i.refresh()}>Atualizar diagnóstico</button>
        <button className="secondary" disabled={!writable || !i.gameInfo || !i.anyInstalled} onClick={() => onOpenModal('repair')}>Reparar componentes</button>
        <button className="primary" disabled={!writable || !i.gamePath || !recovery} onClick={() => onOpenModal('restore')}><Icon name="restore" />Restaurar tudo</button>
      </div>
      {!i.gameClosed && <p className="notice warning"><Icon name="alert" /><span>Feche o jogo antes de reparar ou restaurar.</span></p>}
    </section>
    <aside className="restore-art">
      <NosgothScene variant="aside" />
      <div className="restore-art-copy reveal"><Icon name="rune" /><p>O passado<br />não se perde.</p><span>ELE FAZ PARTE DO LEGADO.</span></div>
    </aside>
  </>;
}
