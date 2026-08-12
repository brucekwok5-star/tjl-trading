const WebSocket = require('ws');

const WS_URL = process.argv[2];
const MODE = process.argv[3] || 'extract';

let ws;
let msgId = 1;
let pending = new Map();

function cdp(method, params) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    ws.send(JSON.stringify({id, method, params}));
    const timeout = setTimeout(() => reject(new Error('Timeout: ' + method)), 30000);
    pending.set(id, {resolve, reject, timeout});
  });
}

ws = new WebSocket(WS_URL);

ws.on('open', async () => {
  try {
    if (MODE === 'nav') {
      await cdp('Page.navigate', {url: process.argv[4] || 'https://www.futunn.com/hk/stock/00992-HK/community'});
      console.log('NAVIGATED');
      ws.close();
      process.exit(0);
    } else {
      // Extract — scroll to load, wait, then scrape
      await cdp('Runtime.evaluate', {
        expression: 'window.scrollTo(0, document.body.scrollHeight)',
        awaitPromise: false
      });
      await new Promise(r => setTimeout(r, 3000));

      const r = await cdp('Runtime.evaluate', {
        expression: `(function() {
  const items = document.querySelectorAll('.nnq-list-item');
  const out = [];
  items.forEach((item, idx) => {
    if (idx >= 20) return;
    const uid = item.getAttribute('uid');
    const fid = item.getAttribute('fid');

    // Extract only the TOP-LEVEL post text (before any replies)
    const allText = (item.innerText || '').trim();
    const lines = allText.split(/\n|\r/);
    const cleanLines = [];
    for (const l of lines) {
      const trimmed = l.trim();
      if (!trimmed) continue;
      // Skip header/meta lines
      if (/^(分享心情|最新|推薦|\d+[分時日年]前)$/.test(trimmed)) continue;
      // Stop at first reply line ("Name : reply text")
      // Pattern: short text followed by " :" signals a reply
      if (/^[^,，\n]{1,30}\s+:\s/.test(trimmed)) break;
      cleanLines.push(trimmed);
    }
    const text = cleanLines.join(' ').trim();

    const timeEl = item.querySelector('.time, [class*="time"]');
    const time = timeEl ? (timeEl.innerText || '').trim() : '';
    const userLinks = item.querySelectorAll('a[href*="/profile/"]');
    const users = [];
    userLinks.forEach(l => {
      const match = (l.href || '').match(/\\/profile\\/(\\d+)/);
      if (match && match[1]) {
        users.push({id: match[1], name: (l.innerText || '').trim()});
      }
    });
    if (uid && text.length > 5) {
      out.push({uid, fid, text: text.substring(0, 400), time, users});
    }
  });
  return JSON.stringify(out);
})()`,
        returnByValue: true
      });

      const data = (r && r.result && r.result.result && r.result.result.value) || '[]';
      console.log(data);
      ws.close();
      process.exit(0);
    }
  } catch(e) {
    console.error('ERROR: ' + e.message);
    ws.close();
    process.exit(1);
  }
});

ws.on('message', (data) => {
  const msg = JSON.parse(data.toString());
  if (msg.id && pending.has(msg.id)) {
    const {resolve, timeout} = pending.get(msg.id);
    clearTimeout(timeout);
    pending.delete(msg.id);
    resolve(msg);
  }
});

ws.on('error', (e) => {
  console.error('WS_ERROR: ' + e.message);
  process.exit(1);
});
