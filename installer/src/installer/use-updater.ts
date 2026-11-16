import { useCallback, useEffect, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { errorText } from './model';

export type UpdatePhase = 'idle' | 'checking' | 'uptodate' | 'available' | 'downloading' | 'installing' | 'error';
export interface UpdateProgress { downloaded: number; total: number }

const AUTO_KEY = 'srmod.autoUpdate';
const readAuto = () => { try { return localStorage.getItem(AUTO_KEY) !== 'off'; } catch { return true; } };

/** Release-based self-update: signature is verified by the Tauri updater against the key in tauri.conf.json. */
export function useUpdater(blocked: boolean) {
  const [version, setVersion] = useState('');
  const [phase, setPhase] = useState<UpdatePhase>('idle');
  const [available, setAvailable] = useState<{ version: string; notes: string } | null>(null);
  const [progress, setProgress] = useState<UpdateProgress | null>(null);
  const [error, setError] = useState('');
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [auto, setAutoState] = useState(readAuto);
  const update = useRef<Update | null>(null);
  const busy = useRef(false);

  useEffect(() => { if (isTauri()) getVersion().then(setVersion).catch(() => undefined); }, []);

  const checkNow = useCallback(async () => {
    if (!isTauri() || busy.current) return;
    busy.current = true; setPhase('checking'); setError('');
    try {
      const found = await check();
      setCheckedAt(new Date());
      update.current = found;
      if (found) { setAvailable({ version: found.version, notes: found.body ?? '' }); setPhase('available'); }
      else { setAvailable(null); setPhase('uptodate'); }
    } catch (err) { setError(errorText(err)); setPhase('error'); }
    finally { busy.current = false; }
  }, []);

  useEffect(() => { if (auto) void checkNow(); }, [auto, checkNow]);

  const install = useCallback(async () => {
    const found = update.current;
    if (!found || busy.current || blocked) return;
    busy.current = true; setPhase('downloading'); setProgress({ downloaded: 0, total: 0 }); setError('');
    try {
      let downloaded = 0; let total = 0;
      await found.downloadAndInstall(event => {
        if (event.event === 'Started') total = event.data.contentLength ?? 0;
        else if (event.event === 'Progress') downloaded += event.data.chunkLength;
        else setPhase('installing');
        setProgress({ downloaded, total });
      });
      setPhase('installing');
      await relaunch();
    } catch (err) { setError(errorText(err)); setPhase('error'); }
    finally { busy.current = false; }
  }, [blocked]);

  const setAuto = (value: boolean) => { setAutoState(value); try { localStorage.setItem(AUTO_KEY, value ? 'on' : 'off'); } catch { /* per-viewer convenience only */ } };

  return { version, phase, available, progress, error, checkedAt, auto, setAuto, checkNow, install };
}
export type Updater = ReturnType<typeof useUpdater>;
