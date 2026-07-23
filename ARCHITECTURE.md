# بنية المشروع

يعتمد المشروع أسلوب **Clean Architecture** بحيث تتجه الاعتماديات من الطبقات الخارجية إلى الداخل فقط.

## الطبقات

```text
src/shein_extractor/
├── domain/                 # الكيانات وقواعد المجال والأخطاء
├── application/            # حالات الاستخدام والمنافذ والخدمات النقية
├── infrastructure/         # Playwright وJSON وPDF والتشخيص
├── presentation/qt/        # واجهة PySide6 والعناصر ومنطق الصور والتقارير
└── cli/                    # أوامر الطرفية
```

## اتجاه الاعتماديات

```text
presentation ─┐
cli ──────────┼──> application ──> domain
infrastructure┘          ▲
                         │
                 ports / protocols
```

- `domain` لا يعتمد على Qt أو Playwright أو نظام الملفات.
- `application` ينسق حالات الاستخدام ويتعامل مع منافذ مجردة.
- `infrastructure` يطبق المنافذ للوصول إلى SHEIN والتخزين وإنشاء PDF.
- `presentation` تعرض البيانات وتستدعي حالات الاستخدام ولا تنفذ قواعد الاستخراج.
- `bootstrap.py` هو Composition Root الوحيد المسؤول عن تركيب الاعتماديات.

## وحدات الواجهة

- `main_window.py`: تنسيق الشاشة والأحداث فقط.
- `widgets/`: عناصر قابلة لإعادة الاستخدام للسجل والبطاقات والحوارات.
- `workers.py`: تشغيل حالة استخدام التحليل في خيط خلفي.
- `image_loading.py`: تحميل الصور والمحاولات المؤجلة وحالة اكتمالها.
- `pdf_reporting.py`: تنسيق دورة تصدير التقرير داخل الواجهة عبر `ExportReport`.
- `bootstrap.py`: إنشاء التطبيقات الفعلية للمنافذ وحقنها في الواجهة.

## حالات الاستخدام

- `AnalyzeCart`: استخراج السلة وحفظ JSON من خلال منفذي الاستخراج والتخزين.
- `LoadAnalysis`: تحميل تحليل محفوظ دون معرفة صيغة التخزين.
- `ExportReport`: إنشاء التقرير من خلال منفذ مجرد؛ ينفذ `QtPdfReportExporter` الرسم لتطبيق سطح المكتب، بينما ينفذ `PlaywrightPdfReportExporter` التصدير الخادمي عبر HTML/CSS وChromium دون تحميل `PySide6`.

## التوافق

بقيت ملفات الجذر `app.py` و`extract_cart.py` و`diagnose_link.py` و`models.py` و`invoice_parser.py` و`pdf_export.py` كواجهات رفيعة للحفاظ على أوامر التشغيل والاستيرادات السابقة.

## إضافة وظيفة جديدة

1. أضف قواعد البيانات والكيانات إلى `domain` عند الحاجة.
2. عرّف المنفذ وحالة الاستخدام في `application`.
3. أنشئ adapter داخل `infrastructure`.
4. اربط التنفيذ في `presentation` أو `cli` عبر Composition Root.
