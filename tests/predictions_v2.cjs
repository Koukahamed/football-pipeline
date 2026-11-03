const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const data=JSON.parse(fs.readFileSync('report/output/data.json','utf8'));
 if(!data.predictions?.model_report?.test)throw Error('Missing real historical report');
 for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://football.test/data.json',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(data)}));
  await page.route('http://football.test/',r=>r.fulfill({contentType:'text/html',body:fs.readFileSync('report/dashboard.html','utf8')}));
  await page.goto('http://football.test/');
  await page.getByRole('button',{name:'Prédictions',exact:true}).click();
  await page.getByRole('heading',{name:'Modèles et test historique',exact:true}).waitFor();
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Prediction UI overflow');
  if(errors.length)throw Error(errors.join('\n'));
  await page.screenshot({path:'report/output/predictions-'+width+'.png',fullPage:true});
  await page.close();
 }
 await browser.close();console.log('V2 report and predictions render on mobile and desktop.');
})();
