#!/usr/bin/env python3
"""
Futu HK 50-Stock CDP Scraper
Relaunches Chrome + OTP login + scrapes all 50 HK stocks
Saves to ~/.openclaw/workspace/futu_hk_full_50.json
"""

import subprocess, json, time, urllib.request, os

WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
DATA_FILE = os.path.join(WORKSPACE, "futu_hk_full_50.json")
LOG_FILE = "/tmp/futu_scrape.log"

TICKERS = [
    ["00700","騰訊"],["02800","盈富"],["03033","恒科"],["02513","智譜"],
    ["07709","南方恒科2xL"],["00100","MINIMAX"],["00981","中芯"],["01347","華虹"],
    ["09988","阿里"],["01888","建滔積層板"],["00992","聯想"],["02828","A50"],
    ["06869","瀾起"],["09992","泡泡瑪特"],["03308","中際旭創"],["01810","小米"],
    ["03986","兆易創新"],["06166","建滔"],["01299","友邦"],["02476","快狗"],
    ["00148","建滔集團"],["06809","瀾起科技"],["09903","中海"],["02899","紫金"],
    ["02318","平安"],["02269","藥明"],["03690","美團"],["01548","里斯"],
    ["06160","百濟"],["01093","石藥"],["02628","中國人壽"],["09999","網易"],
    ["01378","宏利"],["01024","KDS"],["02359","藥明康德"],["00388","港交所"],
    ["09618","京東"],["03330","碧桂園"],["01801","信達"],["09926","BIDU"],
    ["03750","寧德"],["03896","金蝶"],["00005","匯豐"],["07747","WACBI"],
    ["00939","建行"],["02259","藥明生物"],["00322","康師傅"],["00883","中海油"],
    ["02600","中國鋁業"],["02099","CRCC"]
]

# CRITICAL: Use \\n (2 backslashes in Python) so JSON encodes as \\n -> JS sees literal \n
EXPR = (
    "const items=document.querySelectorAll('[class*=\"nnq-list-item\"]');"
    "const posts=[];"
    "for(let i=0;i<items.length&&i<20;i++){"
    "  const el=items[i];"
    "  const text=(el.innerText||'').trim();"
    "  if(text.length>30){"
    "    const lines=text.split('\\n').filter(l=>l.trim().length>0);"
    "    posts.push({"
    "      nick:(lines[0]||'').substring(0,50),"
    "      content:lines.slice(1).join(' | ').substring(0,400),"
    "      time:lines.find(l=>/分鐘前|小時前|剛剛/.test(l))||''"
    "    });"
    "  }"
    "}}"
    "({count:posts.length,posts,url:window.location.href,title:document.title})"
)

def log(msg):
    print(msg)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")

def launch_chrome():
    log("[1/5] Launching Chrome with CDP port 18800...")
    subprocess.run(["killall", "Google Chrome"], capture_output=True)
    time.sleep(2)
    subprocess.Popen(
        ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
         "--remote-debugging-port=18800",
         "--user-data-dir=/Users/jaydensmac/.openclaw/workspace/futu_chrome_data",
         "--no-first-run", "--no-default-browser-check"],
        stdout=open("/tmp/chrome_debug.log","w"),
        stderr=subprocess.DEVNULL
    )
    for _ in range(15):
        try:
            urllib.request.urlopen("http://127.0.0.1:18800/", timeout=1)
            log("  Chrome ready")
            return
        except:
            time.sleep(1)
    raise RuntimeError("Chrome failed to start")

def get_page_id():
    pages = json.loads(urllib.request.urlopen("http://127.0.0.1:18800/json", timeout=5).read())
    return [p["id"] for p in pages if p.get("type") == "page"][0]

