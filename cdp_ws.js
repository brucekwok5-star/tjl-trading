const WebSocket = require('ws');

const USER_IDS = [
  '23814623', '233149641', '35974863', '7977289', '36331816',
  '34689347', '36129675', '135273', '21816942', '28337361',
  '29483438', '231473840', '15797713', '233135590', '232116503',
  '15848751', '15569912', '234147425', '232149973'
];

const TARGET_TAB = 'E8B324E43654DEF60C1E8F6A31776D3D'; // existing futu tab

function cdpSend(ws, id, method, params) {
  return new Promise((resolve, reject) => {
    const msgId = id || Math.random().toString(36).substr(2, 8);
    const msg = JSON.stringify({ id: msgId, method, params });
    
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 20000);
    
    ws.once('message', data => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(data.toString()));
      } catch(e) {
        reject(e);
      }
    });
    
    ws.send(msg);
  });
}

async function main() {
  // Connect to existing tab
  const wsUrl = `ws://127.0.0.1:18800/devtools/page/${TARGET_TAB}`;
  console.log(`Connecting to: ${wsUrl}`);
  
  const ws = new WebSocket(wsUrl);
  
  await new Promise((resolve, reject) => {
    ws.on('open', resolve);
    ws.on('error', reject);
  });
  
  console.log('Connected!');
  
  // Navigate to first profile
  const r1 = await cdpSend(ws, null, 'Page.navigate', { url: 'https://www.futugroup.com/u/23814623/' });
  console.log('Nav result:', JSON.stringify(r1));
  
  await new Promise(r => setTimeout(r, 5000));
  
  // Get frame tree
  const tree = await cdpSend(ws, null, 'Page.getFrameTree', {});
  console.log('Frame tree:', JSON.stringify(tree).substring(0, 500));
  
  // Evaluate
  const evalResult = await cdpSend(ws, null, 'Runtime.evaluate', {
    expression: 'document.body.innerText.substring(0, 3000)',
    returnByValue: true
  });
  console.log('Page text:', evalResult.result.result.value);
  
  ws.close();
}

main().catch(e => { console.error(e.message); process.exit(1); });
