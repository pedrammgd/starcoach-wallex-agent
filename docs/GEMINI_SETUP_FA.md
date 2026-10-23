> بایگانی: Gemini غیرفعال است؛ از BOXAPI_SETUP_FA.md استفاده کنید. این راهنما مربوط به مرحلهٔ قبلی است.

# تنظیم Gemini

فایل آمادهٔ ویرایش: `.env` در ریشهٔ پروژه. در خط `GEMINI_API_KEY=` فقط `YOUR_GEMINI_API_KEY_HERE` را جایگزین کلید خود کنید. لازم نیست فایل یا کدی بسازید. مدل `gemini-3.8-flash` و حالت shadow از قبل تنظیم شده‌اند. فایل permission=600 دارد و در .gitignore و .dockerignore است.

تأیید بدون کلید:

```sh
.venv/bin/python -m wallex_agent.cli verify-gemini
.venv/bin/python -m unittest discover -s tests -v
```

تأیید بعد از جایگزینی کلید:

```sh
.venv/bin/python -m wallex_agent.cli verify-gemini --online
```

این فرمان اول catalog مدل‌ها را از Google می‌خواند؛ نبود مدل درخواستی فقط با جایگزین از catalog احراز‌شده اصلاح می‌شود. سپس یک درخواست آزمایشی ساختاریافته می‌فرستد. `ONLINE_OK` به‌معنای دریافت پاسخ معتبر آزمایشی است؛ سودآوری یا مجوز معامله را ثابت نمی‌کند. `usage` شامل توکن‌های گزارش‌شدهٔ provider است. 403 بدون retry، 429/5xx حداکثر دو تلاش؛ خطا یا refusal یعنی HOLD. در هیچ حالت سفارش واقعی ساخته نمی‌شود.

مدل در مستند رسمی Google موجود و Structured Outputs برای آن ذکر شده است: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash . دسترسی مدل برای کلید شما هنوز بررسی نشده است.

## نتیجهٔ بررسی آنلاین این اجرا

کلید محلی از حالت placeholder تغییر کرده بود. درخواست فقط‌خواندنی catalog مدل‌ها با HTTP 403 / PERMISSION_DENIED رد شد. هیچ درخواست generate_content یا سفارش والکس ارسال نشد؛ مدل جایگزین نشده است. اصلاح مجوز کلید/پروژهٔ Google و اجرای دوبارهٔ فرمان آنلاین لازم است. پاسخ خام provider و کلید ذخیره نشده‌اند؛ گزارش امن در reports/gemini_catalog_diagnostic.json است.
