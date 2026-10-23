# آماده‌سازی استقرار ایزولهٔ Wallex — استقرار انجام نشده

نام پیشنهادی برنامه: `kaav-wallex-shadow`؛ هنوز ساخته نشده. هیچ فایل یا منبع پروژهٔ Liara ارسال‌شده تغییر نکرده است. هیچ مجوزی برای ساخت، deploy یا خرید منبع Wallex صادر نشده است.

`compose.shadow.yml` آمادهٔ اجرای محلی Docker است، نه manifest تأییدشدهٔ Liara. فقط cash/shadow، بدون کلید Wallex، با mount پایدار state/data/reports، lock کرنلی روی journal، restart policy و سقف حجم stdout. یک instance لازم است؛ lock فقط پردازش‌هایی با volume مشترک را جدا می‌کند و distributed fencing نیست. zero-downtime deploy یا دو replica با state مجزا مجاز نیست.

Runtime محلی آزموده‌شده Python3.11.6 است. Dockerfile بر python3.11.14-slim ساخته شده ولی image build این مرحله اجرا نشد؛ Docker daemon روی این میزبان در دسترس نیست. دستور پیش‌فرض Dockerfile `doctor` است و خارج می‌شود؛ برای worker باید فرمان shadow صریح داده شود. هیچ healthcheck HTTP ساخته/آزموده نشده است؛ پشتیبانی اجرای background worker و الزامات port/health در سرویس انتخابی Liara باید پیش از deploy احراز شود.

اعتبار فعلی تیم، region دقیق، IP خروجی، و اتصال Wallex/BoxAPI از همان region در این مرحله **UNVERIFIED** است. تست موفق محلی به معنی دسترسی ایران یا اجرای cloud نیست. هیچ shell/deploy روی اپ سالم مسابقهٔ Liara برای آزمایش Wallex استفاده نشده است.

در صفحهٔ قیمت رسمی https://liara.ir/pricing/ در ۲۳ اکتبر ۲۰۲۶، پلن پایهٔ زمین با RAM0.512GB، CPU0.5، disk5GB، ماهانه750000 و ساعتی1041 تومان نمایش داده شد. این قیمت عمومی گرد‌شده است؛ نگاشت `small-g2/basic`، region، دیسک پایدار اضافی، مالیات، اعتبار تیم و هزینهٔ نهایی هنوز به preflight پنل نیاز دارند. برآورد پایهٔ ۲۴ساعت از قیمت گرد‌شده24984تومان است؛ صفر بودن هزینه بر اثر اعتبار احراز نشده. هیچ منبعی خریداری نشد.

پاک‌سازی پس از مجوز مستقل: توقف worker اختصاصی، export audit/hash، برداشتن کلید از env همان worker، سپس حذف فقط همان app و volume تأییدشده. از حذف یا restart اپ Liara ارسال‌شده خودداری شود.
