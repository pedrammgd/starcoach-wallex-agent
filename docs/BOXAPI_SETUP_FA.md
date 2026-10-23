# راه‌اندازی BoxAPI برای مسابقه

BoxAPI تنها LLM فعال است. کد و اعتبارنامهٔ Gemini حفظ شده ولی هیچ probe، shadow یا مسیر پیش‌فرض آن را فراخوانی نمی‌کند. پروژه و موتور ریسک بازسازی نشده‌اند.

## تنها تغییر لازم توسط مالک کلید

در فایل `<project-root>/.env` مقدار این سطر را جایگزین کنید؛ کلید را در چت، خط فرمان یا Git ننویسید:

```dotenv
BOXAPI_API_KEY=YOUR_BOXAPI_API_KEY_HERE
```

از ریشهٔ همین پروژه:

```sh
.venv/bin/python -m wallex_agent.cli verify-boxapi --online --compare --samples 2
```

این فرمان حداکثر دو مدل و دو نمونه برای هر مدل بررسی می‌کند؛ هر فراخوانی حداکثر دو تلاش دارد. درخواست‌های تولیدی هزینه دارند. اول catalog روی دو مسیر مستند و فقط دامنهٔ رسمی بررسی می‌شود؛ سپس مدل‌های قابل دسترس از میان مدل تنظیم‌شده، `openai/gpt-5.4-mini` و `openai/gpt-5.4-nano` انتخاب می‌شوند. بدون `--compare` فقط یک مدل بررسی می‌شود. timeout پیش‌فرض هر درخواست ۲۰ ثانیه است؛ latency ثبت‌شده شامل تلاش مجدد نیز هست. timeout و خطای اتصال مبهم خودکار تکرار نمی‌شوند.

فقط مدل با پاسخ JSON معتبر و مصرف توکن ثبت‌شده در تمام نمونه‌ها پذیرفته می‌شود؛ پیشنهاد ENTER روی سناریوی بدون edge نیز رد می‌شود. از میان مدل‌های آزموده‌شده، کمترین median latency انتخاب و `BOXAPI_MODEL` و `BOXAPI_BASE_URL` در `.env` اصلاح می‌شود؛ کلید و سایر متغیرها حفظ می‌شوند. این مقایسهٔ کوچک تضمین قابلیت اطمینان آماری یا کیفیت معاملاتی نیست. تا وقتی نرخ صورتحساب حساب مسابقه معلوم نیست، بهترین مدل از نظر هزینه ادعا نمی‌شود. هزینهٔ برگشتی با واحد تأییدنشده و مصرف توکن جدا ثبت می‌شوند.

خروجی موفق باید `ONLINE_OK`، `real_inference_verified=true` و `structured_output_verified=true` داشته باشد. گزارش در `reports/boxapi_verification.json` و دفتر تصمیم در `reports/boxapi_verification_decisions.jsonl` نوشته می‌شود. اجرای آفلاین بدون `--online` فقط تنظیمات را گزارش می‌کند؛ موفقیت استنتاج نیست. هر اجرا journal جدید دارد؛ نتیجهٔ cache به‌عنوان استنتاج تازه جا زده نمی‌شود.

## تفاوت مسیرها

