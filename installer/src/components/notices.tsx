import Icon from './icon';
import type { Installer } from '../installer/use-installer';

/** Package, operation and informational messages, in decreasing severity of layout weight. */
export default function Notices({ installer: i }: { installer: Installer }) {
  if (!i.bundleError && !i.error && !i.notice) return null;
  return (
    <div className="notices">
      {i.bundleError && <div className="notice warning" role="alert"><Icon name="alert" /><div><strong>Pacote indisponível.</strong><p>{i.bundleError}</p><button className="text-button" disabled={i.busy} onClick={() => void i.reloadBundle()}>Verificar pacote novamente</button></div></div>}
      {i.error && <div className="notice danger" role="alert"><Icon name="alert" /><div><strong>Não foi possível concluir.</strong><p>{i.error}</p></div></div>}
      {i.notice && <div className="notice" role="status"><Icon name="shield" /><div><p>{i.notice}</p></div></div>}
    </div>
  );
}
