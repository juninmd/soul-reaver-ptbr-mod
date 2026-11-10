// Types mirrored from the Rust IPC surface, plus the pure rules of the interface.

export interface AssetsInfo { menus: boolean; videos: number; subtitles: boolean; files: number }
export interface GraphicsInfo { installed: boolean; widescreen: boolean; files: number; resolution: string | null; message: string }
export interface ExternalInfo { id: string; installed: boolean; files: number; message: string }
export interface GameInfo {
  path: string; status: string; replaced: number; total: number; message: string;
  localization: AssetsInfo; graphics: GraphicsInfo; textures: ExternalInfo; ui: ExternalInfo; video: ExternalInfo;
}
export interface BundleInfo {
  path: string; name: string; version: string;
  voices: { name: string; version: string; replaced: number; total: number; bytes: number; localization: AssetsInfo; graphicsAvailable: boolean };
  graphicsAvailable: boolean; widescreenAvailable: boolean; texturesAvailable: boolean; uiAvailable: boolean;
  videoAvailable: boolean; videoFiles: number; resolution?: string | null; experimental: string[]; localizedFiles: number;
}
export interface DiagnosticItem { id: string; ok: boolean; detail: string }
export interface Diagnostics { path: string; exeSha256: string; exeSupported: boolean; gameClosed: boolean; items: DiagnosticItem[] }
export interface ControllerStatus { installed: boolean; running: boolean; connected: boolean; deviceName: string | null; message: string }
/** One read-only pass over an installation. `game` is absent when `error` explains why. */
export interface InstallationReport {
  game: GameInfo | null; error: string | null; diagnostics: Diagnostics | null;
  controller: ControllerStatus | null; warnings: string[];
}
export interface DisplayProfile { desktop: string; recommended: string; featureLevel: string | null; hardware: boolean; message: string }
export interface RenderSettings { resolution: string; vsync: boolean; fpsLimit: number; alwaysOnTop: boolean }
export interface OperationProgress { stage: string; current: number; total: number; message: string }
export type OperationKind = 'install' | 'repair' | 'restore';
export type OperationStatus = 'running' | 'succeeded' | 'failed' | 'cancelled';
export interface Operation { kind: OperationKind; status: OperationStatus; path: string }
export type ControllerAction = 'refresh' | 'install' | 'remove' | 'launch';
export type ComponentId = 'dubbing' | 'localization' | 'video' | 'graphics' | 'widescreen' | 'textures' | 'ui';
export type ApplyOptions = Record<ComponentId, boolean>;
export type IconName = 'arrow' | 'check' | 'folder' | 'shield' | 'voice' | 'eye' | 'film' | 'rune' | 'restore' | 'close' | 'minus' | 'maximize' | 'pause' | 'play' | 'settings' | 'spark' | 'alert';
export interface ComponentInfo { id: ComponentId; icon: IconName; title: string; description: string; tag: string; available: boolean; experimental: boolean }

export const initialOptions: ApplyOptions = { dubbing: true, localization: true, video: true, graphics: true, widescreen: true, textures: false, ui: false };
export const initialRender: RenderSettings = { resolution: 'auto', vsync: true, fpsLimit: 60, alwaysOnTop: false };
export const RENDER_FPS_OPTIONS = [0, 30, 60, 120] as const;
const RESOLUTIONS = ['3840x2160', '2560x1440', '1920x1080', '1600x900', '1280x720'];
/** Components that stay experimental regardless of what the package declares. */
const ALWAYS_EXPERIMENTAL: ComponentId[] = ['textures', 'ui'];

