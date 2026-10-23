> تحویل نهایی: ویدئوی پنج‌دقیقه‌ای1080p با روایت فارسی مصنوعی، بازپخش شواهد واقعی و برچسب شبیه‌سازی. [صفحهٔ پخش](docs/video/index.html) · [MP4](docs/video/demo.mp4). بازآزمایی23:00ایران:401/1201باقی است، موجودیprop5میلیونTMN؛ route و بازارهای مجاز و cutoff تأیید نشده‌اند. هیچ معاملهٔ واقعی انجام نشده است.

> وضعیت تازه: ۷۴ تست، ۳ inference واقعی BoxAPI، دو چرخهٔ سایه و ۷۵ مقایسهٔ validation. کلید Wallex برای خواندن کار می‌کند و کیف پول زیرحساب هکاتون۵میلیون تومان دارد؛ متادیتای پکیج و مسیر سفارش هنوز تأیید نشده‌اند. live و انتشار غیرفعال‌اند. گزارش مرجع: FINAL_WALLEX_AUDIT.md.

# عامل پژوهشی والکس — Starcoach

وضعیت فعلی: موتور پژوهش و shadow قابل اجراست؛ LIVE غیرفعال و مسیر سفارش حساب مسابقه احراز نشده است. سودآوری تأیید نشده. هیچ معامله واقعی انجام نشده است.

## شروع سریع

Python 3.11+ لازم است. از ریشهٔ پروژه:

```sh
sh scripts/quickstart.sh
```

این فرمان محیط محلی را می‌سازد، وابستگی‌های قفل‌شده را نصب و تست‌ها و doctor را اجرا می‌کند. تست‌ها به کلید یا شبکه نیاز ندارند. Dockerfile موجود است ولی ساخت Docker در این اجرا آزموده نشده است.

## BoxAPI؛ تنها LLM فعال

برای نصب پاک ابتدا `.env.example` را به `.env` کپی کنید. مقدار `BOXAPI_API_KEY=YOUR_BOXAPI_API_KEY_HERE` را با کلید حساب مسابقه جایگزین کنید. این بسته هیچ کلید واقعی ندارد؛ کد قدیمی Gemini حفظ شده ولی در تنظیم فعال استفاده نمی‌شود.

```sh
.venv/bin/python -m wallex_agent.cli verify-boxapi --online --compare --samples 2
```

نتیجهٔ اجرای واقعی پس از رفع نام مدل: ONLINE_OK با `openai/gpt-5.4-mini`، چهار پاسخ JSON معتبر و لاگ ثبت‌شده. جزئیات در [گزارش رفع شناسه](docs/BOXAPI_MODEL_RESOLUTION_FA.md) است.

SDK رسمی OpenAI نصب و قفل شده است. فرمان بالا مسیر API، catalog حساب، پاسخ JSON سخت‌گیرانه، latency و مصرف توکن را بررسی می‌کند و مدل معتبر سریع‌تر را از میان گزینه‌های محدود آزموده‌شده انتخاب می‌کند. موفقیت catalog به‌تنهایی کافی نیست؛ نتیجهٔ این اجرا شامل پاسخ تولیدی واقعی است. گزارش و تصمیم‌ها در `reports/boxapi_verification*` ذخیره می‌شوند. راهنمای کامل و محدودیت هزینه/انتخاب مدل: [BOXAPI_SETUP_FA.md](docs/BOXAPI_SETUP_FA.md).

## بک‌تست بازتولیدپذیر

```sh
.venv/bin/python scripts/benchmark_all.py
.venv/bin/python -m wallex_agent.cli --config configs/BTCTMN_research.json backtest --symbol BTCTMN --data data/BTCTMN_validated_segment_1.csv --output reports/reproduced
```

دادهٔ Wallex واقعی است؛ کارمزد ۳۰bp در هر سمت، spread کامل ۱۰bp و لغزش ۱۰bp در هر سمت **فرض پژوهشی** هستند، نه کارمزد تأییدشدهٔ حساب چالش. موجودی مجازی ۵ میلیون تومان و تخصیص حداکثر ۲۰٪ است. نتیجهٔ انتخاب با validation در همهٔ بازارهای بررسی‌شده cash بود؛ سود یک استراتژی در نمودار holdout مجوز انتخاب پسینی آن نیست.

## داده و تست سایه عمومی

```sh
.venv/bin/python -m wallex_agent.cli doctor --online
.venv/bin/python -m wallex_agent.cli fetch-data --symbol BTCTMN --days 90 --split-gaps --output data/recent.csv
.venv/bin/python -m wallex_agent.cli --config configs/BTCTMN_research.json shadow --symbol BTCTMN --strategy momentum --journal state/boxapi_shadow_v1.sqlite --cycles 5 --poll-seconds 30
.venv/bin/python -m wallex_agent.cli report --journal state/boxapi_shadow_v1.sqlite --output reports/boxapi_shadow.jsonl
```

