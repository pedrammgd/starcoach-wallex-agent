# بازتولید داوری

۱. `sh scripts/quickstart.sh` را از checkout اجرا کنید؛ تست‌ها به شبکه/کلید نیاز ندارند.
۲. `.venv/bin/python -m wallex_agent.cli verify-boxapi` باید OFFLINE_CONFIGURATION_ONLY و network_calls=0 بدهد.
۳. `.venv/bin/python scripts/benchmark_all.py` گزارش‌های تمام قطعات واجد طول را بازسازی می‌کند.
۴. hash داده در quality_report و manifest را مقایسه کنید. دادهٔ خام عمومی در data/raw است.
۵. reports/shadow_public.jsonl شواهد مشاهدهٔ زندهٔ عمومی است؛ اجرای مجدد از اینترنت قیمت‌های جدید دارد و همان بازده قبلی انتظار نمی‌رود.
۶. `.venv/bin/python -m wallex_agent.cli run` باید PermissionError مسدودبودن live بدهد.

نسخهٔ SDK قفل شده است. current source hashes در manifest موجود است، ولی گزارش‌های ساخته‌شده در مراحل توسعه ممکن است source hash قدیمی داشته باشند؛ آخرین بازسازی باید پیش از freeze تحویل انجام شود. هنوز release معامله‌کننده‌ای وجود ندارد؛ هیچ Git SHA مربوط به معامله ادعا نمی‌شود.
