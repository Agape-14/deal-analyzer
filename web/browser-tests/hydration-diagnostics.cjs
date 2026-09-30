// Temporary diagnostics for the disposable production harness. This changes
// only the test browser's downloaded React script, never an application file.
async function captureHydrationDiagnostics(page) {
  const captures = [];
  page.on('console', message => {
    if (message.text().startsWith('HYDRATION_FIBER:')) {
      captures.push({ url: page.url(), fiber: JSON.parse(message.text().slice(16)) });
    }
  });
  await page.route(/\/_next\/static\/chunks\/[^/]+\.js$/, async route => {
    const response = await route.fetch();
    let source = await response.text();
    const start = source.indexOf('function rD(');
    if (start >= 0 && source.slice(start, start + 400).includes('418')) {
      const header = source.slice(start).match(/^function rD\((\w+)\)\{/);
      if (header) {
        if (!captures.some(capture => capture.source)) captures.push({ source: source.slice(start - 1600, start + 1600) });
        const argument = header[1];
        const diagnostic = "console.error('HYDRATION_FIBER:'+JSON.stringify((()=>{" +
          "const chain=[];const name=t=>typeof t==='string'?t:t?.displayName||t?.name||String(t);" +
          "const node=n=>n?.outerHTML?.slice(0,6000)||n?.nodeValue||null;" +
          "for(let p=" + argument + ";p&&chain.length<25;p=p.return){chain.push({tag:p.tag,type:name(p.type)," +
          "props:{className:p.pendingProps?.className,id:p.pendingProps?.id,role:p.pendingProps?.role}," +
          "node:node(p.stateNode),next:node(p.stateNode?.nextSibling)});}" +
          "return {readyState:document.readyState,chain};})()));";
        source = source.slice(0, start) + source.slice(start).replace(header[0], header[0] + diagnostic);
      }
    }
    await route.fulfill({ response, body: source });
  });
  return captures;
}

module.exports = { captureHydrationDiagnostics };
