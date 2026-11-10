import type { ModalName } from '../dialogs/app-dialogs';
import type { Installer } from '../installer/use-installer';
import type { Screen } from '../app/navigation';
import type { ViewState } from '../app/view-state';

/** What every screen receives from the application shell. */
export interface ScreenProps {
  installer: Installer;
  view: ViewState;
  onNavigate: (screen: Screen) => void;
  onOpenModal: (modal: ModalName) => void;
  onChangeLocation: () => void;
}
