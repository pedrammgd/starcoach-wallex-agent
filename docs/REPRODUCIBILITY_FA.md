# بازتولید بدون credential

برای تست، مطالعهٔ تاریخی و نمایش شواهد **هیچ فایل .env یا API key لازم نیست**. نصب در محیط جدا با Python3.11.6 و نسخه‌های requirements.lock از PyPI موفق شد. نصب قبلی پروژه برای این اثبات بازاستفاده نشد؛ فقط cache عادی دانلود بعضی بسته‌ها قابل استفاده بود.

فرمان عمومی با uv:

```sh
uv venv .venv --python python3.11
uv pip install --python .venv/bin/python -r requirements.lock --index-url https://pypi.org/simple
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/cutoff_demo.py
.venv/bin/python scripts/build_final_demo.py
.venv/bin/python -m wallex_agent.cli verify-boxapi
```

روی همین Mac ARM64، interpreter قدیمی universal2 باعث شد uv ابتدا به build طولانی cryptography برود؛ آن اجرا متوقف شد. فرمان واقعی موفق با wheel رسمی و معماری منطبق با دستگاه:

```sh
uv pip install --only-binary=:all: --python-platform aarch64-apple-darwin --python .venv/bin/python -r requirements.lock --index-url https://pypi.org/simple
```

این گزینهٔ platform برای **همان مک ARM64** است؛ روی Linux یا x86 به‌صورت کور استفاده نشود. هیچ تنظیم سیستم یا .venv اصلی برای این راه‌حل تغییر نکرده است. image Docker این مرحله build نشد، چون daemon موجود نیست؛ نصب macOS را build ابری Linux معرفی نمی‌کنیم.

`verify-boxapi` بدون --online، صفر درخواست دارد و `OFFLINE_CONFIGURATION_ONLY` می‌دهد؛ گزارش مجزای offline می‌نویسد و مدرک inference واقعی قبلی را overwrite نمی‌کند. دستور online تا۳ فراخوانی می‌تواند هزینه داشته باشد و فقط با کلید خودِ اپراتور اجرا شود.

`cutoff_demo.py` صرفاً fixture مصنوعی بدون endpoint صرافی است. `build_final_demo.py` از فایل‌های شواهد کار می‌کند؛ اگر گزارش خصوصی read-only همراه بسته نباشد، گزارش پاک `FINAL_ACCESS_STATUS.json` را می‌خواند. تاریخچه‌ها با source hash زمان خود باقی‌اند و نتیجهٔ live نیستند.

مطالعهٔ جدید:

```sh
.venv/bin/python scripts/final_strategy_study.py
```

این فرمان۷۵مقایسه با presets ثابت روی train/validation دارد؛ به final25% دست نمی‌زند. نتایج قدیمی holdout پیش‌تر دیده شده‌اند؛ دادهٔ prospective آینده هنوز دورهٔ کاملی ندارد.

قابلیت `run` و `flatten` عمداً مسدود است. کلید واقعی، .env، journal SQLite، state خصوصی یا شناسهٔ کامل حساب در بستهٔ پاک نیست. GitHub هنوز منتشر نشده است.

نتیجهٔ نهایی:۷۴تست در1.455ثانیه در محیط تازه و بدون credential موفق شدند؛ سه smokecheck دمو/offline BoxAPI/cutoff هم exit0 داشتند. exit2 فرمان credit به معنی کامل نبودن preflight پکیج است؛ گزارش می‌تواند هم‌زمان api_key_valid=true و competition_wallet_confirmed=true داشته باشد.
