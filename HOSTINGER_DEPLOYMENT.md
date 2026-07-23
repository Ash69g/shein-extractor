# نشر خدمة SHEIN على Hostinger

يوضح هذا الملف طريقة تشغيل API داخل حاوية Docker مستقلة، وربطها داخليًا مع حاوية `n8n` عبر شبكة `root_default`.

## البنية المعتمدة

- تعمل خدمة `shein-api` داخل حاوية مستقلة.
- لا يُفتح منفذ API للإنترنت؛ يصل إليها `n8n` داخليًا عبر `http://shein-api:8000`.
- يعمل Uvicorn بعامل واحد للمحافظة على ترتيب طابور `FIFO` ومنع تشغيل عدة جلسات Chromium في الوقت نفسه.
- تحفظ قاعدة SQLite وملفات JSON وPDF في مجلد `runtime/` على الخادم.
- تنضم الخدمة إلى شبكة Docker الحالية `root_default`.

## المتطلبات التي تم التحقق منها

- Ubuntu 24.04.
- Docker وDocker Compose يعملان.
- حاويتا `root-n8n-1` و`root-traefik-1` تعملان.
- شبكة Docker باسم `root_default` موجودة.
- حالة `n8n` على `/healthz` سليمة.

## 1. تجهيز مجلد المشروع

بعد رفع ملفات المشروع إلى الخادم، افتح Terminal الخادم وانتقل إلى مجلد المشروع:

```bash
cd /opt/shein-extractor
```

أنشئ مجلدات التخزين الدائم:

```bash
mkdir -p runtime/data runtime/exports runtime/outputs
chmod 700 runtime runtime/data runtime/exports runtime/outputs
```

## 2. إنشاء المفتاح السري

لا تضع المفتاح في المحادثات أو مستودع Git. أنشئ ملف `.env` محميًا:

```bash
umask 077
printf 'SHEIN_API_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" > .env
chmod 600 .env
```

يمكن التأكد من وجود اسم المتغير دون إظهار قيمته:

```bash
sed 's/=.*$/=<hidden>/' .env
```

## 3. التحقق من إعداد Compose

```bash
docker compose -f compose.hostinger.yml config --services
docker compose -f compose.hostinger.yml config --images
```

النتيجة المتوقعة تتضمن الخدمة `shein-api` والصورة `shein-extractor-api:0.2.0`.

## 4. بناء الحاوية

```bash
docker compose -f compose.hostinger.yml build --pull
```

قد يستغرق البناء الأول عدة دقائق لأنه يثبت Chromium واعتماداته وخطوط العربية.

## 5. تشغيل الخدمة

```bash
docker compose -f compose.hostinger.yml up -d
docker compose -f compose.hostinger.yml ps
```

تابع السجل عند الحاجة:

```bash
docker compose -f compose.hostinger.yml logs --tail=100 -f shein-api
```

اخرج من المتابعة باستخدام `Ctrl+C`؛ لا يؤدي ذلك إلى إيقاف الحاوية.

## 6. فحص الصحة

افحص الخدمة من داخل حاويتها:

```bash
docker exec shein-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=5).read().decode())"
docker exec shein-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).read().decode())"
```

ثم تحقق من وصول `n8n` إليها عبر الشبكة الداخلية:

```bash
docker exec root-n8n-1 node -e "fetch('http://shein-api:8000/health/live').then(async r => console.log(r.status, await r.text())).catch(e => { console.error(e); process.exit(1) })"
```

يجب أن تظهر حالة HTTP بقيمة `200`.

## 7. التخزين الدائم

تحقق من ربط مجلد التشغيل:

```bash
docker inspect shein-api --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
ls -la runtime runtime/data runtime/exports runtime/outputs
```

بعد إنشاء أول مهمة يجب أن يظهر ملف:

```text
runtime/data/jobs.sqlite3
```

وتظهر ملفات JSON وPDF داخل مجلدي `runtime/outputs` و`runtime/exports`.

## 8. أوامر الإدارة

إعادة التشغيل:

```bash
docker compose -f compose.hostinger.yml restart shein-api
```

الإيقاف دون حذف البيانات:

```bash
docker compose -f compose.hostinger.yml down
```

التشغيل مجددًا:

```bash
docker compose -f compose.hostinger.yml up -d
```

إعادة البناء بعد تحديث الكود:

```bash
docker compose -f compose.hostinger.yml build --pull
docker compose -f compose.hostinger.yml up -d
```

لا تستخدم `docker compose down -v`، ولا تحذف مجلد `runtime/`، لأن ذلك قد يحذف بيانات المهام والتقارير.

## الخطوة التالية بعد نجاح النشر

إنشاء Workflow في `n8n` بالتسلسل التالي:

1. استقبال رسالة Telegram.
2. إرسال محتوى الرسالة إلى `POST /v1/jobs`.
3. متابعة `GET /v1/jobs/{job_id}` حتى تصبح الحالة `completed`.
4. تنزيل الملف من `GET /v1/jobs/{job_id}/pdf`.
5. إرسال PDF إلى مجموعة Telegram نفسها.