def login_and_verify(page_id):
    """Login via OTP then verify."""
    log("[2/5] Checking login state...")
    
    # First check if already logged in
    script = (
        "const WebSocket = require('/tmp/ws_temp/node_modules/ws');\n"
        "const ws = new WebSocket('ws://127.0.0.1:18800/devtools/page/" + page_id + "');\n"
        "let msgId=1;\n"
        "ws.on('open', async () => {\n"
        "  async function send(m,p) {\n"
        "    return new Promise((res,rej) => {\n"
        "      const id=msgId++;\n"
        "      ws.send(JSON.stringify({id,method:m,params:p||{}}));\n"
        "      const t=setTimeout(()=>{ws.close();rej(new Error('Timeout'));},20000);\n"
        "      const h=(d)=>{const m=JSON.parse(d.toString());if(m.id===id){ws.off('message',h);clearTimeout(t);res(m.result);}};\n"
        "      ws.on('message',h);\n"
        "    });\n"
        "  }\n"
        "  await send('Page.navigate',{url:'https://www.futunn.com/hk/stock/00700-HK/community'});\n"
        "  await new Promise(r=>setTimeout(r,8000));\n"
        "  const u=await send('Runtime.evaluate',{expression:'window.location.href',returnByValue:true});\n"
        "  const title=await send('Runtime.evaluate',{expression:'document.title',returnByValue:true});\n"
        "  console.log('URL:'+JSON.stringify(u?.result?.value));\n"
        "  console.log('TITLE:'+JSON.stringify(title?.result?.value));\n"
        "  ws.close();\n"
        "  process.exit(0);\n"
        "});\n"
        "ws.on('error',e=>{console.error('ERR:'+e.message);process.exit(1);});\n"
        "setTimeout(()=>process.exit(2),20000);\n"
    )
    with open("/tmp/check_login.js","w") as f:
        f.write(script)
    r = subprocess.run(["node","/tmp/check_login.js"], capture_output=True, text=True, timeout=25)
    log(f"  State: {r.stdout}")
    
    if "00700" in r.stdout or "騰訊" in r.stdout:
        log("  Login: OK")
        return True
    
    # Need to login - OTP flow
    log("[3/5] Session expired. Starting OTP login...")
    log("  Navigate to passport.futunn.com")
    login_script = (
        "const WebSocket = require('/tmp/ws_temp/node_modules/ws');\n"
        "const ws = new WebSocket('ws://127.0.0.1:18800/devtools/page/" + page_id + "');\n"
        "let msgId=1;\n"
        "ws.on('open', async () => {\n"
        "  async function send(m,p) {\n"
        "    return new Promise((res,rej) => {\n"
        "      const id=msgId++;\n"
        "      ws.send(JSON.stringify({id,method:m,params:p||{}}));\n"
        "      const t=setTimeout(()=>{ws.close();rej(new Error('Timeout'));},25000);\n"
        "      const h=(d)=>{const m=JSON.parse(d.toString());if(m.id===id){ws.off('message',h);clearTimeout(t);res(m.result);}};\n"
        "      ws.on('message',h);\n"
        "    });\n"
        "  }\n"
        "  await send('Page.navigate',{url:'https://passport.futunn.com/'});\n"
        "  await new Promise(r=>setTimeout(r,5000));\n"
        "  \n"
        "  // Click phone tab\n"
        "  const tabs=await send('Runtime.evaluate',{expression:`(function(){const els=document.querySelectorAll('[class*=tab],button');for(const el of els){if(el.innerText&&el.innerText.includes('手機')){el.click();return 'clicked';}}return 'not found';})()`,returnByValue:true});\n"
        "  console.log('Phone tab:', tabs?.result?.value);\n"
        "  await new Promise(r=>setTimeout(r,2000));\n"
        "  \n"
        "  // Fill phone number\n"
        "  const inputs=await send('Runtime.evaluate',{expression:`(function(){const els=document.querySelectorAll('input');for(const el of els){if(el.type==='tel'||el.placeholder?.includes('機')||el.placeholder?.includes('phone')){el.value='90130881';el.dispatchEvent(new Event('input',{bubbles:true}));return 'filled:'+el.placeholder;}}return 'not found';})()`,returnByValue:true});\n"
        "  console.log('Phone input:', inputs?.result?.value);\n"
        "  await new Promise(r=>setTimeout(r,1000));\n"
        "  \n"
        "  // Click send code\n"
        "  const sendBtn=await send('Runtime.evaluate',{expression:`(function(){const els=document.querySelectorAll('button,div[role=button]');for(const el of els){if(el.innerText?.includes('獲取')||el.innerText?.includes('發送')||el.innerText?.includes('驗證')){el.click();return 'clicked:'+el.innerText;}}return 'not found';})()`,returnByValue:true});\n"
        "  console.log('Send code btn:', sendBtn?.result?.value);\n"
        "  await new Promise(r=>setTimeout(r,1000));\n"
        "  \n"
        "  // Check URL\n"
        "  const url=await send('Runtime.evaluate',{expression:'window.location.href',returnByValue:true});\n"
        "  console.log('URL:',url?.result?.value);\n"
        "  \n"
        "  ws.close();\n"
        "  process.exit(0);\n"
        "});\n"
        "ws.on('error',e=>{console.error('ERR:'+e.message);process.exit(1);});\n"
        "setTimeout(()=>process.exit(2),30000);\n"
    )
    with open("/tmp/login_otp.js","w") as f:
        f.write(login_script)
    r = subprocess.run(["node","/tmp/login_otp.js"], capture_output=True, text=True, timeout=30)
    log(f"  OTP send result: {r.stdout}")
    
    log("  OTP sent to your phone!")
    log("  Please type OTP code in Telegram or here to continue.")
    return False

