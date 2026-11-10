import type { Installer } from '../installer/use-installer';

/** Facts about the last operation and the recovery path, shared by several screens. */
export function viewState(i: Installer) {
  const status = i.operation?.status;
  const succeeded = status === 'succeeded';
  const ended = !!i.operation && status !== 'running';
  const partial = status === 'failed' || status === 'cancelled';
  // The folder was chosen but could not be inspected: only recovery is offered.
  const unverifiedRecovery = !!i.gamePath && !i.gameInfo && !!i.error;
  const recovery = i.anyInstalled || (partial && i.operation?.path === i.gamePath) || unverifiedRecovery;
  return { succeeded, ended, partial, unverifiedRecovery, recovery };
}

export type ViewState = ReturnType<typeof viewState>;
