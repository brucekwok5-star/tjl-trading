import WebSocket from 'ws';

const WS_URL = 'ws://127.0.0.1:18800/devtools/page/16B6E4C9A5B1DC1D41C9C92ED84E2083';

const USERS = [
  { id: '16459220', name: 'Zona' },
  { id: '18099215', name: '杭州吕布' },
  { id: '14042366', name: '人B失格' },
  { id: '22379942', name: '用爱感动A股' },
  { id: '27406798', name: '嘉运久赢' },
  { id: '26136151', name: 'Hanchiller' },
  { id: '36078245', name: '万花美偲' },
  { id: '2854700', name: '六爷漫谈' },
  { id: '7371606', name: 'User7371606' },
  { id: '231455402', name: 'User231455402' },
  { id: '3226989', name: 'User3226989' },
  { id: '21058120', name: 'User21058120' },
  { id: '11891989', name: 'User11891989' },
  { id: '17363266', name: 'User17363266' },
  { id: '17958286', name: 'User17958286' },
  { id: '231721959', name: 'User231721959' },
];

const KEYWORDS = ['美股', 'US', 'NASDAQ', 'NYSE', '美股今晚', '今晚美股', '特斯拉', '苹果', '英伟达', 'AMD', '今晚涨跌', 'TSLA', 'AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NFLX', '今晚', '走势', '预测', '分析', '标普', '纳指', '道琼斯', '加息', '降息', '财报', '业绩', '盈利', '亏损', '财报季', '个股', '涨停', '跌停', '大盘', '期权', 'CTA', '蔚来', '小鹏', '理想', '京东', '百度', '阿里巴巴', '拼多多', '哔哩', '知乎', '斗鱼', '虎牙'];

class CDPClient {
  constructor(wsUrl) {
    this.ws = null;
    this.wsUrl = wsUrl;
    this.pending = new Map();
    this.nextId = 1;
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.on('open', () => resolve());
      this.ws.on('error', reject);
      this.ws.on('message', (data) => {
        try {
          const msg = JSON.parse(data.toString());
          if (msg.id && this.pending.has(msg.id)) {
            const { resolve: res, reject: rej, timeout } = this.pending.get(msg.id);
            clearTimeout(timeout);
            this.pending.delete(msg.id);
            if (msg.result) res(msg.result);
            else if (msg.error) rej(new Error(msg.error.message || JSON.stringify(msg.error)));
            else res(msg);
          }
        } catch (e) {}
      });
      this.ws.on('error', (e) => {
        for (const [, { reject }] of this.pending) reject(e);
        this.pending.clear();
      });
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const msg = JSON.stringify({ id, method, params });
      const timeout = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`Timeout for ${method}`));
        }
      }, 30000);
      this.pending.set(id, { resolve, reject, timeout });
      this.ws.send(msg);
    });
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

function wait(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function extractPageContent(cdp) {
  // Try to get the full page text content
  const result = await cdp.send('Runtime.evaluate', {
    expression: `
      (function() {
        // Get body text, filtering out navigation and footer
        const body = document.body.innerText || '';
        
        // Try to find main content area
        const mainSelectors = [
          '.main-content', '.profile-main', '.feed-main',
          '[class*="main"]', 'main', 'article',
          '.post-list', '.article-list', '[class*="post"]'
        ];
        
        let content = '';
        for (const sel of mainSelectors) {
          const el = document.querySelector(sel);
          if (el) {
            content = el.innerText || el.textContent || '';
            if (content.length > 100) break;
          }
        }
        
        if (!content || content.length < 100) {
          content = body;
        }
        
        return content.substring(0, 20000);
      })()
    `,
    returnByValue: true,
    awaitPromise: false,
  });
  
  return result?.result?.value || '';
}

async function extractPosts(cdp) {
  const selectors = [
    '.post-item', '.article-item', '.feed-item',
    '[class*="post-item"]', '[class*="article-item"]',
    '[class*="feed-item"]', 'article'
  ];
  
  for (const sel of selectors) {
    try {
      const result = await cdp.send('Runtime.evaluate', {
        expression: `
          (function() {
            const items = document.querySelectorAll('${sel}');
            if (items.length === 0) return [];
            return Array.from(items).slice(0, 30).map((el, i) => {
              const text = (el.innerText || el.textContent || '').trim();
              const dateEl = el.querySelector('[class*="time"], [class*="date"], [class*="create"], time');
              const date = dateEl ? (dateEl.innerText || dateEl.textContent || '') : '';
              const titleEl = el.querySelector('h1, h2, h3, h4, [class*="title"], [class*="header"]');
              const title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
              return { text: text.substring(0, 1000), date: date.substring(0, 100), title: title.substring(0, 200) };
            }).filter(i => i.text.length > 30);
          })()
        `,
        returnByValue: true,
        awaitPromise: false,
      });
      const posts = result?.result?.value || [];
      if (posts.length > 0) return posts;
    } catch(e) {}
  }
  return [];
}

async function checkUser(cdp, user) {
  process.stdout.write(`\n=== ${user.name} (${user.id}) ===\n`);
  
  try {
    // Navigate
    await cdp.send('Page.navigate', { url: `https://q.futunn.com/profile/${user.id}` });
    await wait(5000);
    
    // Scroll
    await cdp.send('Runtime.evaluate', {
      expression: `window.scrollTo(0, 500)`,
      awaitPromise: false,
    });
    await wait(1500);
    await cdp.send('Runtime.evaluate', {
      expression: `window.scrollTo(0, document.body.scrollHeight)`,
      awaitPromise: false,
    });
    await wait(2000);
    
    // Get text content
    const text = await extractPageContent(cdp);
    
    // Filter for relevant content
    const relevantLines = text.split('\n').filter(l => {
      const trimmed = l.trim();
      if (trimmed.length < 10) return false;
      return KEYWORDS.some(k => trimmed.includes(k));
    });
    
    if (relevantLines.length > 0) {
      process.stdout.write(`  FOUND ${relevantLines.length} lines with US stock keywords\n`);
      const uniqueLines = [...new Set(relevantLines)].slice(0, 15);
      uniqueLines.forEach(l => process.stdout.write(`    >> ${l.trim().substring(0, 200)}\n`));
      return { user, found: true, lines: uniqueLines };
    } else {
      process.stdout.write(`  No US stock keywords found\n`);
      return { user, found: false };
    }
  } catch(e) {
    process.stdout.write(`  ERROR: ${e.message}\n`);
    return { user, error: e.message };
  }
}

async function main() {
  process.stdout.write('Connecting to Chrome...\n');
  const cdp = new CDPClient(WS_URL);
  
  try {
    await cdp.connect();
    process.stdout.write('Connected!\n');
    
    for (const user of USERS) {
      const result = await checkUser(cdp, user);
      await wait(1000);
    }
    
    process.stdout.write('\n\n========== DONE ==========\n');
  } finally {
    cdp.close();
  }
}

main().catch(e => {
  process.stderr.write(`Fatal: ${e.message}\n`);
  process.exit(1);
});
