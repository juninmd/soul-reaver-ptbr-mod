import Icon from '../components/icon';
import GameLocation from '../components/game-location';
import NosgothScene from '../components/nosgoth-scene';
import Notices from '../components/notices';
import { componentsFor } from '../installer/model';
import type { Installer } from '../installer/use-installer';
import type { ScreenProps } from './screen-props';

/** Why the review button is disabled, most actionable reason first. */
function blockingReason(i: Installer, selected: number): string {
  if (!i.gameInfo) return 'Selecione uma instalação compatível.';
  if (!i.gameClosed) return 'Feche o jogo para continuar.';
  if (!i.diagnostics) return 'Atualize o diagnóstico antes de instalar.';
  if (!selected) return 'Selecione pelo menos um componente.';
  if (i.gameInfo.status === 'preparing') return 'Uma operação anterior ficou incompleta. Consulte a restauração.';
  return 'Verifique o pacote e a compatibilidade no diagnóstico.';
}

export default function ComponentsScreen({ installer: i, onNavigate, onOpenModal, onChangeLocation }: ScreenProps) {
  const modules = componentsFor(i.bundle);
  const selected = modules.filter(item => i.selectedOptions[item.id]).length;
  return <>
    <section className="workspace reveal">
      <div className="eyebrow">PREPARE SUA JORNADA</div>
      <h1 tabIndex={-1}>Escolha o que despertar.</h1>
      <p className="intro">A essência do clássico. Os detalhes que você escolhe.</p>
      <Notices installer={i} />
      <div className="section-heading">
        <h2>Componentes do pacote</h2>
        <div className="heading-actions">
          <button type="button" className="text-button" disabled={i.busy || !i.selectedOptions.graphics} onClick={() => onOpenModal('render')}><Icon name="settings" />Render GPU · {i.display?.recommended || '…'}</button>
          <span className="counter">{selected} selecionados</span>
        </div>
      </div>
      <div className="module-list">
        {modules.map(item => {
          // Widescreen only exists on top of the wrapper.
          const disabled = i.busy || !item.available || (item.id === 'widescreen' && !i.selectedOptions.graphics);
          const tag = !item.available ? 'INDISPONÍVEL' : item.experimental ? 'EXPERIMENTAL' : item.tag;
          return (
            <label key={item.id} className={`module ${item.available ? '' : 'unavailable'}`}>
              <Icon name={item.icon} />
              <div className="module-text"><strong>{item.title}</strong><span>{item.description}</span></div>
              <span className={`module-tag ${item.experimental ? 'amber' : ''}`}>{tag}</span>
              <input type="checkbox" checked={i.selectedOptions[item.id]} disabled={disabled} aria-label={item.title}
                onChange={event => i.setOptions(current => ({ ...current, [item.id]: event.target.checked }))} />
            </label>
          );
        })}
      </div>
      {i.bundle && <p className="coverage-note"><Icon name="voice" /> O catálogo não comprova cobertura da campanha. Falas não substituídas mantêm o áudio original.</p>}
      {i.bundle?.experimental.length ? <p className="quiet experimental-note">Componentes experimentais declarados pelo pacote: {i.bundle.experimental.join(', ')}. O resultado no jogo ainda depende de validação.</p> : null}
    </section>
    <aside className="summary-panel">
      <NosgothScene variant="aside" />
      <div className="aside-content reveal">
        <Icon name="rune" className="large-rune" />
        <div className="eyebrow">SEU RITUAL DE INSTALAÇÃO</div>
        <h2>O próximo passo<br />é seu.</h2>
        <GameLocation installer={i} onChange={onChangeLocation} />
        <div className="security-note"><Icon name="shield" /><p>Os arquivos são verificados antes de aplicar. O instalador mantém backup e preserva seus saves.</p></div>
        {!i.readyToApply && !i.busy && <p className="quiet install-requirements">{blockingReason(i, selected)}</p>}
        <button className="primary" disabled={i.busy || !i.readyToApply} onClick={() => onOpenModal('review')}>Revisar instalação<Icon name="arrow" /></button>
        <button className="secondary full-width" disabled={i.busy} onClick={() => { onNavigate('diagnostics'); void i.refresh(); }}>Ver diagnóstico</button>
      </div>
    </aside>
  </>;
}
