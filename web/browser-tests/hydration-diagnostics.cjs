// Chromium-only diagnostics for the disposable production browser harness.
// Capture the failed React fiber while the exception is paused, without
// changing the shipped application or ignoring a recoverable render error.
async function captureHydrationDiagnostics(page) {
  const session = await page.context().newCDPSession(page);
  const captures = [];
  await session.send('Debugger.enable');
  await session.send('Debugger.setPauseOnExceptions', { state: 'all' });
  session.on('Debugger.paused', async event => {
    try {
      const mismatchFrame = event.callFrames.find(frame => frame.functionName === 'rD');
      if (!mismatchFrame && !/Minified React error #418|Hydration Mismatch Exception/.test(event.data?.description || '')) {
        if (captures.length < 5) captures.push({ exception: event.data?.description, frames: event.callFrames.slice(0, 6).map(frame => frame.functionName) });
        return;
      }
      const frame = mismatchFrame || event.callFrames[0];
      const fiber = await session.send('Debugger.evaluateOnCallFrame', {
        callFrameId: frame.callFrameId,
        expression: `(() => {
          const f = arguments[0];
          const name = t => typeof t === 'string' ? t : t?.displayName || t?.name || String(t);
          const node = n => n?.outerHTML?.slice(0, 6000) || n?.nodeValue || null;
          const chain = [];
          for (let p = f; p && chain.length < 25; p = p.return) {
            chain.push({ tag: p.tag, type: name(p.type), props: {
              className: p.pendingProps?.className, id: p.pendingProps?.id,
              value: p.pendingProps?.value, role: p.pendingProps?.role
            }, node: node(p.stateNode), next: node(p.stateNode?.nextSibling) });
          }
          return JSON.stringify(chain);
        })()`, returnByValue: true,
      });
      const nodes = [];
      for (const scope of frame.scopeChain) {
        if (!scope.object.objectId || scope.type === 'global') continue;
        const props = await session.send('Runtime.getProperties', { objectId: scope.object.objectId, ownProperties: true });
        for (const prop of props.result.filter(p => p.value?.subtype === 'node').slice(0, 10)) {
          const html = await session.send('Runtime.callFunctionOn', {
            objectId: prop.value.objectId, functionDeclaration: 'function() { return this.outerHTML?.slice(0, 6000) || this.nodeValue; }', returnByValue: true,
          });
          nodes.push({ name: prop.name, html: html.result.value });
        }
      }
      const source = await session.send('Debugger.getScriptSource', { scriptId: frame.location.scriptId });
      captures.push({ url: page.url(), fiber: fiber.result.value, evaluationError: fiber.exceptionDetails, nodes, source: source.scriptSource?.slice(33500, 36500) });
    } catch (error) {
      captures.push({ diagnosticError: error.message });
    } finally {
      await session.send('Debugger.resume').catch(() => {});
    }
  });
  return captures;
}

module.exports = { captureHydrationDiagnostics };
