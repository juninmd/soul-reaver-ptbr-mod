interface Props { busy: boolean; running: boolean }

export default function StatusBar({ busy, running }: Props) {
  const text = !busy ? 'Instalador PT-BR · cobertura parcial · backup e verificação de integridade'
    : running ? 'Operação em andamento · aguarde a conclusão segura' : 'Conferindo sua instalação…';
  return (
    <footer className={`statusbar ${busy ? 'busy' : ''}`}>
      <span><i />{text}</span>
      <span className="footer-edition">NOSGOTH <b>/</b> PT-BR</span>
    </footer>
  );
}
