import { useState } from 'react';

export interface Settings { autoUpdate: boolean }
const key = 'soul-reaver-ptbr.settings';
const defaults: Settings = { autoUpdate: true };

function load(): Settings {
  try { return { ...defaults, ...JSON.parse(localStorage.getItem(key) ?? '{}') }; } catch { return defaults; }
}

/** Per-user preferences, kept in the webview storage. */
export function useSettings(): [Settings, (patch: Partial<Settings>) => void] {
  const [settings, setSettings] = useState<Settings>(load);
  const update = (patch: Partial<Settings>) => setSettings(current => {
    const next = { ...current, ...patch };
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* storage unavailable: keep in memory */ }
    return next;
  });
  return [settings, update];
}
