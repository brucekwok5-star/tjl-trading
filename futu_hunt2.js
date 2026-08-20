const WebSocket = require('/tmp/ws_temp/node_modules/ws');
const fs = require('fs');
const PAGE_ID = 'D054201FF0BF6A1917E4704B913D8ADB';
const STOCKS = [["00012", "\u6052\u57fa\u5730\u7522"], ["00005", "\u6ed9\u8c50\u63a7\u80a1"], ["09988", "\u963f\u91cc\u5df4\u5df4-W"], ["02318", "\u4e2d\u570b\u5e73\u5b89"], ["00780", "\u540c\u7a0b\u65c5\u884c"], ["03968", "\u62db\u5546\u9280\u884c"], ["03690", "\u7f8e\u5718-W"], ["06160", "\u767e\u6fdf\u795e\u5dde"], ["03296", "\u83ef\u52e4\u6280\u8853"], ["01288", "\u8fb2\u696d\u9280\u884c"], ["03908", "\u4e2d\u91d1\u516c\u53f8"], ["00002", "\u4e2d\u96fb\u63a7\u80a1"], ["02601", "\u4e2d\u570b\u592a\u4fdd"], ["01299", "\u53cb\u90a6\u4fdd\u96aa"], ["09888", "\u767e\u5ea6\u96c6\u5718-SW"], ["00175", "\u5409\u5229\u6c7d\u8eca"], ["09961", "\u651c\u7a0b\u96c6\u5718-S"], ["02162", "\u5eb7\u8afe\u4e9e-B"], ["03618", "\u91cd\u6176\u8fb2\u6751\u5546\u696d\u9280\u884c"], ["09633", "\u8fb2\u592b\u5c71\u6cc9"], ["02571", "\u8cfd\u76ee\u79d1\u6280"], ["09618", "\u4eac\u6771\u96c6\u5718-SW"], ["02256", "\u548c\u8b7d-B"], ["01368", "\u7279\u6b65\u570b\u969b"], ["02588", "\u4e2d\u9280\u822a\u7a7a\u79df\u8cc3"], ["02319", "\u8499\u725b\u4e73\u696d"], ["03899", "\u4e2d\u96c6\u5b89\u745e\u79d1"], ["00027", "\u9280\u6cb3\u5a1b\u6a02"], ["00688", "\u4e2d\u570b\u6d77\u5916\u767c\u5c55"], ["01109", "\u83ef\u6f64\u7f6e\u5730"], ["06862", "\u6d77\u5e95\u6488"], ["06110", "\u6ed4\u640f"], ["00386", "\u4e2d\u570b\u77f3\u6cb9\u5316\u5de5\u80a1\u4efd"], ["01876", "\u767e\u5a01\u4e9e\u592a"], ["00135", "\u6606\u4f96\u80fd\u6e90"], ["02823", "\u5b89\u78a9A50"], ["00291", "\u83ef\u6f64\u5564\u9152"], ["00100", "MINIMAX-W"], ["01211", "\u6bd4\u4e9e\u8fea\u80a1\u4efd"], ["03360", "\u9060\u6771\u5b8f\u4fe1"], ["09973", "\u5947\u745e\u6c7d\u8eca"], ["00700", "\u9a30\u8a0a\u63a7\u80a1"], ["00992", "\u806f\u60f3\u96c6\u5718"], ["00669", "\u5275\u79d1\u5be6\u696d"], ["03750", "\u5be7\u5fb7\u6642\u4ee3"], ["00388", "\u9999\u6e2f\u4ea4\u6613\u6240"], ["00016", "\u65b0\u9d3b\u57fa\u5730\u7522"], ["02883", "\u4e2d\u6d77\u6cb9\u7530\u670d\u52d9"], ["00038", "\u7b2c\u4e00\u62d6\u62c9\u6a5f\u80a1\u4efd"], ["02388", "\u4e2d\u9280\u9999\u6e2f"]];
const EXPR = `const items=document.querySelectorAll('[class*=nnq-list-item]');const posts=[];for(let i=0;i<items.length&&i<20;i++){  const el=items[i];  const text=(el.innerText||'').trim();  if(text.length>3){    const lines=text.split('\\n').filter(l=>l.trim().length>0);    posts.push({text,lines:lines.slice(0,5)});  }}JSON.stringify(posts)`;
const LOG = '/tmp/futu_hunt2.log';
const OUT = '/tmp/futu_hunt2.json';

let id = 0, cur = 0, data = {}, ws;

function log(m) {
    fs.appendFileSync(LOG, cur + '/' + STOCKS.length + ' ' + STOCKS[cur][0] + ' ' + STOCKS[cur][1] + ': ' + m + '\n');
    console.log(cur + '/' + STOCKS.length + ' ' + STOCKS[cur][0] + ' ' + STOCKS[cur][1] + ': ' + m);
}

function send(m, p) {
    return new Promise((res, rej) => {
        ws.send(JSON.stringify({id: ++id, method: m, params: p}));
        const h = msg => {
            const d = JSON.parse(msg);
            if (d.id === id) { ws.removeListener('message', h); res(d); }
        };
        ws.on('message', h);
        setTimeout(() => rej(new Error('timeout ' + m)), 25000);
    });
}

async function next() {
    if (cur >= STOCKS.length) {
        const total = Object.values(data).reduce((s, v) => s + (v.posts?.length||0), 0);
        console.log('=== DONE ' + Object.keys(data).length + ' stocks ' + total + ' posts ===');
        fs.writeFileSync(OUT, JSON.stringify(data, null, 2));
        ws.close(); process.exit(0); return;
    }
    const [code, name] = STOCKS[cur];
    try {
        await send('Page.navigate', {url: 'https://www.futunn.com/hk/stock/' + code + '-HK/community'});
        await new Promise(r => setTimeout(r, 4500));
        const r = await send('Runtime.evaluate', {expression: EXPR});
        const posts = r.result?.result?.value;
        if (posts) {
            const p = JSON.parse(posts);
            data[code] = {name, posts: p};
            log(p.length + ' posts');
        } else { data[code] = {name, posts:[]}; log('0'); }
    } catch(e) {
        data[code] = {name, posts:[], err: e.message.slice(0,40)};
        log('ERR: ' + e.message.slice(0,40));
    }
    cur++; next();
}

ws = new WebSocket('ws://127.0.0.1:18800/devtools/page/' + PAGE_ID);
ws.on('error', e => console.error('WS:', e.message));
ws.on('open', () => next());
