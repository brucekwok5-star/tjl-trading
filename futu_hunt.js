const WebSocket = require('ws');
const WS_URL = process.argv[2];
const MODE = process.argv[3];

let ws;
let msgId = 1;
const pending = new Map();

function cdp(method, params, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    ws.send(JSON.stringify({id, method, params}));
    const timeout = setTimeout(() => reject(new Error('Timeout: ' + method)), timeoutMs);
    pending.set(id, {resolve, reject, timeout});
  });
}

ws = new WebSocket(WS_URL);
ws.on('open', async () => {
  try {
    if (MODE === 'nav') {
      const url = process.argv[4];
      const r = await cdp('Page.navigate', {url}, 60000);
      console.log('NAVIGATED');
    } else if (MODE === 'extract') {
      await cdp('Runtime.evaluate', {
        expression: 'window.scrollTo(0, document.body.scrollHeight)',
        awaitPromise: false
      });
      await new Promise(r => setTimeout(r, 2000));

      const r = await cdp('Runtime.evaluate', {
        expression: `(function() {
  const items = document.querySelectorAll('.nnq-list-item');
  const out = [];
  items.forEach((item, idx) => {
    if (idx >= 20) return;
    const uid = item.getAttribute('uid');
    const fid = item.getAttribute('fid');
    let text = '';
    const contentEls = item.querySelectorAll('.content, [class*="content"]');
    contentEls.forEach(el => {
      const t = (el.innerText || '').trim();
      if (t.length > text.length) text = t;
    });
    if (!text || text.length < 5) {
      const allText = (item.innerText || '').trim();
      const lines = allText.split('\\n').filter(l => {
        l = l.trim();
        if (!l) return false;
        if (l.includes('分享心情') || l.includes('最新') || l.includes('推薦')) return false;
        return true;
      });
      text = lines.join(' ').trim();
    }
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
    } else if (MODE === 'create_page') {
      const r = await cdp('Target.createTarget', {url: 'about:blank'});
      const targetId = r.result && r.result.targetId;
      console.log(targetId || 'ERROR');
    }
    ws.close();
    process.exit(0);
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
ws.on('error', (e) => { console.error('WS_ERROR: ' + e.message); process.exit(1); });