[صفحهٔ اصلی API](https://boxapi.ir/docs/ai/) مسیر `https://ai.boxapi.ir/ai/v1` و [صفحهٔ متن به متن](https://boxapi.ir/docs/ai/text-to-text/) مسیر `https://ai.boxapi.ir/api/v1` را نشان می‌دهد. بررسی بدون کلید برای `/models` در هر دو مسیر ۴۰۱ داد؛ این نتیجه مسیر مجاز حساب یا سازگاری structured output را ثابت نمی‌کند. پیش‌فرض موقت، مسیر صفحهٔ اصلی است. اگر catalog هر دو مسیر شکست بخورد، فرمان متوقف می‌شود و خطای پالایش‌شده گزارش می‌دهد؛ مدل یا پاسخ ساختگی جایگزین نمی‌شود.

SDK رسمی `openai==3.37.0` استفاده می‌شود. درخواست Chat Completions شامل `response_format=json_schema` با `strict=true` است. رد schema، refusal، پاسخ ناقص یا نامعتبر باعث HOLD و ممنوعیت افزایش exposure است. JSON ساده جایگزین پنهانی schema نمی‌شود.

## Shadow و ریسک

```sh
.venv/bin/python -m wallex_agent.cli --config configs/BTCTMN_research.json shadow --symbol BTCTMN --strategy momentum --journal state/boxapi_shadow_v1.sqlite --cycles 5 --poll-seconds 30
.venv/bin/python -m wallex_agent.cli report --journal state/boxapi_shadow_v1.sqlite --output reports/boxapi_shadow.jsonl
```

نماد بالا فقط مثال پژوهشی است و مجوز بازار مسابقه نیست. مدل فقط وقتی کاندیدای ورود یا موقعیت مجازی موجود باشد فراخوانی می‌شود. HOLD بدون inference ممکن است حاصل نبود edge باشد. مدل می‌تواند ورود را وتو، تخصیص را کاهش یا خروج پیشنهاد کند؛ ورود را فراتر از کاندیدای استراتژی مجاز نمی‌کند. risk مستقل بعد از پاسخ اعمال می‌شود. حساب، برداشت، انتقال، broker tool و دادهٔ محرمانه به LLM داده نمی‌شود.

Agent برای هر journal حداکثر ۲۰ invocation با رزرو برآوردی یک دلار دارد؛ retry ممکن است هزینهٔ نامعلوم داشته باشد و این رزرو سقف واقعی صورتحساب نیست. برای verification سقف ۶ invocation و رزرو ۰٫۳۰ است. سقف مصرف پنل BoxAPI نیز باید مطابق اعتبار مسابقه محدود شود.

## Liara

CLI رسمی پروژه نصب است. از تیم و منابع تخصیص‌یافته استفاده کنید؛ هیچ منبعی در این مرحله خریداری یا ساخته نشده است. پس از مشخص‌شدن حساب، تیم و اپ موجود، متغیرهای `LIARA_ACCOUNT`، `LIARA_TEAM_ID` و `LIARA_APP_NAME` در `.env` قابل تکمیل‌اند. کلید BoxAPI را فقط در متغیرهای محرمانهٔ همان اپ قرار دهید. Gemini را در runtime فعال نکنید. تنظیمات امن Dockerfile شامل BoxAPI و shadow است؛ گواهی Linux مسیر `/etc/ssl/certs/ca-certificates.crt` دارد.

```sh
.venv/bin/python scripts/liara_access.py whoami
.venv/bin/python scripts/liara_access.py apps
.venv/bin/python scripts/liara_access.py probe
.venv/bin/python scripts/liara_access.py verify-boxapi
```

دو فرمان آخر فقط روی اپ موجود و هدف صریح اجرا می‌شوند؛ هیچ deploy/create/restart انجام نمی‌دهند. probe فقط catalog و بازار عمومی را می‌خواند؛ verify-boxapi استنتاج واقعی محدود را در همان runtime می‌آزماید. ادعای region فقط با metadata پنل/اجرای واقعی قابل احراز است. نتیجهٔ اتصال محلی اثبات اتصال از Liara نیست.

حساب خصوصی والکس، نمادهای مجاز، کارمزد اختصاصی و پایان دقیق معاملات هنوز باید احراز شوند. همهٔ مسیرهای سفارش واقعی همچنان مسدودند.

## تطبیق شناسهٔ مدل

شناسهٔ دقیق catalog، از جمله پیشوند ارائه‌دهنده، مستقیماً برای inference ارسال می‌شود. نام کوتاه فقط اگر یک تطبیق یکتا با بخش پایانی شناسه داشته باشد به شناسهٔ کامل تبدیل می‌شود. نسخه‌های `:batch`، تاریخ‌دار و پیشوندهای متفاوت خودکار جایگزین نمی‌شوند؛ نام مبهم نیازمند شناسهٔ کامل است. وجود مدل در catalog به‌تنهایی موفقیت inference نیست.
