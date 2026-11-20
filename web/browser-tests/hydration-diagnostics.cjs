const fs = require('node:fs/promises');
const path = require('node:path');

// Explicitly gated, temporary instrumentation of disposable CI build output.
// No repository/application source or production service is changed.
async function instrumentProductionHydration() {
  if (process.env.BROWSER_TEST_MODE !== 'synthetic' || process.env.BROWSER_HYDRATION_TRACE !== '1' || process.env.BROWSER_DIAGNOSTIC === '1') return;
  const root = path.resolve('.next/static/chunks');
  for (const file of await fs.readdir(root, { recursive: true })) {
    if (!file.endsWith('.js')) continue;
    const chunk = path.join(root, file);
    let source = await fs.readFile(chunk, 'utf8');
    const start = source.indexOf('function rD(');
    if (start < 0 || !source.slice(start, start + 400).includes('418')) continue;
    const header = source.slice(start).match(/^function rD\((\w+)\)\{/);
    if (!header) continue;
    console.log('HYDRATION_SOURCE:' + source.slice(start - 1600, start + 1600));
    const argument = header[1];
    const diagnostic = "console.error('HYDRATION_FIBER:'+JSON.stringify((()=>{" +
      "const chain=[];const name=t=>typeof t==='string'?t:t?.displayName||t?.name||String(t);" +
      "const node=n=>n?.outerHTML?.slice(0,6000)||n?.nodeValue||null;" +
      "for(let p=" + argument + ";p&&chain.length<25;p=p.return){chain.push({tag:p.tag,type:name(p.type)," +
      "props:{className:p.pendingProps?.className,id:p.pendingProps?.id,role:p.pendingProps?.role}," +
      "node:node(p.stateNode),tail:node(p.stateNode?.lastChild),next:node(p.stateNode?.nextSibling)});}" +
      "return {readyState:document.readyState,chain};})()));";
    source = source.slice(0, start) + source.slice(start).replace(header[0], header[0] + diagnostic);
    await fs.writeFile(chunk, source);
  }
}

async function captureHydrationDiagnostics(page) {
  const captures = [];
  page.on('console', message => {
    if (message.text().startsWith('HYDRATION_FIBER:')) {
      captures.push({ url: page.url(), fiber: JSON.parse(message.text().slice(16)) });
    }
  });
  return captures;
}

module.exports = { captureHydrationDiagnostics, instrumentProductionHydration };
