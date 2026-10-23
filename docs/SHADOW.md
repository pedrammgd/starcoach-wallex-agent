# تست سایه

در این اجرا پنج polling محدود با دادهٔ دقیقه‌ای BTCTMN انجام شد. تصمیم‌های بازار عمومی واقعی با موجودی مجازی پنج میلیون تومان ثبت شدند؛ تصمیم‌ها HOLD و fill صفر بودند. این تست را معاملهٔ واقعی یا اثبات صحت fill بازار نمی‌نامیم. export در reports/shadow_public.jsonl و کنسول در reports/shadow_run.log است. journal زنجیرهٔ hash معتبر دارد و تصمیم تکراری برای همان کندل دوباره اجرا نمی‌شود.

shadow از قیمت مشاهده‌شدهٔ bid/ask استفاده می‌کند؛ در گذشته به open دلخواه fill نمی‌سازد. spread واقعی یک بار و slippage مفروض جدا اعمال می‌شود. برای دادهٔ عمومی timestamp صرافی موجود نیست؛ محدودیت freshness صریح در event ثبت است. latency واقعی matching engine، permission حساب و خطای سفارش واقعی هنوز بررسی نشده‌اند.

BoxAPI از .env خوانده می‌شود و فقط روی candidate معامله یا exposure موجود فراخوانی می‌شود. کلید نمونه باعث HOLD و جلوگیری از ورود است. چرخهٔ عمومی ثبت‌شده در `reports/boxapi_public_shadow.jsonl` به علت نبود momentum edge بدون inference و fill بوده است؛ آن را تست آنلاین مدل تلقی نمی‌کنیم. برای نسخهٔ جدید کد از journal جدید استفاده کنید، چون provenance باید ثابت بماند.
