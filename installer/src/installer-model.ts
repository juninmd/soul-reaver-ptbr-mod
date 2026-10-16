export interface AssetsInfo { menus: boolean; videos: number; subtitles: boolean; files: number }
export interface GraphicsInfo { installed: boolean; widescreen: boolean; files: number; message: string }
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
export interface Diagnostics { path: string; exeSha256: string; exeSupported: boolean; gameClosed: boolean; items: { id: string; ok: boolean; detail: string }[] }
export interface ControllerStatus { installed: boolean; running: boolean; connected: boolean; deviceName: string | null; message: string }
export interface OperationProgress { stage: string; current: number; total: number; message: string }
export type OperationKind = 'install' | 'repair' | 'restore';
export type OperationStatus = 'running' | 'succeeded' | 'failed' | 'cancelled';
export interface Operation { kind: OperationKind; status: OperationStatus; path: string }
export type ComponentId = 'dubbing' | 'localization' | 'video' | 'graphics' | 'widescreen' | 'textures' | 'ui';
export type ApplyOptions = Record<ComponentId, boolean>;
export const initialOptions: ApplyOptions = { dubbing: true, localization: true, video: true, graphics: true, widescreen: true, textures: false, ui: false };
export type IconName = 'arrow' | 'check' | 'folder' | 'shield' | 'voice' | 'eye' | 'film' | 'rune' | 'restore' | 'close' | 'minus' | 'maximize' | 'pause' | 'play' | 'settings' | 'spark';
export interface ComponentInfo { id: ComponentId; icon: IconName; title: string; description: string; tag: string; available: boolean; experimental: boolean }

export function componentsFor(bundle: BundleInfo | null): ComponentInfo[] {
  const items: Omit<ComponentInfo, 'experimental'>[] = [
    { id: 'dubbing', icon: 'voice', title: 'Vozes de Nosgoth', description: bundle ? `${bundle.voices.replaced} de ${bundle.voices.total} falas do catálogo · cobertura da campanha parcial.` : 'Dublagem em português brasileiro.', tag: 'PT-BR', available: !!bundle && bundle.voices.replaced > 0 },
    { id: 'localization', icon: 'rune', title: 'Cada palavra, um novo sentido', description: bundle ? `Menus e legendas · ${bundle.localizedFiles} arquivos · campanha ainda parcial em inglês.` : 'Menus e legendas em português brasileiro.', tag: 'TRADUÇÃO', available: !!bundle && bundle.localizedFiles > 0 },
    { id: 'video', icon: 'film', title: 'A história ganha vida', description: `Cinemáticas PT-BR${bundle ? ` · ${bundle.videoFiles} arquivos no pacote` : ''}.`, tag: 'VÍDEOS', available: bundle?.videoAvailable === true },
    { id: 'graphics', icon: 'eye', title: 'Um novo olhar para o abismo', description: `Renderização ${bundle?.resolution || '4K'} com dgVoodoo2.`, tag: '4K', available: bundle?.graphicsAvailable === true },
    { id: 'widescreen', icon: 'eye', title: 'Além dos limites do horizonte', description: 'Campo de visão Hor+ 16:9. Requer renderização 4K selecionada.', tag: '16:9', available: bundle?.graphicsAvailable === true && bundle?.widescreenAvailable === true },
    { id: 'textures', icon: 'spark', title: 'Texturas de outro reino', description: 'Texturas HD experimentais; carregamento no jogo ainda sem prova.', tag: 'EXPERIMENTAL', available: bundle?.texturesAvailable === true },
    { id: 'ui', icon: 'rune', title: 'Símbolos do mundo antigo', description: 'Interface / HUD Unicode experimental; integração real pendente.', tag: 'EXPERIMENTAL', available: bundle?.uiAvailable === true },
  ];
  return items.map(item => ({ ...item, experimental: item.id === 'textures' || item.id === 'ui' || !!bundle?.experimental.includes(item.id) }));
}

export function effectiveOptions(options: ApplyOptions, bundle: BundleInfo | null): ApplyOptions {
  const available = componentsFor(bundle);
  const result = Object.fromEntries(available.map(item => [item.id, options[item.id] && item.available])) as ApplyOptions;
  result.widescreen = result.widescreen && result.graphics;
  return result;
}
export function hasInstallation(game: GameInfo | null, controller: ControllerStatus | null): boolean {
  return !!game && (['installed', 'preparing'].includes(game.status) || game.localization.files > 0 || game.graphics.installed || game.video.installed || game.textures.installed || game.ui.installed) || controller?.installed === true;
}
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
