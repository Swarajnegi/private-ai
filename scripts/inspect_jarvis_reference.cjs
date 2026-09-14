// Inspect the supplied motion reference without altering the original video.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const {pathToFileURL} = require('node:url');
(async () => {
 const out = path.resolve('artifacts/jarvis-ui'); fs.mkdirSync(out,{recursive:true});
 const browser = await chromium.launch({channel:'msedge',headless:true});
 const page = await browser.newPage({viewport:{width:1000,height:800}});
 if(!process.argv[2])throw new Error('Usage: node scripts/inspect_jarvis_reference.cjs <video path>');
 await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);
 const video = page.locator('video'); await video.waitFor();
 await video.evaluate(v=>new Promise(resolve=>{v.pause(); if(v.readyState>=2)resolve();else v.onloadeddata=resolve;}));
 console.log(await video.evaluate(v=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration})));
 const duration=await video.evaluate(v=>v.duration);
 for (const t of [0.2,1,2,3,4].filter(t=>t<duration)) {
  await video.evaluate((v,t)=>new Promise(resolve=>{v.onseeked=resolve;v.currentTime=t;}),t);
  await video.screenshot({path:path.join(out,`reference-${t}.png`)});
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
