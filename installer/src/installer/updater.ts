// Auto-update by GitHub release: `latest.json` is published by the release workflow.
import { useCallback, useEffect, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { errorText } from './model';

export type UpdateState =
  | { phase: 'idle' }
  | { phase: 'checking' }
  | { phase: 'current'; checkedAt: number }
  | { phase: 'available'; version: string; notes: string }
  | { phase: 'downloading'; version: string; received: number; total: number }
  | { phase: 'installing'; version: string }
  | { phase: 'error'; message: string };

export interface Updater {
  /** Installed application version (empty outside the desktop shell). */
  version: string;
  supported: boolean;
  state: UpdateState;
  check: () => Promise<void>;
  install: () => Promise<void>;
}

/** `blocked` holds the update back while the installer is writing to the game. */
export function useUpdater(autoCheck: boolean, blocked: boolean): Updater {
  const supported = isTauri();
  const [version, setVersion] = useState('');
  const [state, setState] = useState<UpdateState>({ phase: 'idle' });
  const pending = useRef<Update | null>(null);
  const busy = useRef(false);

  useEffect(() => { if (supported) getVersion().then(setVersion).catch(() => undefined); }, [supported]);

  const run = useCallback(async () => {
    if (!supported || busy.current) return;
    busy.current = true; setState({ phase: 'checking' });
    try {
      const update = await check();
      pending.current = update;
      setState(update ? { phase: 'available', version: update.version, notes: update.body ?? '' } : { phase: 'current', checkedAt: Date.now() });
    } catch (err) { setState({ phase: 'error', message: errorText(err) }); } finally { busy.current = false; }
  }, [supported]);

  const install = useCallback(async () => {
    const update = pending.current;
    if (!update || busy.current || blocked) return;
    busy.current = true;
    let received = 0, total = 0;
    setState({ phase: 'downloading', version: update.version, received, total });
    try {
      await update.downloadAndInstall(event => {
        if (event.event === 'Started') total = event.data.contentLength ?? 0;
        else if (event.event === 'Progress') received += event.data.chunkLength;
        else setState({ phase: 'installing', version: update.version });
        if (event.event !== 'Finished') setState({ phase: 'downloading', version: update.version, received, total });
      });
      setState({ phase: 'installing', version: update.version });
      await relaunch();
    } catch (err) { setState({ phase: 'error', message: errorText(err) }); busy.current = false; }
  }, [blocked]);

  useEffect(() => { if (autoCheck) void run(); }, [autoCheck, run]);

  return { version, supported, state, check: run, install };
}
