import Icon from '../components/icon';
import GameLocation from '../components/game-location';
import NosgothScene from '../components/nosgoth-scene';
import Notices from '../components/notices';
import type { ScreenProps } from './screen-props';

const features = [
  { icon: 'voice', title: 'Nosgoth em português', detail: 'Dublagem, menus e legendas · cobertura parcial' },
  { icon: 'eye', title: 'O clássico, sob uma nova luz', detail: 'Renderização 4K e widescreen opcionais' },
  { icon: 'shield', title: 'Um caminho de volta', detail: 'Verificação de integridade, backup e restauração' },
] as const;

export default function HomeScreen({ installer: i, view, onNavigate, onChangeLocation }: ScreenProps) {
  return <>
    <section className="hero">
      <NosgothScene variant="hero" label="Pilares em ruínas de Nosgoth, um eclipse e um viajante com uma lâmina espectral" />
      <div className="hero-top"><span className="small-rune">✧</span> O LEGADO RENASCE</div>
      <div className="hero-copy reveal">
        <p className="legacy">LEGACY OF KAIN</p>
        <h1 className="wordmark" tabIndex={-1}>SOUL<br /><span>REAVER</span></h1>
        <div className="ornament"><span />◆<span /></div>
        <p className="hero-line">Retorne a Nosgoth.<br />Agora, na sua língua.</p>
        <p className="hero-description">Uma nova voz para uma história eterna.<br />Prepare sua jornada em português brasileiro.</p>
      </div>
      <div className="art-caption"><span /> REINO ESPECTRAL <span className="caption-line" /> NOSGOTH</div>
    </section>
    <section className="home-panel reveal">
      <div className="eyebrow"><span className="tiny-line" /> SEU PRÓXIMO CAPÍTULO</div>
      <h2>O destino espera<br />por você.</h2>
      <p className="intro">Escolha como revisitar o mundo de Raziel.<br />Nós cuidamos dos preparativos.</p>
      <ul className="journey-features">
        {features.map(feature => <li key={feature.title}><Icon name={feature.icon} /><div><strong>{feature.title}</strong><span>{feature.detail}</span></div></li>)}
      </ul>
      <GameLocation installer={i} onChange={onChangeLocation} />
      <Notices installer={i} />
      {view.unverifiedRecovery && <button className="text-button recovery-link" disabled={i.busy} onClick={() => onNavigate('restore')}>Ver opções de recuperação<Icon name="arrow" /></button>}
      <button className="primary" disabled={i.busy} onClick={() => onNavigate('components')}>{i.loading ? 'Preparando sua jornada…' : 'Preparar instalação'}<Icon name="arrow" /></button>
      <p className="quiet centered">Você revisa os componentes antes de começar.</p>
    </section>
  </>;
}
