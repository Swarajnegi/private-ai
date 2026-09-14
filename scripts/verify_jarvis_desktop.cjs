// Desktop visual and runtime verification; credentials are never logged.
const { chromium }=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const dir=path.resolve('artifacts/jarvis-ui');fs.mkdirSync(dir,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:864},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 const token=fs.readFileSync('jarvis_data/.hearth_token','utf8').trim();
 await page.addInitScript(t=>sessionStorage.setItem('jarvis_hearth_token',t),token);
 await page.goto('http://127.0.0.1:8756/',{waitUntil:'networkidle'});
 await page.waitForTimeout(1800);
 await page.screenshot({path:path.join(dir,'desktop.png')});
 console.log('desktop',await page.evaluate(()=>{const c=document.querySelector('.living-core').getBoundingClientRect();const m=document.querySelector('#messages');return{core:{width:c.width,height:c.height},overflow:document.documentElement.scrollWidth>innerWidth,welcomeOverflow:m.scrollHeight>m.clientHeight+2};}));
 await page.setViewportSize({width:1280,height:720});await page.waitForTimeout(500);await page.screenshot({path:path.join(dir,'laptop.png')});
 console.log('laptop',await page.evaluate(()=>{const c=document.querySelector('.living-core').getBoundingClientRect();const m=document.querySelector('#messages');return{core:{width:c.width,height:c.height},overflow:document.documentElement.scrollWidth>innerWidth,welcomeOverflow:m.scrollHeight>m.clientHeight+2};}));
 console.log('errors',errors);
 if(errors.length)throw new Error('Browser runtime errors detected');
 await page.setViewportSize({width:1536,height:864});
 await page.locator('.session').first().click();
 await page.locator('.message').first().waitFor();
 console.log('Live saved conversation read successfully:',await page.locator('.message').count(),'messages');
 await page.screenshot({path:path.join(dir,'live-conversation.png')});
 await browser.close();
})().catch(e=>{console.error(e.message);process.exit(1)});
