// Read-only reuse of an existing Remotion installation; no npm install or downloads.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const req = JSON.parse(fs.readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, ''));
const local = createRequire(path.join(req.root, 'package.json'));
const {bundle} = local('@remotion/bundler');
const {openBrowser, selectComposition, renderMedia, makeCancelSignal} = local('@remotion/renderer');
const {cancelSignal, cancel} = makeCancelSignal();
function status(message) {
  const temp = req.progress + '.tmp';
  fs.writeFileSync(temp, JSON.stringify({message}));
  fs.renameSync(temp, req.progress);
}
let browser;
const watch = setInterval(() => {if (fs.existsSync(req.cancel)) cancel();}, 250);
(async () => {
  try {
    status('Preparing Remotion graphics (one renderer, no package downloads)...');
    const modules = path.join(req.root, 'node_modules');
    const serveUrl = await bundle({
      entryPoint: req.entry, rootDir: req.root, outDir: path.join(req.work, 'bundle'),
      publicDir: null, enableCaching: false, gitSource: null,
      webpackOverride: (config) => ({...config,
        resolve: {...config.resolve, modules: [modules, ...(config.resolve?.modules || [])]},
        resolveLoader: {...config.resolveLoader, modules: [modules, 'node_modules']},
      }),
    });
    if (fs.existsSync(req.cancel)) throw new Error('Rendering cancelled');
    browser = await openBrowser('chrome', {browserExecutable: req.browser});
    for (const [index, item] of req.items.entries()) {
      if (fs.existsSync(req.cancel)) throw new Error('Rendering cancelled');
      const inputProps = {...item.props, image: 'data:image/png;base64,' + fs.readFileSync(item.image).toString('base64')};
      const composition = await selectComposition({serveUrl, id: 'VideoPilotGraphic', inputProps, puppeteerInstance: browser});
      const temporary = path.join(req.work, `${item.id}.partial.mp4`);
      status(`Rendering graphics ${index + 1}/${req.items.length}: shot ${item.id}`);
      await renderMedia({composition, serveUrl, inputProps, outputLocation: temporary,
        codec: 'h264', pixelFormat: 'yuv420p', crf: 20, x264Preset: 'veryfast',
        concurrency: 1, disallowParallelEncoding: true, imageFormat: 'jpeg', jpegQuality: 90,
        muted: true, overwrite: true, puppeteerInstance: browser, cancelSignal,
        offthreadVideoCacheSizeInBytes: 64 * 1024 * 1024, mediaCacheSizeInBytes: 64 * 1024 * 1024,
        ffmpegOverride: ({args}) => [...args.slice(0, -1), '-threads', '2', args.at(-1)],
      });
      fs.renameSync(temporary, item.output.replace(/\.mp4$/, '.ready.mp4'));
    }
    status('Remotion clips rendered; checking output files.');
  } finally {
    clearInterval(watch);
    if (browser) await browser.close({silent: true});
  }
})().catch((error) => {console.error(error.stack || String(error)); process.exitCode = 1;});
