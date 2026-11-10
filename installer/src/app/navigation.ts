import { flushSync } from 'react-dom';

export type Screen = 'home' | 'components' | 'progress' | 'restore' | 'diagnostics';

export const navigation: { screen: Exclude<Screen, 'progress'>; label: string }[] = [
  { screen: 'home', label: 'A jornada' },
  { screen: 'components', label: 'Componentes' },
  { screen: 'restore', label: 'Restauração' },
  { screen: 'diagnostics', label: 'Diagnóstico e controle' },
];

const titles: Record<Screen, string> = {
  home: 'A jornada', components: 'Componentes', progress: 'Operação', restore: 'Restauração', diagnostics: 'Diagnóstico e controle',
};

export function documentTitle(screen: Screen): string {
  return `Soul Reaver PT-BR · ${titles[screen]}`;
}

/**
 * Applies a screen change inside a view transition, so the outgoing screen
 * cross-fades into the incoming one. Falls back to an immediate update where
 * the API is missing or the user prefers reduced motion.
 */
export function transitionScreen(update: () => void) {
  if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    update();
    return;
  }
  document.startViewTransition(() => flushSync(update));
}
