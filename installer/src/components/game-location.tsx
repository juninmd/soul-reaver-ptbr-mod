import Icon from './icon';
import type { Installer } from '../installer/use-installer';

interface Props { installer: Installer; onChange: () => void }

/** The selected copy of the game and, in one line, whether it can be modified now. */
export default function GameLocation({ installer: i, onChange }: Props) {
  const title = i.loading ? 'Conferindo sua instalação…' : i.gameInfo ? 'Soul Reaver · Steam Classic' : i.gamePath ? 'Instalação não validada' : 'Encontre seu caminho';
  const status = i.loading ? 'Aguarde as verificações'
    : !i.gameClosed ? 'Feche o jogo antes de alterar arquivos'
      : !i.gameInfo ? 'Aguardando uma cópia compatível'
        : i.anyInstalled ? 'Componentes detectados · consulte o diagnóstico' : 'Base verificada · Steam Classic';
  const ready = !!i.gameInfo && i.gameClosed;
  return (
    <div className={`game-location ${i.gameInfo ? '' : 'location-warning'}`} aria-busy={i.loading}>
      <div className="location-heading"><Icon name="folder" /><span>SUA CÓPIA DO JOGO</span><button className="text-button" disabled={i.busy} onClick={onChange}>Alterar</button></div>
      <strong>{title}</strong>
      <span className="file-path" title={i.gamePath}>{i.gamePath || 'Selecione a pasta do jogo para continuar.'}</span>
      <span className={`status-line ${ready ? 'spectral' : 'amber'} ${i.loading ? 'pending' : ''}`}><span className="status-dot" />{status}</span>
    </div>
  );
}