shadow از تنظیم BoxAPI در `.env` استفاده می‌کند. روی رویداد کاندیدا از LLM تصمیم می‌گیرد؛ LLM به بروکر دسترسی ندارد. کلید ناموجود یعنی افزایش exposure ممنوع. برای دادهٔ دقیقه‌ای `configs/minute_shadow.json` موجود است. shadow فقط حساب مجازی دارد؛ HTTP quote زمان مشاهده دارد، timestamp معتبر صرافی در این پاسخ نداریم و آن را برای live کافی نمی‌دانیم. journal برای نسخهٔ ثابت کد/تنظیمات است؛ با تغییر نسخه مسیر جدیدی بسازید.

## تحویل و محدودیت‌ها

متن رسمی در `CHALLENGE_SPEC.md` و رونویسی خودکار ویدئو در `docs/VIDEO_TRANSCRIPT_AUTO_FA.md` است. `docs/SUBMISSION_CHECKLIST.md` وضعیت واقعی تحویل را ثبت می‌کند. شواهد عمومی و پاک‌شده در `reports/` و داده‌های عمومی انتخاب‌شده در `data/` قرار دارند. API Key، PII یا دارایی شخصی در این فایل‌ها نباید قرار گیرد.

`run` و `flatten` عمداً خطای مسدودبودن می‌دهند و هیچ adapter تولیدی ندارند. هویت حساب اعتباری، نمادهای مسابقه، پایان دقیق معاملات، کارمزدها، کلید حساب و تأیید صریح live لازم‌اند. ساخت README یا پرکردن یک فایل تنظیمات این شروط را احراز نمی‌کند. GitHub و ویدئوی دمو هنوز ارسال نشده‌اند. انتشار عمومی مجوز مستقل می‌خواهد؛ بستهٔ پاک دارای manifest است و مخزن مستقل نهایی برای بازبینی آماده می‌شود.

## ممیزی نهایی ۲۳ اکتبر — نسخهٔ جدید محلی، منتشرنشده

ابتدا [FINAL_WALLEX_AUDIT.md](FINAL_WALLEX_AUDIT.md) و [FINAL_COMPETITION_RULES.md](FINAL_COMPETITION_RULES.md) را بخوانید. کلید در خواندن پایه معتبر است؛ کیف پول زیرحساب هکاتون با موجودی جاری و در دسترس۵میلیون تومان احراز شد. تاریخچه و جزئیات پکیج401 می‌دهند؛ initial balance، expiry، route، fee رقابت، allowlist و cutoff رسمی تأیید نشده‌اند. هیچ سفارش واقعی ارسال نشده و broker تولیدی مسدود است. snapshot پاک `9e6b4d8` محلی حفظ شده؛ تغییرات جدید مربوط به آن commit نیستند.

۷۴ تست موفق؛ مطالعهٔ جدید۷۵حالت validation دوباره cash را انتخاب کرد. سه inference واقعی BoxAPI، دو shadow روی دادهٔ جاری، و cutoff simulation همراه audit ثبت شده‌اند. بهبود سود AI یا پایداری سه‌روزه ادعا نمی‌شود.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/final_strategy_study.py
.venv/bin/python scripts/cutoff_demo.py
.venv/bin/python scripts/build_final_demo.py
.venv/bin/python -m http.server 8768 --bind 127.0.0.1 --directory artifacts/wallex-demo
# فقط GET احرازشده؛ کلید در .env، نه command line:
.venv/bin/python -m wallex_agent.credit --online
# حداکثر۳ inference واقعی با هزینهٔ provider؛ بدون سفارش:
.venv/bin/python scripts/final_online_evidence.py --online
```

برای demo از http://127.0.0.1:8768 استفاده کنید. فیلم پنج‌دقیقه‌ای ضبط واقعی رابط شواهد تاریخی، بدون صدا، در docs/video/demo.mp4 قرار دارد؛ متن روایت در docs/DEMO_SCRIPT_FA.md آماده است. GitHub/ویدئو/فرم Wallex بدون مجوز جدا منتشر یا ارسال نمی‌شود. جزئیات آماده‌سازی cloud و محدودیت‌های آن در ops/wallex/README_FA.md است.


## بازآزمایی فوری نهایی

[گزارش22:45ایران](docs/FINAL_RETEST_FA.md):401با code1201 روی تاریخچه/active/overview باقی است؛ GET پایه و کیف پول200، موجودی در دسترس5میلیونTMN. route سفارشBLOCKED؛ بازارها و cutoff نامعلوم. هیچ سفارش یا write انجام نشد.74تست موفق. [راهنمای اجرای پاک](docs/REPRODUCIBILITY_FA.md).


### ویدئوی نهایی و صفحهٔ پخش

ویدئو ضبط واقعی رابط محلی و بازپخش شواهد تاریخی است و صدا ندارد. هیچ سفارش واقعی اجرا نشده است؛ بخش پایان دوره صریحاً شبیه‌سازی است.

- [صفحهٔ HTML5 پخش ویدئو](docs/video/index.html)
- [فایل MP4 نهایی](docs/video/demo.mp4)
- برای اجرای محلی: `python3 -m http.server 8768` و سپس `http://127.0.0.1:8768/docs/video/`.

این نسخه هنوز منتشر نشده است. فعال‌سازی GitHub Pages از پوشهٔ `docs` و انتشار سورس و ویدئو، نیازمند مجوز صریح مالک است.
