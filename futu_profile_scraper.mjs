import { WebSocket } from 'ws';

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

const KEYWORDS = ['美股', 'US', 'NASDAQ', 'NYSE', '美股今晚', '今晚美股', '特斯拉', '苹果', '英伟达', 'AMD', '今晚涨跌', 'TSLA', 'AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NFLX', '今晚', '走势', '预测', '分析'];

function send(ws, method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = Date.now() + Math.random();
    const msg = JSON.stringify({ id, method, params });
    const timeout = setTimeout(() => reject(new Error(`Timeout for ${method}`)), 30000);
    ws.on('message', (data) => {
      try {
        const resp = JSON.parse(data.toString());
        if (resp.id === id) {
          clearTimeout(timeout);
          resolve(resp.result);
        }
      } catch (e) {}
    });
    ws.send(msg);
  });
}

function wait(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function extractPosts(ws) {
  // Try multiple selectors for posts on Futu
  const selectors = [
    '.post-item',
    '.article-item',
    '[class*="post"]',
    '[class*="article"]',
    '.feed-item',
    '[class*="dynamic"]',
    '[class*="content"]',
    'article',
    '.main-content [class*="item"]',
    '.post-list [class*="item"]',
  ];

  let posts = [];
  for (const sel of selectors) {
    try {
      const result = await send(ws, 'Runtime.evaluate', {
        expression: `
          (function() {
            const items = document.querySelectorAll('${sel}');
            return Array.from(items).map(el => {
              const text = el.innerText || el.textContent || '';
              const date = el.querySelector('[class*="time"], [class*="date"], [class*="time"], time, [class*="create"]')?.innerText || '';
              const title = el.querySelector('h1, h2, h3, h4, [class*="title"]')?.innerText || '';
              return { text, date, title, sel: '${sel}' };
            }).filter(i => i.text.trim().length > 20);
          })()
        `,
        returnByValue: true,
      });
      if (result?.result?.value?.length > 0) {
        posts = result.result.value;
        console.log(`  Found ${posts.length} posts with selector: ${sel}`);
        break;
      }
    } catch(e) {}
  }

  return posts;
}

async function getFullPageContent(ws) {
  const result = await send(ws, 'Runtime.evaluate', {
    expression: `
      (function() {
        // Try to get the main content area
        const main = document.querySelector('.main-content, .profile-content, .feed, .posts, [class*="feed"], [class*="post"]');
        if (main) return main.innerText;
        return document.body.innerText;
      })()
    `,
    returnByValue: true,
  });
  return result?.result?.value || '';
}

async function scrollAndExtract(ws) {
  // Scroll down to load more content
  await send(ws, 'Runtime.evaluate', {
    expression: `window.scrollTo(0, document.body.scrollHeight / 2)`,
    returnByValue: false,
  });
  await wait(2000);
  
  await send(ws, 'Runtime.evaluate', {
    expression: `window.scrollTo(0, document.body.scrollHeight)`,
    returnByValue: false,
  });
  await wait(2000);
}

async function checkProfile(ws, user) {
  console.log(`\n=== Checking user: ${user.name} (${user.id}) ===`);
  
  try {
    // Navigate to profile
    await send(ws, 'Page.navigate', { url: `https://q.futunn.com/profile/${user.id}` });
    await wait(4000);
    
    // Scroll to load content
    await scrollAndExtract(ws);
    
    // Get page content
    const content = await getFullPageContent(ws);
    
    // Filter for US stock related content
    const usStockPosts = [];
    const lines = content.split('\n').filter(l => l.trim().length > 10);
    
    for (const line of lines) {
      const hasKeyword = KEYWORDS.some(k => line.includes(k));
      if (hasKeyword) {
        usStockPosts.push(line.trim());
      }
    }
    
    if (usStockPosts.length > 0) {
      console.log(`  Found ${usStockPosts.length} lines with US stock keywords:`);
      usStockPosts.slice(0, 10).forEach(p => console.log(`    - ${p.substring(0, 200)}`));
    } else {
      console.log(`  No US stock keywords found in page content`);
    }
    
    // Try to get post items specifically
    const posts = await extractPosts(ws);
    
    const relevantPosts = posts.filter(p => {
      const combined = (p.text + ' ' + p.title).toLowerCase();
      return KEYWORDS.some(k => combined.includes(k.toLowerCase()));
    });
    
    if (relevantPosts.length > 0) {
      console.log(`  Found ${relevantPosts.length} relevant post items`);
      return { user, posts: relevantPosts };
    }
    
    return { user, posts: [], usStockLines: usStockPosts };
  } catch(e) {
    console.log(`  Error: ${e.message}`);
    return { user, error: e.message };
  }
}

async function main() {
  console.log('Connecting to Chrome DevTools Protocol...');
  
  const ws = new WebSocket(WS_URL);
  
  await new Promise((resolve, reject) => {
    ws.on('open', resolve);
    ws.on('error', reject);
  });
  
  console.log('Connected! Starting profile checks...\n');
  
  const results = [];
  
  for (const user of USERS) {
    const result = await checkProfile(ws, user);
    results.push(result);
    await wait(1500); // delay between profiles
  }
  
  ws.close();
  
  // Summary
  console.log('\n\n========== SUMMARY ==========\n');
  for (const r of results) {
    const name = r.user.name;
    if (r.posts?.length > 0) {
      console.log(`\n【${name}】 Found ${r.posts.length} US stock related posts:`);
      r.posts.forEach((p, i) => {
        console.log(`  Post ${i+1}: ${p.title || 'No title'}`);
        console.log(`  Content: ${p.text.substring(0, 300)}...`);
        console.log(`  Date: ${p.date}`);
      });
    } else if (r.usStockLines?.length > 0) {
      console.log(`\n【${name}】 Found ${r.usStockLines.length} lines with US stock keywords:`);
      r.usStockLines.forEach((l, i) => console.log(`  ${i+1}: ${l.substring(0, 200)}`));
    } else if (r.error) {
      console.log(`\n【${name}】 ERROR: ${r.error}`);
    } else {
      console.log(`\n【${name}】 No US stock predictions found`);
    }
  }
}

main().catch(console.error);
