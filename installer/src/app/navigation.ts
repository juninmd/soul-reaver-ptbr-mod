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
