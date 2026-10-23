/* Capture only the sanitized local evidence viewer, with explicit historical labels.
 * Requires the already-installed Playwright package; no personal browser profile.
 * This does not contact Wallex or any AI provider, and cannot place orders.
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out = path.resolve('artifacts/wallex-demo-video');
const url = 'http://127.0.0.1:8768/';
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const scenes = [
  {id:'status', seconds:40, title:'۱ — واقعیت حساب و مرز ایمنی', parts:[
    'کاو: عامل پژوهشی Wallex، با AI واقعی و کنترل ریسک قطعی.',
    'این فیلم ضبط رابط شواهد است؛ عملیات حساب و inference در زمان فیلم اجرا نمی‌شوند.',
    'وضعیت دسترسی، پاسخ HTTP و موجودی خوانده‌شده در همین صفحه مشخص‌اند.',
    'معاملهٔ واقعی انجام نشده؛ مسیر سفارش prop و مجوز زنده شرط ضروری هستند.'
  ], moves:[0,200,0,140]},
  {id:'research',seconds:55,title:'۲ — بک‌تست واقعی و هزینه‌محور',parts:[
    '۷۵ مقایسه: پنج بخش داده × پنج استراتژی × سه سناریوی هزینه.',
    'جدول از خروجی validation است؛ هزینهٔ پایهٔ فرضی رفت‌وبرگشت ۰٫۹ درصد.',
    'نمونهٔ BTC momentum: بازده ۰٫۴۳۶٪؛ اما نتایج بین بازارها پایدار نبود.',
    'هیچ استراتژی تمام معیارهای پایداری را پاس نکرد؛ انتخاب نهایی cash و صفر معامله است.',
    'بخش داده و محدودیت holdout مستند است؛ ادعای سود تضمینی یا آزمون آینده نداریم.'
  ],moves:[0,350,460,580,0]},
  {id:'ai',seconds:50,title:'۳ — inference واقعی BoxAPI در تصمیم',parts:[
    'مدل ثبت‌شده: openai/gpt-5.4-mini؛ سه پاسخ واقعی با JSON معتبر.',
    'یک نامزد تاریخی momentum از هدف حدود ۲۰٪ به HOLD و تخصیص صفر رسید.',
    'این بازپخش تاریخی بخش آموزش است؛ معامله یا سود آینده را نشان نمی‌دهد.',
    'سه فراخوان: ۱۳۰۶ توکن؛ تأخیر حدود ۲٫۵۶ تا ۳٫۱۲ ثانیه؛ هزینهٔ دلاری تأیید نشده.',
    'timeout، retry محدود، ثبت مصرف و schema فعال‌اند؛ ابزار سفارش در اختیار مدل نیست.'
  ],moves:[0,350,450,350,0]},
  {id:'shadow',seconds:45,title:'۴ — شواهد سایه و ثبت تصمیم',parts:[
    'دو مشاهدهٔ واقعی بازار و دو بررسی AI؛ پول و اجرای معامله در این حالت مجازی‌اند.',
    'خروجی هر دو چرخه HOLD؛ fill برابر null و معاملهٔ واقعی صفر.',
    'شناسهٔ مدل، hash ورودی، token usage و تأخیر در تصمیم ثبت شده‌اند.',
    'دفتر سفارش واقعی و پایداری سه‌روزه احراز نشده‌اند؛ محدودیت‌ها پنهان نیستند.'
  ],moves:[0,400,600,650]},
  {id:'cutoff',seconds:60,title:'۵ — کنترل پایان دوره؛ فقط شبیه‌سازی',parts:[
    'هشدار: تمام قیمت‌ها، زمان‌ها و fillهای این بخش مصنوعی‌اند؛ درخواست Wallex صفر.',
    'deadline نامعلوم باعث توقف می‌شود؛ زمان پایان مسابقه حدس زده نمی‌شود.',
    'در buffer پایان دوره، ورود جدید متوقف و سفارش نیمه‌پر تطبیق می‌شود.',
    'لغو و فروش در broker مجازی انجام شده‌اند؛ مانده و dust باید حسابرسی شوند.',
    'هشت رویداد journal ثبت شده؛ سود مصنوعی این fixture عملکرد استراتژی نیست.',
    'این سناریو مسیر کد را بررسی می‌کند؛ پشتیبانی routing حساب prop همچنان جداست.'
  ],moves:[0,300,420,470,400,0]},
  {id:'reproduce',seconds:50,title:'۶ — بازتولید، ریسک و تحویل',parts:[
    'نسخهٔ پاک بدون کلید خصوصی قابل نصب و اجرای آفلاین است؛ تست‌ها و فرمان‌ها مستندند.',
    'کنترل قطعی اندازه، exposure، توقف زیان، cooldown و پایان دوره بر تصمیم AI مقدم است.',
    'ژورنال و شواهد شامل دادهٔ بازار، ورودی تصمیم، gate ریسک و نتیجهٔ شبیه‌سازی‌اند.',
    'نتیجه: AI واقعی و آزمایش قابل بازتولید؛ هیچ ادعای معاملهٔ زنده یا سود واقعی نداریم.',
    'انتشار GitHub به تأیید مالک نیاز دارد؛ این فیلم بی‌صداست و زیرنویس فارسی دارد.'
  ],moves:[0,300,350,300,0]}
];
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args:['--disable-background-networking','--disable-component-update','--no-first-run','--no-default-browser-check']});
  const context=await browser.newContext({viewport:{width:1920,height:1080},deviceScaleFactor:1,recordVideo:{dir:path.join(out,'capture'),size:{width:1920,height:1080}},locale:'fa-IR'});
  await context.route('**/*',route=>route.request().url().startsWith(url)?route.continue():route.abort());
  const page=await context.newPage();
  await page.goto(url,{waitUntil:'networkidle'});
  await page.addStyleTag({content:`html{scroll-behavior:smooth;scroll-padding-top:100px}nav{top:44px!important}body{padding-top:44px;padding-bottom:180px}section{scroll-margin-top:115px!important}main{max-width:1360px!important}#video-label{position:fixed;z-index:10000;top:0;left:0;right:0;background:#381e00;color:#ffe1a2;font:22px Tahoma,Arial,sans-serif;line-height:44px;text-align:center}#video-caption{position:fixed;z-index:10000;bottom:0;left:0;right:0;background:rgba(4,10,22,.97);border-top:2px solid #38bdf8;min-height:130px;padding:18px 80px;text-align:center;font:27px/1.8 Tahoma,Arial,sans-serif;color:#f8fafc;box-sizing:border-box}#video-caption strong{display:block;color:#7dd3fc;font-size:23px}#video-progress{position:fixed;z-index:10001;bottom:0;right:0;height:5px;background:#38bdf8;transition:width .4s linear}`});
  await page.evaluate(()=>{
    for(const [id,tag] of [['video-label','div'],['video-caption','div'],['video-progress','div']]){const n=document.createElement(tag);n.id=id;document.body.appendChild(n);}
    document.querySelector('#video-label').textContent='بازپخش شواهد ثبت‌شده • هیچ عملیات زنده‌ای در فیلم انجام نمی‌شود • بدون روایت صوتی';
  });
  const sourceHtml=await page.locator('html').innerText();
  for (const pattern of [/sk-[A-Za-z0-9]{15,}/,/Bearer\s+[A-Za-z0-9_.-]{15,}/,/AIza[A-Za-z0-9_-]{20,}/,/\/Users\/pedram/]) if(pattern.test(sourceHtml))throw new Error('PRIVATE_TEXT_DETECTED');
  const timeline=[];
  let elapsed=0;
  for(const scene of scenes){
    await page.getByRole('link',{name:({status:'وضعیت',research:'بازار و استراتژی',ai:'AI واقعی',shadow:'سایه',cutoff:'پایان دوره',reproduce:'بازتولید'})[scene.id],exact:true}).click();
    await sleep(700);
    const started=Date.now();
    timeline.push({scene:scene.id,start:elapsed,duration:scene.seconds,caption:scene.title,kind:scene.id==='cutoff'?'synthetic simulation':'recorded historical evidence UI'});
    for(let i=0;i<scene.parts.length;i++){
      await page.evaluate(({title,text,cutoff,progress})=>{
        const caption=document.querySelector('#video-caption');caption.replaceChildren();const titleNode=document.createElement('strong');titleNode.textContent=title;caption.append(titleNode,document.createTextNode(text));
        document.querySelector('#video-label').textContent=cutoff?'شبیه‌سازی با دادهٔ مصنوعی • هیچ سفارش یا endpoint والکس اجرا نشده':'بازپخش شواهد ثبت‌شده • هیچ عملیات زنده‌ای در فیلم انجام نمی‌شود • بدون روایت صوتی';
        document.querySelector('#video-progress').style.width=progress+'%';
      },{title:scene.title,text:scene.parts[i],cutoff:scene.id==='cutoff',progress:(elapsed+scene.seconds*i/scene.parts.length)/3});
      if(i===0)await page.screenshot({path:path.join(out,`scene-${scene.id}.png`)});
      if(i>0 && scene.moves[i])await page.mouse.wheel(0,scene.moves[i]);
      if(i===scene.parts.length-1 && ['research','ai','cutoff'].includes(scene.id))await page.locator('#'+scene.id).scrollIntoViewIfNeeded();
      const remaining=(started+scene.seconds*1000*(i+1)/scene.parts.length)-Date.now();
      if(remaining>0)await sleep(remaining);
    }
    elapsed+=scene.seconds;
    console.log(JSON.stringify({scene:scene.id,seconds:elapsed}));
  }
  const video=page.video();await context.close();const raw=await video.path();await browser.close();
  fs.writeFileSync(path.join(out,'recording.json'),JSON.stringify({created_at:new Date().toISOString(),source:url,video:raw,viewport:[1920,1080],historical_replay:true,synthetic_section:'cutoff',narration:'none; silent Persian captions',timeline},null,2));
  console.log(JSON.stringify({raw,seconds:elapsed}));
})().catch(e=>{console.error(e.stack);process.exit(1)});
