// Controlled Tauri transport for exercising the installer UI in a plain browser.
// Nothing here touches a real backend or a game: every answer is a fixture.
export function installBridge() {
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
      if (command === 'get_display_profile') return { desktop: '3840x2160', recommended: '3840x2160', featureLevel: '11_0', hardware: true, message: 'GPU Direct3D 11_0 detectada.' };
      if (command === 'inspect_installation') {
        // Mirrors the single-pass report of src-tauri/src/diagnostics.rs.
        const controller = structuredClone(bridge.controller);
        if (args.gamePath.includes('incompatible')) return { game: null, error: 'Edição não suportada: hash diferente.', diagnostics: null, controller, warnings: [] };
        bridge.game.path = args.gamePath;
        const failure = bridge.fail.diagnostics;
        const diagnostics = failure ? null : { path: args.gamePath, exeSha256: '9'.repeat(64), exeSupported: true, gameClosed: !bridge.controller.running, items: [{ id: 'voices', ok: bridge.game.status === 'installed', detail: `${bridge.game.replaced}/479 falas contra o backup` }, { id: 'controller', ok: false, detail: bridge.controller.message }] };
        return { game: structuredClone(bridge.game), error: null, diagnostics, controller, warnings: failure ? [failure] : [] };
      }
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
}
