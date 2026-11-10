// Typed boundary with the Rust commands in `src-tauri/src/commands.rs`.
import { invoke } from '@tauri-apps/api/core';
import type { ApplyOptions, BundleInfo, ControllerStatus, DisplayProfile, GameInfo, InstallationReport, OperationKind, RenderSettings } from './model';

const operationCommands: Record<OperationKind, string> = { install: 'apply_mod', repair: 'repair_mod', restore: 'restore_mod' };
const controllerCommands = { install: 'install_controller', remove: 'remove_controller', launch: 'launch_controller_game' } as const;

export const ipc = {
  detectGame: () => invoke<string | null>('detect_game'),
  bundleInfo: () => invoke<BundleInfo>('get_bundle_info'),
  displayProfile: () => invoke<DisplayProfile>('get_display_profile'),
  /** Game state, diagnosis and controller support from a single inspection of the files. */
  inspectInstallation: (gamePath: string) => invoke<InstallationReport>('inspect_installation', { gamePath }),
  runOperation: (kind: OperationKind, gamePath: string, options: ApplyOptions, render: RenderSettings) => invoke<GameInfo>(
    operationCommands[kind],
    kind === 'install'
      ? { gamePath, options: { ...options, vsync: render.vsync, fpsLimit: render.fpsLimit, alwaysOnTop: render.alwaysOnTop, renderResolution: render.resolution } }
      : { gamePath },
  ),
  pauseOperation: () => invoke<void>('pause_operation'),
  resumeOperation: () => invoke<void>('resume_operation'),
  cancelOperation: () => invoke<void>('cancel_operation'),
  launchGame: (gamePath: string) => invoke<void>('launch_game', { gamePath }),
  controller: (action: keyof typeof controllerCommands, gamePath: string) => invoke<ControllerStatus>(controllerCommands[action], { gamePath }),
  openLogsFolder: () => invoke<void>('open_logs_folder'),
};
