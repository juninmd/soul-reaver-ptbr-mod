import { useEffect, useRef, useState } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { effectiveOptions, hasInstallation, initialOptions, initialRender, type ApplyOptions, type BundleInfo, type ControllerStatus, type Diagnostics, type DisplayProfile, type GameInfo, type Operation, type OperationKind, type OperationProgress, type RenderSettings } from './installer-model';

export type ControllerAction = 'refresh' | 'install' | 'remove' | 'launch';

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
  async function readGame(path: string, clear: boolean) {
    if (clear) { setGamePath(path); setGameInfo(null); setDiagnostics(null); setController(null); }
    const [inspection, diagnosis, control] = await Promise.allSettled([
      invoke<GameInfo>('inspect_game', { path }),
      invoke<Diagnostics>('diagnose', { gamePath: path }),
      invoke<ControllerStatus>('get_controller_status', { gamePath: path }),
    ]);
    setGameInfo(inspection.status === 'fulfilled' ? inspection.value : null);
    setDiagnostics(diagnosis.status === 'fulfilled' ? diagnosis.value : null);
    setController(control.status === 'fulfilled' ? control.value : null);
    if (inspection.status === 'rejected') throw new Error(String(inspection.reason));
    const failures = [diagnosis, control].filter(item => item.status === 'rejected');
    if (failures.length) setNotice('Algumas verificações não puderam ser concluídas. Atualize o diagnóstico antes de instalar.');
  }

  useEffect(() => {
    let disposed = false;
    const unlisteners: UnlistenFn[] = [];
    async function bind<T>(name: string, handler: (payload: T) => void) {
      const unlisten = await listen<T>(name, event => { if (!disposed && activeOperation.current) handler(event.payload); });
      if (disposed) unlisten(); else unlisteners.push(unlisten);
    }
    async function initialize() {
      if (!isTauri()) {
        setError('Abra o aplicativo desktop para localizar o jogo e gerenciar a instalação.');
        setLoading(false); lock.current = false;
        return;
      }
      try {
        await Promise.all([
          bind<OperationProgress>('progress', payload => { setProgress(payload); setMessage(payload.message); }),
          bind<string>('progress-message', setMessage),
        ]);
        if (disposed) return;
        setListenersReady(true);
        // A missing/invalid package must not hide a detected installation or recovery.
        const [detected, foundBundle, profile] = await Promise.allSettled([
          invoke<string | null>('detect_game'), invoke<BundleInfo>('get_bundle_info'), invoke<DisplayProfile>('get_display_profile'),
        ]);
        if (disposed) return;
        if (foundBundle.status === 'fulfilled') setBundle(foundBundle.value);
        else setBundleError(String(foundBundle.reason));
        if (profile.status === 'fulfilled') setDisplay(profile.value);
        if (detected.status === 'fulfilled' && detected.value) await readGame(detected.value, true);
        else if (detected.status === 'rejected') setError(String(detected.reason));
      } catch (err) {
        if (!disposed) setError(String(err));
      } finally {
        if (!disposed) { setLoading(false); lock.current = false; }
      }
    }
    void initialize();
    return () => { disposed = true; unlisteners.forEach(unlisten => unlisten()); };
  }, []);

  async function query(task: () => Promise<void>) {
    if (lock.current || controlLock.current) return;
    lock.current = true; setLoading(true); setError(null); setNotice('');
    try { await task(); } catch (err) { setError(String(err)); }
    finally { setLoading(false); lock.current = false; }
  }
  async function inspect(path: string) {
    if (!path.trim()) return;
    await query(() => readGame(path.trim(), true));
  }
  async function chooseFolder() {
    await query(async () => {
      const selected = await open({ directory: true, multiple: false, title: 'Selecione a pasta de instalação do Soul Reaver' });
      if (typeof selected === 'string') await readGame(selected, true);
    });
  }
  async function reloadBundle() {
    await query(async () => {
      setBundleError(null); setBundle(null);
      try { setBundle(await invoke<BundleInfo>('get_bundle_info')); }
      catch (err) { setBundleError(String(err)); }
    });
  }
  async function refresh() { if (gamePath) await query(() => readGame(gamePath, true)); }

  const selectedOptions = effectiveOptions(options, bundle);
  const readyToApply = !!gameInfo && ['original', 'installed'].includes(gameInfo.status) && !!bundle && listenersReady && diagnostics?.exeSupported === true && diagnostics.gameClosed && Object.values(selectedOptions).some(Boolean);
  const anyInstalled = hasInstallation(gameInfo, controller);
  const running = operation?.status === 'running';
  const busy = loading || running || controlPending || launching;
  const canLaunchGame = !busy && !!gameInfo && operation?.kind === 'install' && operation.status === 'succeeded' && operation.path === gamePath && diagnostics?.gameClosed !== false && controller?.running !== true;

  async function launchGame() {
    if (lock.current || controlLock.current || !canLaunchGame || !operation) return;
    const path = operation.path;
    lock.current = true; mutation.current = true;
    setLaunching(true); setError(null); setNotice('');
    try {
      await invoke('launch_game', { gamePath: path });
      setNotice('Jogo aberto.');
      try { await readGame(path, false); }
      catch (err) { setNotice(`Jogo aberto. Não foi possível atualizar o diagnóstico: ${String(err)}`); }
    } catch (err) { setError(String(err)); }
    finally { setLaunching(false); lock.current = false; mutation.current = false; }
  }

  async function run(kind: OperationKind): Promise<boolean> {
    if (lock.current || controlLock.current || !gamePath || !listenersReady || (kind === 'install' && !readyToApply)) return false;
    lock.current = true; mutation.current = true; activeOperation.current = true;
    const path = gamePath;
    setOperation({ kind, path, status: 'running' }); setError(null); setNotice('');
    setProgress(null); setMessage('Preparando operação…'); setPaused(false); setStopping(false);
    try {
      const command = kind === 'install' ? 'apply_mod' : kind === 'repair' ? 'repair_mod' : 'restore_mod';
      const applyOptions = {
        ...selectedOptions,
        vsync: render.vsync,
        fpsLimit: render.fpsLimit,
        alwaysOnTop: render.alwaysOnTop,
        renderResolution: render.resolution,
      };
      const updated = await invoke<GameInfo>(command, kind === 'install' ? { gamePath: path, options: applyOptions } : { gamePath: path });
      setGameInfo(updated);
      setOperation({ kind, path, status: 'succeeded' });
      setMessage(kind === 'restore' ? 'Restauração concluída.' : kind === 'repair' ? 'Reparo concluído.' : 'Componentes aplicados. Consulte a cobertura no diagnóstico.');
    } catch (err) {
      const text = String(err);
      const cancelled = text.toLowerCase().includes('cancelada');
      setOperation({ kind, path, status: cancelled ? 'cancelled' : 'failed' });
      setError(cancelled ? null : text);
      setMessage(cancelled ? 'Operação interrompida entre unidades seguras. Confira o estado dos componentes.' : 'A operação não foi concluída. Alguns componentes podem ter sido aplicados.');
    } finally {
      activeOperation.current = false;
      // Keep the navigation/close guard until the final inspection has settled.
      setLoading(true);
      try { await readGame(path, false); }
      catch (err) { setNotice(`Não foi possível atualizar o estado após a operação: ${String(err)}`); }
      setLoading(false); setPaused(false); setStopping(false);
      lock.current = false; mutation.current = false;
    }
    return true;
  }
  async function togglePause() {
    if (!activeOperation.current || stopping || controlLock.current) return;
    controlLock.current = true; setControlPending(true);
    try { await invoke(paused ? 'resume_operation' : 'pause_operation'); if (activeOperation.current) setPaused(!paused); }
    catch (err) { setNotice(String(err)); }
    finally { controlLock.current = false; setControlPending(false); }
  }
  async function cancel() {
    if (!activeOperation.current || stopping || controlLock.current) return;
    controlLock.current = true; setControlPending(true); setStopping(true);
    try {
      await invoke('cancel_operation');
      if (activeOperation.current) { setPaused(false); setMessage('Parada solicitada; aguardando a unidade segura em andamento…'); }
    } catch (err) { setNotice(String(err)); setStopping(false); }
    finally { controlLock.current = false; setControlPending(false); }
  }
  async function runController(kind: ControllerAction) {
    if (lock.current || controlLock.current || !gamePath) return;
    lock.current = true; mutation.current = kind !== 'refresh'; setLoading(true); setControllerAction(kind); setError(null);
    try {
      const command = { refresh: 'get_controller_status', install: 'install_controller', remove: 'remove_controller', launch: 'launch_controller_game' }[kind];
      setController(await invoke<ControllerStatus>(command, { gamePath }));
      // Launching the game is always an explicit user click in a confirmation dialog.
      await readGame(gamePath, false);
    } catch (err) { setError(String(err)); }
    finally { setControllerAction(null); setLoading(false); lock.current = false; mutation.current = false; }
  }

  async function openLogsFolder() {
    try {
      await invoke('open_logs_folder');
    } catch (err) {
      setNotice(`Não foi possível abrir a pasta de logs: ${String(err)}`);
    }
  }

  return { gamePath, gameInfo, bundle, bundleError, diagnostics, controller, options, setOptions, selectedOptions, render, setRender, display, loading, listenersReady, controllerAction, launching, canLaunchGame, launchGame, error, notice, operation, progress, message, paused, stopping, controlPending, running, busy, anyInstalled, readyToApply, mutation, inspect, chooseFolder, reloadBundle, refresh, run, togglePause, cancel, runController, openLogsFolder, setNotice };
}
