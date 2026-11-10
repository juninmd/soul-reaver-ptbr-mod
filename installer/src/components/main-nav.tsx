import Icon from './icon';
import { navigation, type Screen } from '../app/navigation';

interface Props { screen: Screen; disabled: boolean; onNavigate: (screen: Screen) => void; onAbout: () => void }

export default function MainNav({ screen, disabled, onNavigate, onAbout }: Props) {
  // The operation screen belongs to the components journey.
  const current = screen === 'progress' ? 'components' : screen;
  return (
    <nav className="main-nav" aria-label="Navegação principal">
      <div className="nav-links">
        {navigation.map(({ screen: key, label }) => (
          <button key={key} aria-current={current === key ? 'page' : undefined} disabled={disabled} onClick={() => onNavigate(key)}>{label}</button>
        ))}
      </div>
      <button className="about-button" aria-label="Sobre o projeto" onClick={onAbout}>UM CLÁSSICO. UMA NOVA VOZ. <Icon name="rune" /></button>
    </nav>
  );
}
