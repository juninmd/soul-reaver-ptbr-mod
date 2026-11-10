import { useEffect, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { ipc } from './ipc';
import {
  effectiveOptions, errorText, hasInstallation, initialOptions, initialRender,
  type ApplyOptions, type BundleInfo, type ControllerAction, type ControllerStatus, type Diagnostics,
  type DisplayProfile, type GameInfo, type Operation, type OperationKind, type OperationProgress, type RenderSettings,
} from './model';

/**
 * State and actions of the installer.
 *
 * Three guards serialize the work, as refs because they must be read in the
 * same tick they are set:
 * - `lock`: a query or an operation is running; nothing else may start.
 * - `mutation`: files may be written; closing the window is intercepted.
 * - `controlLock`: a pause/resume/cancel request is in flight.
 */
export function useInstaller() {
  const [gamePath, setGamePath] = useState('');
  const [gameInfo, setGameInfo] = useState<GameInfo | null>(null);
  const [bundle, setBundle] = useState<BundleInfo | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [controller, setController] = useState<ControllerStatus | null>(null);
  const [options, setOptions] = useState<ApplyOptions>(initialOptions);
  const [render, setRender] = useState<RenderSettings>(initialRender);
  const [display, setDisplay] = useState<DisplayProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [listenersReady, setListenersReady] = useState(false);
  const [controllerAction, setControllerAction] = useState<ControllerAction | null>(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [operation, setOperation] = useState<Operation | null>(null);
  const [progress, setProgress] = useState<OperationProgress | null>(null);
  const [message, setMessage] = useState('');
  const [paused, setPaused] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [controlPending, setControlPending] = useState(false);
  const lock = useRef(true);
  const mutation = useRef(false);
  const controlLock = useRef(false);
  const activeOperation = useRef(false);

  // Read-only refresh after every outcome, including partial failure/cancellation.
  // The backend inspects the files once and derives the three views from it.
  async function readGame(path: string, clear: boolean) {
    if (clear) { setGamePath(path); setGameInfo(null); setDiagnostics(null); setController(null); }
    const report = await ipc.inspectInstallation(path);
    setGameInfo(report.game);
    setDiagnostics(report.diagnostics);
    setController(report.controller);
    if (!report.game) throw new Error(report.error ?? 'Não foi possível inspecionar a instalação.');
    if (report.warnings.length) setNotice(`Algumas verificações não puderam ser concluídas: ${[...new Set(report.warnings)].join(' · ')}`);
  }

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    async function initialize() {
      if (!isTauri()) {
        setError('Abra o aplicativo desktop para localizar o jogo e gerenciar a instalação.');
        setLoading(false); lock.current = false;
        return;
      }
      try {
        const stop = await listen<OperationProgress>('progress', event => {
          if (disposed || !activeOperation.current) return;
          setProgress(event.payload); setMessage(event.payload.message);
        });
        if (disposed) { stop(); return; }
        unlisten = stop;
        setListenersReady(true);
        // A missing/invalid package must not hide a detected installation or recovery.
        const [detected, foundBundle, profile] = await Promise.allSettled([ipc.detectGame(), ipc.bundleInfo(), ipc.displayProfile()]);
        if (disposed) return;
        if (foundBundle.status === 'fulfilled') setBundle(foundBundle.value);
        else setBundleError(errorText(foundBundle.reason));
        if (profile.status === 'fulfilled') setDisplay(profile.value);
        if (detected.status === 'fulfilled' && detected.value) await readGame(detected.value, true);
        else if (detected.status === 'rejected') setError(errorText(detected.reason));
      } catch (err) {
        if (!disposed) setError(errorText(err));
      } finally {
        if (!disposed) { setLoading(false); lock.current = false; }
      }
    }
    void initialize();
    return () => { disposed = true; unlisten?.(); };
  }, []);

  /** Runs a read-only task under the shared lock, surfacing its failure as the page error. */
  async function query(task: () => Promise<void>) {
    if (lock.current || controlLock.current) return;
    lock.current = true; setLoading(true); setError(null); setNotice('');
    try { await task(); } catch (err) { setError(errorText(err)); }
    finally { setLoading(false); lock.current = false; }
  }
  async function inspect(path: string) {
    if (path.trim()) await query(() => readGame(path.trim(), true));
  }
  async function chooseFolder() {
    await query(async () => {
      const selected = await open({ directory: true, multiple: false, title: 'Selecione a pasta de instalação do Soul Reaver' });
      if (typeof selected === 'string') await readGame(selected, true);
    });
  }
  // Verifies the package on disk again; the backend reuses that description
  // in every diagnosis until the next explicit verification.
  async function verifyBundle() {
    setBundleError(null); setBundle(null);
    try { setBundle(await ipc.bundleInfo()); }
    catch (err) { setBundleError(errorText(err)); }
  }
  const reloadBundle = () => query(verifyBundle);
  /** The user asked for the current state: package and installation are both read from disk. */
  async function refresh() {
    if (gamePath) await query(async () => { await verifyBundle(); await readGame(gamePath, true); });
  }

  const selectedOptions = effectiveOptions(options, bundle);
  const readyToApply = !!gameInfo && ['original', 'installed'].includes(gameInfo.status) && !!bundle && listenersReady
    && diagnostics?.exeSupported === true && diagnostics.gameClosed && Object.values(selectedOptions).some(Boolean);
  const anyInstalled = hasInstallation(gameInfo, controller);
  const running = operation?.status === 'running';
  const busy = loading || running || controlPending || launching;
  const gameClosed = diagnostics?.gameClosed !== false && controller?.running !== true;
  const canLaunchGame = !busy && !!gameInfo && operation?.kind === 'install' && operation.status === 'succeeded' && operation.path === gamePath && gameClosed;

  async function launchGame() {
    if (lock.current || controlLock.current || !canLaunchGame || !operation) return;
    const path = operation.path;
    lock.current = true; mutation.current = true;
    setLaunching(true); setError(null); setNotice('');
    try {
      await ipc.launchGame(path);
      setNotice('Jogo aberto.');
      try { await readGame(path, false); }
      catch (err) { setNotice(`Jogo aberto. Não foi possível atualizar o diagnóstico: ${errorText(err)}`); }
    } catch (err) { setError(errorText(err)); }
    finally { setLaunching(false); lock.current = false; mutation.current = false; }
  }

  async function run(kind: OperationKind): Promise<boolean> {
    if (lock.current || controlLock.current || !gamePath || !listenersReady || (kind === 'install' && !readyToApply)) return false;
    lock.current = true; mutation.current = true; activeOperation.current = true;
    const path = gamePath;
    setOperation({ kind, path, status: 'running' }); setError(null); setNotice('');
    setProgress(null); setMessage('Preparando operação…'); setPaused(false); setStopping(false);
    try {
      setGameInfo(await ipc.runOperation(kind, path, selectedOptions, render));
      setOperation({ kind, path, status: 'succeeded' });
      setMessage(kind === 'restore' ? 'Restauração concluída.' : kind === 'repair' ? 'Reparo concluído.' : 'Componentes aplicados. Consulte a cobertura no diagnóstico.');
    } catch (err) {
      const text = errorText(err);
      const cancelled = text.toLowerCase().includes('cancelada');
      setOperation({ kind, path, status: cancelled ? 'cancelled' : 'failed' });
      setError(cancelled ? null : text);
      setMessage(cancelled ? 'Operação interrompida entre unidades seguras. Confira o estado dos componentes.' : 'A operação não foi concluída. Alguns componentes podem ter sido aplicados.');
    } finally {
      activeOperation.current = false;
      // Keep the navigation/close guard until the final inspection has settled.
      setLoading(true);
      try { await readGame(path, false); }
      catch (err) { setNotice(`Não foi possível atualizar o estado após a operação: ${errorText(err)}`); }
      setLoading(false); setPaused(false); setStopping(false);
      lock.current = false; mutation.current = false;
    }
    return true;
  }

  /** Sends one pause/resume/cancel request at a time while an operation is active. */
  async function control(request: () => Promise<void>, onFailure?: () => void) {
    if (!activeOperation.current || stopping || controlLock.current) return;
    controlLock.current = true; setControlPending(true);
    try { await request(); }
    catch (err) { setNotice(errorText(err)); onFailure?.(); }
    finally { controlLock.current = false; setControlPending(false); }
  }
  const togglePause = () => control(async () => {
    await (paused ? ipc.resumeOperation() : ipc.pauseOperation());
    if (activeOperation.current) setPaused(!paused);
  });
  const cancel = () => control(async () => {
    setStopping(true);
    await ipc.cancelOperation();
    if (activeOperation.current) { setPaused(false); setMessage('Parada solicitada; aguardando a unidade segura em andamento…'); }
  }, () => setStopping(false));

  async function runController(kind: ControllerAction) {
    if (lock.current || controlLock.current || !gamePath) return;
    lock.current = true; mutation.current = kind !== 'refresh'; setLoading(true); setControllerAction(kind); setError(null);
    try {
      // Launching the game is always an explicit user click in a confirmation dialog.
      if (kind !== 'refresh') setController(await ipc.controller(kind, gamePath));
      await readGame(gamePath, false);
    } catch (err) { setError(errorText(err)); }
    finally { setControllerAction(null); setLoading(false); lock.current = false; mutation.current = false; }
  }

  async function openLogsFolder() {
    try { await ipc.openLogsFolder(); }
    catch (err) { setNotice(`Não foi possível abrir a pasta de logs: ${errorText(err)}`); }
  }

  return {
    gamePath, gameInfo, bundle, bundleError, diagnostics, controller, display,
    selectedOptions, setOptions, render, setRender,
    loading, listenersReady, busy, running, paused, stopping, controlPending, launching, controllerAction,
    error, notice, operation, progress, message,
    anyInstalled, readyToApply, gameClosed, canLaunchGame, mutation,
    inspect, chooseFolder, reloadBundle, refresh, run, togglePause, cancel, launchGame, runController, openLogsFolder,
  };
}

export type Installer = ReturnType<typeof useInstaller>;