export function componentsFor(bundle: BundleInfo | null): ComponentInfo[] {
  const graphics = bundle?.graphicsAvailable === true;
  const items: Omit<ComponentInfo, 'experimental'>[] = [
    { id: 'dubbing', icon: 'voice', title: 'Vozes de Nosgoth', description: bundle ? `${bundle.voices.replaced} de ${bundle.voices.total} falas do catálogo · cobertura da campanha parcial.` : 'Dublagem em português brasileiro.', tag: 'PT-BR', available: !!bundle && bundle.voices.replaced > 0 },
    { id: 'localization', icon: 'rune', title: 'Cada palavra, um novo sentido', description: bundle ? `Menus e legendas · ${bundle.localizedFiles} arquivos · campanha ainda parcial em inglês.` : 'Menus e legendas em português brasileiro.', tag: 'TRADUÇÃO', available: !!bundle && bundle.localizedFiles > 0 },
    { id: 'video', icon: 'film', title: 'A história ganha vida', description: `Cinemáticas PT-BR${bundle ? ` · ${bundle.videoFiles} arquivos no pacote` : ''}.`, tag: 'VÍDEOS', available: bundle?.videoAvailable === true },
    { id: 'graphics', icon: 'eye', title: 'Um novo olhar para o abismo', description: 'Wrapper dgVoodoo2 · render acelerado por GPU · VSync e limite de quadros ajustáveis.', tag: 'GPU', available: graphics },
    { id: 'widescreen', icon: 'eye', title: 'Além dos limites do horizonte', description: 'Campo de visão Hor+ 16:9. Requer o wrapper dgVoodoo2 selecionado.', tag: '16:9', available: graphics && bundle?.widescreenAvailable === true },
    { id: 'textures', icon: 'spark', title: 'Texturas de outro reino', description: 'Texturas HD experimentais; carregamento no jogo ainda sem prova.', tag: 'EXPERIMENTAL', available: bundle?.texturesAvailable === true },
    { id: 'ui', icon: 'rune', title: 'Símbolos do mundo antigo', description: 'Interface / HUD Unicode experimental; integração real pendente.', tag: 'EXPERIMENTAL', available: bundle?.uiAvailable === true },
  ];
  return items.map(item => ({ ...item, experimental: ALWAYS_EXPERIMENTAL.includes(item.id) || !!bundle?.experimental.includes(item.id) }));
}

/** What will actually be installed: unavailable components are never selected and widescreen needs the wrapper. */
export function effectiveOptions(options: ApplyOptions, bundle: BundleInfo | null): ApplyOptions {
  const result = Object.fromEntries(componentsFor(bundle).map(item => [item.id, options[item.id] && item.available])) as ApplyOptions;
  result.widescreen = result.widescreen && result.graphics;
  return result;
}

function parseMode(value: string | null | undefined): [number, number] | null {
  if (!value) return null;
  const [width, height] = value.split('x').map(Number);
  return Number.isFinite(width) && Number.isFinite(height) ? [width, height] : null;
}

/** Resolution choices never offer a mode larger than the detected desktop; the current choice is always listed. */
export function resolutionChoices(profile: DisplayProfile | null, current: string): { value: string; label: string }[] {
  const desktop = parseMode(profile?.desktop);
  const modes = RESOLUTIONS.filter(mode => {
    const size = parseMode(mode);
    return !desktop || (!!size && size[0] <= desktop[0] && size[1] <= desktop[1]);
  });
  const choices = [
    { value: 'auto', label: profile ? `Automática (${profile.recommended})` : 'Automática (detectada)' },
    ...modes.map(mode => ({ value: mode, label: mode })),
  ];
  return choices.some(choice => choice.value === current) ? choices : [...choices, { value: current, label: current }];
}

export function hasInstallation(game: GameInfo | null, controller: ControllerStatus | null): boolean {
  const managed = !!game && (['installed', 'preparing'].includes(game.status) || game.localization.files > 0 || game.graphics.installed || game.video.installed || game.textures.installed || game.ui.installed);
  return managed || controller?.installed === true;
}

/** Percentage of the current stage, or `null` while the backend has not reported a total. */
export function stagePercent(progress: OperationProgress | null): number | null {
  if (!progress || !Number.isFinite(progress.total) || progress.total <= 0 || !Number.isFinite(progress.current)) return null;
  return Math.max(0, Math.min(100, Math.floor(progress.current * 100 / progress.total)));
}

const stageLabels: Record<string, string> = { iniciando: 'Preparando operação', verificacao: 'Conferindo integridade', 'preparacao-dublagem': 'Preparando dublagem', backup: 'Preservando áudio original', instalacao: 'Aplicando dublagem', localization: 'Aplicando menus e legendas', video: 'Aplicando vídeos', graficos: 'Aplicando gráficos', textures: 'Aplicando texturas', ui: 'Aplicando interface', restauracao: 'Restaurando dublagem', concluido: 'Etapa concluída' };
export function stageLabel(stage: string): string {
  if (stage.startsWith('backup-')) return `Preservando originais · ${stageLabel(stage.slice(7))}`;
  if (stage.startsWith('restauracao-')) return `Restaurando · ${stage.replace('restauracao-', '').replaceAll('-', ' ')}`;
  return stageLabels[stage] || stage.replaceAll('-', ' ');
}

const diagnosticLabels: Record<string, string> = { voices: 'Dublagem', localization: 'Menus e legendas', video: 'Vídeos', bundle: 'Pacote', graphics: 'Gráficos', textures: 'Texturas', ui: 'Interface', controller: 'DualSense' };
export function diagnosticLabel(id: string): string {
  return diagnosticLabels[id] || id;
}

/** Text of a rejected IPC call or thrown error, without the `Error:` prefix. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
