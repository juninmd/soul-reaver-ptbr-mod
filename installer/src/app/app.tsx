import { useEffect, useRef, useState, type ReactNode } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import MainNav from '../components/main-nav';
import StatusBar from '../components/status-bar';
import WindowTitlebar, { type WindowAction } from '../components/window-titlebar';
import AppDialogs, { type ModalName } from '../dialogs/app-dialogs';
import { errorText, type OperationKind } from '../installer/model';
import { useInstaller } from '../installer/use-installer';
import ComponentsScreen from '../screens/components-screen';
import DiagnosticsScreen from '../screens/diagnostics-screen';
import HomeScreen from '../screens/home-screen';
import ProgressScreen from '../screens/progress-screen';
import RestoreScreen from '../screens/restore-screen';
import type { ScreenProps } from '../screens/screen-props';
import { documentTitle, transitionScreen, type Screen } from './navigation';
import { viewState } from './view-state';

const screens: Record<Screen, (props: ScreenProps) => ReactNode> = {
  home: HomeScreen, components: ComponentsScreen, progress: ProgressScreen, restore: RestoreScreen, diagnostics: DiagnosticsScreen,
};

/** Application shell: window chrome, navigation, the current screen and its dialog. */
export default function App() {
  const installer = useInstaller();
  const [screen, setScreen] = useState<Screen>('home');
  const [modal, setModal] = useState<ModalName | null>(null);
  const [windowError, setWindowError] = useState('');
  const main = useRef<HTMLElement>(null);
  const view = viewState(installer);
  const { busy, mutation } = installer;

  // Each screen announces itself through its heading; the outcome of an operation does too.
  useEffect(() => {
    main.current?.querySelector<HTMLElement>('h1')?.focus({ preventScroll: true });
    document.title = documentTitle(screen);
  }, [screen, view.ended]);

  // Alt+F4 and the taskbar reach the window directly: never close over a write.
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void getCurrentWindow().onCloseRequested(event => {
      if (mutation.current) { event.preventDefault(); setModal('close-busy'); }
    }).then(stop => { if (disposed) stop(); else unlisten = stop; }).catch(err => setWindowError(errorText(err)));
    return () => { disposed = true; unlisten?.(); };
  }, [mutation]);

  async function windowAction(action: WindowAction) {
    if (action === 'close' && mutation.current) { setModal('close-busy'); return; }
    if (!isTauri()) { setWindowError('Os controles da janela estão disponíveis no aplicativo desktop.'); return; }
    try { await getCurrentWindow()[action](); } catch (err) { setWindowError(errorText(err)); }
  }
  const show = (next: Screen) => { if (next !== screen) transitionScreen(() => setScreen(next)); };
  const navigate = (next: Screen) => { if (!busy) show(next); };
  function start(kind: OperationKind) {
    if (busy || !installer.gamePath || (kind === 'install' && !installer.readyToApply)) return;
    // Not a navigation: the operation screen must be in place before the first
    // progress event, so it does not wait for a view transition.
    setModal(null); setScreen('progress'); void installer.run(kind);
  }

  const CurrentScreen = screens[screen];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Ir para o conteúdo</a>
      <WindowTitlebar edition={installer.bundle ? `v${installer.bundle.version}` : 'INSTALADOR'} onAction={action => void windowAction(action)} />
      <MainNav screen={screen} disabled={busy} onNavigate={navigate} onAbout={() => setModal('about')} />
      <main id="main" ref={main} tabIndex={-1} className={`main-content screen-${screen}`}>
        <CurrentScreen installer={installer} view={view} onNavigate={navigate} onOpenModal={setModal} onChangeLocation={() => { if (!busy) setModal('location'); }} />
      </main>
      <StatusBar busy={busy} running={installer.running} />
      {windowError && <div className="window-error" role="alert">{windowError}<button className="text-button" onClick={() => setWindowError('')}>Dispensar</button></div>}
      <AppDialogs modal={modal} installer={installer} view={view} onClose={() => setModal(null)} onStart={start} />
    </div>
  );
}