def scrape(page_id):
    log("[5/5] Scraping 50 HK stocks (~6 min)...")
    tickers_json = "[" + ",".join(f"['{c}','{n}']" for c,n in TICKERS) + "]"
    
    script = (
        "const WebSocket = require('/tmp/ws_temp/node_modules/ws');\n"
        "const fs = require('fs');\n"
        "const PAGE_ID = '" + page_id + "';\n"
        "const WS_URL = 'ws://127.0.0.1:18800/devtools/page/'+PAGE_ID;\n"
        "const TICKERS = " + tickers_json + ";\n"
        "const EXPR = `" + EXPR + "`;\n"
        "let msgId=1;\n"
        "const ws = new WebSocket(WS_URL);\n"
        "ws.on('open', async () => {\n"
        "  async function send(m,p) {\n"
        "    return new Promise((res,rej) => {\n"
        "      const id=msgId++;\n"
        "      ws.send(JSON.stringify({id,method:m,params:p||{}}));\n"
        "      const t=setTimeout(()=>{ws.close();rej(new Error('Timeout'));},25000);\n"
        "      const h=(d)=>{const m=JSON.parse(d.toString());if(m.id===id){ws.off('message',h);clearTimeout(t);res(m.result);}};\n"
        "      ws.on('message',h);\n"
        "    });\n"
        "  }\n"
        "  const all={},done=0;\n"
        "  for(const [code,name] of TICKERS) {\n"
        "    try {\n"
        "      await send('Page.navigate',{url:'https://www.futunn.com/hk/stock/'+code+'-HK/community'});\n"
        "      await new Promise(r=>setTimeout(r,6500));\n"
        "      const r=await send('Runtime.evaluate',{expression:EXPR,returnByValue:true});\n"
        "      const d=r?.result?.value||{};\n"
        "      const url=d?.url||'';\n"
        "      const count=d?.count||0;\n"
        "      if(url.includes('/404')||count===0) {\n"
        "        all[code]={name,posts:[],url,title:d?.title};\n"
        "        fs.appendFileSync('/tmp/futu_scrape.log',code+' '+name+': '+(url.includes('/404')?'404':'0')+' SKIP\\n');\n"
        "        continue;\n"
        "      }\n"
        "      all[code]={name,posts:d?.posts||[],url,title:d?.title};\n"
        "      fs.appendFileSync('/tmp/futu_scrape.log',code+' '+name+': '+count+' posts\\n');\n"
        "    } catch(e) {\n"
        "      all[code]={name,posts:[],error:e.message};\n"
        "      fs.appendFileSync('/tmp/futu_scrape.log',code+' '+name+': ERR '+e.message+'\\n');\n"
        "    }\n"
        "    done++;\n"
        "    if(done%10===0) fs.appendFileSync('/tmp/futu_scrape.log','PROGRESS: '+done+'/50\\n');\n"
        "  }\n"
        "  fs.writeFileSync('" + DATA_FILE + "',JSON.stringify(all,null,2));\n"
        "  const tp=Object.values(all).reduce((s,v)=>s+v.posts.length,0);\n"
        "  fs.appendFileSync('/tmp/futu_scrape.log','\\nDONE: '+tp+' posts from '+Object.keys(all).length+' stocks\\n');\n"
        "  ws.close();\n"
        "  process.exit(0);\n"
        "});\n"
        "ws.on('error',e=>{console.error('WS ERR:'+e.message);process.exit(1);});\n"
        "setTimeout(()=>{console.error('TIMEOUT');process.exit(2);},900000);\n"
    )
    with open("/tmp/scrape_50.js","w") as f:
        f.write(script)
    
    r = subprocess.run(["node","/tmp/scrape_50.js"], capture_output=True, text=True, timeout=900)
    return r

def main():
    open(LOG_FILE,"w").write("")
    log("=== Futu HK CDP Scrape ===")
    try:
        launch_chrome()
        page_id = get_page_id()
        log(f"[2/5] Page ID: {page_id[:16]}...")
        if not login_and_verify(page_id):
            log("OTP login needed. Re-run after entering OTP code.")
            return
        result = scrape(page_id)
        log(f"Exit: {result.returncode}")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    log("=== Summary ===")
    if os.path.exists(DATA_FILE):
        d = json.load(open(DATA_FILE))
        total = sum(len(v.get('posts',[])) for v in d.values())
        log(f"Stocks: {len(d)}, Posts: {total}")
        log(f"Data: {DATA_FILE}")
    else:
        log("No data file created")

if __name__ == "__main__":
    main()
