// Exercises the production React UI with a controlled Tauri transport in Chromium.
// Native smoke/transactions are recorded separately. No backend/game claim is made here.
import { createRequire } from 'node:module';
import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
let chromium;
for (const name of await readdir(join(process.env.LOCALAPPDATA, 'ms-playwright', '.links'))) {
  try { chromium = require((await readFile(join(process.env.LOCALAPPDATA, 'ms-playwright', '.links', name), 'utf8')).trim()).chromium; if (chromium) break; } catch { /* local installs only */ }
}
assert.ok(chromium, 'Playwright local não encontrado.');
const output = resolve(process.argv[2] || 'validate/96-identidade-implementada/browser');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1240, height: 800 }, deviceScaleFactor: 1 });
const errors = [];
const checks = [];
const external = [];
const page = await context.newPage();
page.setDefaultTimeout(7000);
page.on('pageerror', error => errors.push(String(error)));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
page.on('request', request => { if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:1496/')) external.push(request.url()); });
await context.addInitScript(() => {
  window.isTauri = true;
  const callbacks = new Map();
  const listeners = new Map();
  let id = 0;
  const assets = { menus: false, subtitles: false, videos: 0, files: 0 };
  const component = name => ({ id: name, installed: false, files: 0, message: 'Não instalado.' });
  const bridge = window.__testBridge = {
    calls: [], fail: {}, pending: null, launchPending: null, detect: 'C:\\fixture\\SoulReaver', folder: null,
    game: { path: 'C:\\fixture\\SoulReaver', status: 'original', replaced: 0, total: 479, message: 'Base original compatível.', localization: assets, graphics: { installed: false, widescreen: false, files: 0, message: 'Gráficos originais.' }, video: component('video'), textures: component('textures'), ui: component('ui') },
    bundle: { path: 'C:\\fixture\\package', name: 'Pacote de teste da interface', version: '0.1.0', voices: { name: 'Vozes', version: '0.1.0', replaced: 12, total: 479, bytes: 1000, localization: assets, graphicsAvailable: true }, graphicsAvailable: true, widescreenAvailable: true, texturesAvailable: false, uiAvailable: true, videoAvailable: true, videoFiles: 3, localizedFiles: 2, resolution: '3840x2160', experimental: ['ui'] },
    controller: { installed: false, connected: false, running: false, deviceName: null, message: 'Nenhum DualSense detectado.' },
    emit(event, payload) { for (const [key, listener] of listeners) if (listener.event === event) callbacks.get(listener.handler)?.({ event, id: key, payload }); },
    finish(status = 'success') {
      const pending = bridge.pending; bridge.pending = null;
      if (status === 'success') {
        bridge.game = { ...bridge.game, status: pending.command === 'restore_mod' ? 'original' : 'installed', replaced: pending.command === 'restore_mod' ? 0 : 12 };
        pending.resolve(structuredClone(bridge.game));
      } else pending.reject(status === 'cancel' ? 'Operação cancelada entre unidades de trabalho.' : 'Conflito: arquivo alterado posteriormente. Preservado.');
    },
    finishLaunch(error) {
      const pending = bridge.launchPending; bridge.launchPending = null;
      if (error) pending.reject(error);
      else { bridge.controller.running = true; pending.resolve(); }
    },
  };
  if (sessionStorage.getItem('fixtureScenario') === 'missing-bundle') bridge.fail.get_bundle_info = 'Pacote ausente';
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener(_event, key) { listeners.delete(key); } };
  window.__TAURI_INTERNALS__ = {
    metadata: { currentWindow: { label: 'main' }, currentWebview: { label: 'main' } },
    transformCallback(callback) { const key = ++id; callbacks.set(key, callback); return key; },
    async invoke(command, args = {}) {
      bridge.calls.push({ command, args: structuredClone(args) });
      if (bridge.fail[command]) throw bridge.fail[command];
      if (command === 'plugin:event|listen') { const key = ++id; listeners.set(key, args); return key; }
      if (command === 'plugin:event|unlisten') { listeners.delete(args.eventId); return; }
      if (command === 'detect_game') return bridge.detect;
      if (command === 'get_bundle_info') return structuredClone(bridge.bundle);
      if (command === 'inspect_game') { if (args.path.includes('incompatible')) throw 'Edição não suportada: hash diferente.'; bridge.game.path = args.path; return structuredClone(bridge.game); }
      if (command === 'get_controller_status') return structuredClone(bridge.controller);
      if (command === 'diagnose') return { path: args.gamePath, exeSha256: '9'.repeat(64), exeSupported: true, gameClosed: !bridge.controller.running, items: [{ id: 'voices', ok: bridge.game.status === 'installed', detail: `${bridge.game.replaced}/479 falas contra o backup` }] };
      if (command === 'plugin:dialog|open') return bridge.folder;
      if (['apply_mod', 'repair_mod', 'restore_mod'].includes(command)) return new Promise((resolve, reject) => { bridge.pending = { command, resolve, reject }; });
      if (command === 'launch_game') return new Promise((resolve, reject) => { bridge.launchPending = { resolve, reject }; });
      if (command === 'pause_operation' || command === 'resume_operation' || command === 'cancel_operation') return;
      if (command === 'plugin:window|close') { bridge.emit('tauri://close-requested', null); return; }
      if (command.startsWith('plugin:window|')) return;
      if (command === 'install_controller' || command === 'remove_controller') { bridge.controller.installed = command === 'install_controller'; return structuredClone(bridge.controller); }
      throw new Error(`Comando não previsto no teste: ${command}`);
    },
  };
});
const button = name => page.getByRole('button', { name, exact: true });
const check = (name, value) => { assert.ok(value, name); checks.push(name); };
const shot = name => page.screenshot({ path: join(output, `${name}.png`), fullPage: true });
const waitIdle = () => page.waitForFunction(() => ![...document.querySelectorAll('nav button')].find(e => e.textContent === 'A jornada')?.disabled);
const commandCalls = name => page.evaluate(name => window.__testBridge.calls.filter(call => call.command === name), name);
const pending = () => page.waitForFunction(() => window.__testBridge.pending !== null);
const finish = async status => { await page.evaluate(status => window.__testBridge.finish(status), status); await waitIdle(); };
const install = async () => { await button('Revisar instalação').click(); await button('Instalar componentes').click(); await pending(); };
try {
  await page.goto('http://127.0.0.1:1496/'); await waitIdle(); await shot('01-jornada');
  check('Abertura sem rolagem em 1240x800', await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1));
  check('Sem aplicação automática ao iniciar', (await commandCalls('apply_mod')).length === 0);
  check('Sem abertura automática do jogo ao iniciar', (await commandCalls('launch_game')).length === 0);
  await button('Preparar instalação').click(); await shot('02-componentes');
  check('Componentes e ações cabem na janela inicial', await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1));
  check('Componentes refletem disponibilidade do pacote', await page.getByRole('checkbox', { name: 'Texturas de outro reino' }).isDisabled());
  check('Componente experimental disponível permanece opcional', await page.getByRole('checkbox', { name: 'Símbolos do mundo antigo' }).isEnabled() && !await page.getByRole('checkbox', { name: 'Símbolos do mundo antigo' }).isChecked());
  await page.getByRole('checkbox', { name: 'Um novo olhar para o abismo' }).uncheck();
  check('Widescreen depende dos gráficos e fica desmarcado', await page.getByRole('checkbox', { name: 'Além dos limites do horizonte' }).isDisabled() && !await page.getByRole('checkbox', { name: 'Além dos limites do horizonte' }).isChecked());
  await page.getByRole('checkbox', { name: 'Vozes de Nosgoth' }).uncheck();
  await page.getByRole('checkbox', { name: 'Cada palavra, um novo sentido' }).uncheck();
  await page.getByRole('checkbox', { name: 'A história ganha vida' }).uncheck();
  check('Seleção vazia bloqueia instalação', await button('Revisar instalação').isDisabled());
  await page.getByRole('checkbox', { name: 'Vozes de Nosgoth' }).check();
  await button('Revisar instalação').click(); await shot('03-revisao');
  check('Revisão contém apenas a escolha efetiva', await page.locator('.review-list li').count() === 1);
  check('Revisão ainda não instala', (await commandCalls('apply_mod')).length === 0);
  await page.keyboard.press('Escape');
  check('Escape devolve foco à revisão', await button('Revisar instalação').evaluate(e => e === document.activeElement));
  await install();
  check('Abrir jogo não aparece durante a instalação', await button('Abrir jogo').count() === 0);
  check('IPC recebe destino e opções reais da seleção', JSON.stringify((await commandCalls('apply_mod')).at(-1).args) === JSON.stringify({ gamePath: 'C:\\fixture\\SoulReaver', options: { dubbing: true, localization: false, video: false, graphics: false, widescreen: false, textures: false, ui: false } }));
  await page.evaluate(() => window.__testBridge.emit('progress', { stage: 'instalacao', current: 1, total: 4, message: 'Aplicando dublagem.' }));
  await page.waitForFunction(() => document.querySelector('progress')?.value === 25);
  check('Progresso usa etapa enviada pelo backend', Number(await page.getByRole('progressbar').getAttribute('value')) === 25);
  check('Navegação bloqueada durante escrita', await button('A jornada').isDisabled());
  await button('Fechar janela').click();
  check('Fechamento por botão próprio é protegido', await page.getByRole('heading', { name: 'Aguarde uma conclusão segura.' }).isVisible() && !(await commandCalls('plugin:window|close')).length);
  await button('Voltar à operação').click();
  await page.evaluate(() => window.__testBridge.emit('tauri://close-requested', null));
  await page.getByRole('heading', { name: 'Aguarde uma conclusão segura.' }).waitFor();
  check('Fechamento do sistema não destrói escritor ativo', !(await commandCalls('plugin:window|destroy')).length);
  await button('Voltar à operação').click();
  await button('Pausar').click(); await button('Retomar').waitFor();
  check('Pausa e retomada usam comandos cooperativos', (await commandCalls('pause_operation')).length === 1);
  await shot('04-progresso-pausado'); await button('Retomar').click();
  check('Retomada enviada ao backend', (await commandCalls('resume_operation')).length === 1);
  await page.evaluate(() => window.__testBridge.emit('progress', { stage: 'concluido', current: 1, total: 1, message: 'Etapa concluída.' }));
  check('100 por cento de uma etapa não conclui operação pendente', await page.getByRole('heading', { name: 'Nosgoth desperta.' }).isVisible());
  await button('Parar operação').click(); await button('Parar com segurança').click();
  check('Pedido de parada não encerra antes da resposta', await button('A jornada').isDisabled() && (await commandCalls('cancel_operation')).length === 1);
  await finish('cancel');
  check('Cancelamento não oferece abertura do jogo', await button('Abrir jogo').count() === 0);
  check('Cancelamento informa componentes parciais', await page.getByRole('heading', { name: 'Jornada interrompida.' }).isVisible() && await page.getByText('A interrupção não desfaz componentes já aplicados.', { exact: false }).isVisible());
  check('Estado é inspecionado após cancelamento', (await commandCalls('inspect_game')).length >= 2);
  await button('Componentes').click(); await install();
  await page.evaluate(() => { window.__testBridge.fail.diagnose = 'Falha de diagnóstico após aplicação'; });
  await finish('success');
  check('Falha de diagnóstico não reclassifica instalação concluída', await page.getByRole('heading', { name: 'Componentes aplicados.' }).isVisible());
  check('Instalação concluída oferece Abrir jogo sem exigir DualSense', await button('Abrir jogo').isEnabled());
  check('Concluir instalação não abre o jogo automaticamente', (await commandCalls('launch_game')).length === 0);
  await shot('05-conclusao');
  await button('Abrir jogo').click();
  await page.waitForFunction(() => window.__testBridge.launchPending !== null);
  check('Abrir jogo envia o destino da instalação', (await commandCalls('launch_game')).at(-1).args.gamePath === 'C:\\fixture\\SoulReaver');
  check('Inicialização bloqueia clique repetido e navegação', await button('Abrindo…').isDisabled() && await button('A jornada').isDisabled());
  await page.evaluate(() => window.__testBridge.finishLaunch('Não foi possível abrir o jogo: acesso negado.'));
  await waitIdle();
  check('Falha ao abrir permite nova tentativa e mantém instalação concluída', await button('Abrir jogo').isEnabled() && await page.getByText('Não foi possível abrir o jogo: acesso negado.', { exact: true }).isVisible() && await page.getByRole('heading', { name: 'Componentes aplicados.' }).isVisible());
  await page.evaluate(() => { delete window.__testBridge.fail.diagnose; });
  await button('Abrir jogo').focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(() => window.__testBridge.launchPending !== null);
  await page.evaluate(() => window.__testBridge.finishLaunch()); await waitIdle();
  check('Abertura por teclado atualiza estado e impede iniciar outra instância', await button('Jogo já está aberto').isDisabled() && (await commandCalls('launch_game')).length === 2 && (await commandCalls('launch_controller_game')).length === 0);
  await page.evaluate(() => { window.__testBridge.controller.running = false; });
  await button('Ver restauração').click();
  await button('Atualizar diagnóstico').click(); await waitIdle();
  await button('Reparar componentes').click(); await button('Reparar agora').click(); await pending();
  check('Reparo mantém comando existente', (await commandCalls('repair_mod')).length === 1);
  await finish('success');
  check('Reparo não exibe o atalho exclusivo da instalação', await button('Abrir jogo').count() === 0);
  await button('Ver restauração').click();
  await button('Restaurar tudo').click(); await button('Restaurar originais').click(); await pending();
  check('Restauração usa o caminho selecionado', (await commandCalls('restore_mod')).at(-1).args.gamePath === 'C:\\fixture\\SoulReaver');
  await finish('success');
  check('Restauração não oferece abertura pós-instalação', await button('Abrir jogo').count() === 0);
  await button('Voltar à jornada').click();
  await button('Restauração').click();
  check('Estado atualizado desabilita restauração após retorno ao original', await button('Restaurar tudo').isDisabled());
  await button('Diagnóstico e controle').click(); await shot('06-diagnostico');
  await button('Habilitar suporte').click();
  check('DualSense exige confirmação antes de escrever', (await commandCalls('install_controller')).length === 0);
  await page.getByRole('dialog').getByRole('button', { name: 'Habilitar suporte', exact: true }).click(); await waitIdle();
  check('DualSense preserva instalação e estado real do backend', (await commandCalls('install_controller')).length === 1 && await button('Jogar com DualSense').isEnabled());
  await button('Jogar com DualSense').click();
  check('Abrir o jogo requer confirmação específica', await page.getByRole('heading', { name: 'Abrir Soul Reaver com DualSense?' }).isVisible() && (await commandCalls('launch_controller_game')).length === 0);
  await page.keyboard.press('Escape');
  await button('Remover suporte').click(); await page.getByRole('dialog').getByRole('button', { name: 'Remover suporte', exact: true }).click(); await waitIdle();
  check('Remoção DualSense mantém comando existente', (await commandCalls('remove_controller')).length === 1);
  await button('Alterar').click(); await page.getByLabel('Pasta do jogo').fill('C:\\fixture\\incompatible'); await button('Verificar').click(); await waitIdle();
  await button('Componentes').click();
  check('Edição incompatível bloqueia instalação', await button('Revisar instalação').isDisabled());
  await button('A jornada').click(); await shot('10-erro-de-inspecao');
  check('Erro de inspeção e recuperação cabem na abertura', await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1) && await button('Ver opções de recuperação').isVisible());
  await button('Restauração').click();
  check('Falha de inspeção mantém recuperação acessível', await button('Restaurar tudo').isEnabled());
  await button('Restaurar tudo').click();
  check('Recuperação sem inspeção informa a exigência de registros e backups', await page.getByText('A inspeção não foi concluída.', { exact: false }).isVisible());
  await page.keyboard.press('Escape');
  await button('Componentes').click();
  await button('Alterar').click(); await page.getByLabel('Pasta do jogo').fill('');
  check('Pasta vazia bloqueia verificação', await button('Verificar').isDisabled());
  await page.getByLabel('Pasta do jogo').fill('C:\\fixture\\SoulReaver'); await button('Verificar').click(); await waitIdle();
  await page.evaluate(() => { window.__testBridge.controller.running = true; });
  await button('Ver diagnóstico').click(); await waitIdle(); await button('Componentes').click();
  check('Jogo aberto bloqueia aplicação', await button('Revisar instalação').isDisabled());
  await page.evaluate(() => { sessionStorage.setItem('fixtureScenario', 'missing-bundle'); });
  await page.reload(); await waitIdle();
  check('Falha do pacote não esconde a instalação detectada', await page.getByText('Soul Reaver · Steam Classic', { exact: true }).isVisible());
  await button('Preparar instalação').click();
  check('Pacote ausente bloqueia revisão e permite tentar novamente', await button('Revisar instalação').isDisabled() && await button('Verificar pacote novamente').isVisible());
  await page.evaluate(() => { sessionStorage.removeItem('fixtureScenario'); });
  await page.reload(); await waitIdle();
  await page.setViewportSize({ width: 860, height: 680 }); await shot('07-compacto');
  check('Sem overflow horizontal em 860px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.setViewportSize({ width: 390, height: 844 }); await shot('08-mobile');
  check('Sem overflow horizontal em 390px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await button('Preparar instalação').click(); await shot('09-componentes-mobile');
  check('Componentes sem overflow horizontal em 390px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  check('Movimento reduzido respeitado', await page.locator('.primary').first().evaluate(e => getComputedStyle(e).transitionDuration === '0s'));
  check('Nenhuma requisição externa', external.length === 0);
  check('Console sem erros', errors.length === 0);
  await writeFile(join(output, 'report.json'), JSON.stringify({ target: 'Production React UI, Chromium, controlled Tauri transport', simulatedBackend: true, gameLaunched: false, checks, errors, external }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, errors, report: join(output, 'report.json') }));
} catch (error) {
  await shot('failure');
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: String(error), console: errors, state: await page.evaluate(() => ({ body: document.body.innerText, calls: window.__testBridge?.calls })) }, null, 2));
  throw error;
} finally { await browser.close(); }
