# RIO — Novel Studio

تطبيق تجريبي متعدد المستخدمين على Flask، يستخدم Gemini API خارج خادم Render. لا يتم تحميل نموذج لغوي محلياً.

## التشغيل على Windows
ثبت Python 3.11+ ثم افتح PowerShell داخل مجلد المشروع:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

افتح `.env` وعدّل `SECRET_KEY` و`GEMINI_API_KEY` و`RIO_ADMIN_USERNAME` و`RIO_ADMIN_PASSWORD`. لا ترفع `.env` إلى GitHub ولا تشارك مفتاح Gemini.

حمّل المتغيرات في جلسة PowerShell الحالية ثم شغّل التطبيق:

```powershell
Get-Content .env | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' -and $_ -notmatch '^\\s*#' } | ForEach-Object {
  $parts = $_ -split '=', 2
  [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
}
python app.py
```

افتح `http://127.0.0.1:5000` لتظهر واجهة الهبوط الجديدة. اضغط «ابدأ حكايتك الآن» للدخول إلى الدردشة مباشرةً من دون تسجيل دخول؛ تُنشأ جلسة زائر تلقائياً. إدارة المستخدمين تبقى محمية، ويمكن للمدير فتح `/login` وتسجيل الدخول ببيانات المدير التي أدخلتها في `.env`. ينشأ حساب المدير عند التشغيل الأول فقط؛ تعديل متغيرات البيئة لاحقاً لا يغير كلمة مرور حساب موجود.

## النشر على Render
1. ارفع ملفات المشروع إلى مستودع GitHub جديد. تأكد أن `.env` غير مرفوع.
2. في Render اختر **New + → Blueprint** واربط المستودع الذي يحتوي `render.yaml`.
3. أو أنشئ Web Service يدوياً بهذه الإعدادات:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
   - Health Check Path: `/health`
4. أضف متغيرات البيئة `SECRET_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `RIO_ADMIN_USERNAME`, `RIO_ADMIN_PASSWORD`, `COOKIE_SECURE=true`.
5. بعد النشر افتح رابط الخدمة لتظهر واجهة RIO العامة. الزوار يستطيعون بدء الدردشة دون تسجيل دخول. لإدارة المستخدمين افتح `/login` وسجّل الدخول بحساب المدير ثم ادخل إلى **إدارة المستخدمين**.

مفتاح Gemini من Google AI Studio. الحصة المجانية محدودة وقد تختلف وتتغير حسب النموذج والحساب؛ راقب الاستهلاك في AI Studio.

## الصلاحيات
- **admin:** استخدام RIO وإدارة المستخدمين والصلاحيات.
- **writer:** استخدام المحادثة.
- **reader:** عرض مساحة العمل دون إرسال رسائل.
الواجهة العامة والدردشة متاحتان للزوار دون تسجيل؛ تُنشأ جلسة زائر تلقائياً. إدارة الحسابات محمية بتسجيل دخول المدير. سجلات جلسات الزوار تجريبية ويمكن أن تتراكم في قاعدة البيانات المؤقتة.

## مهم: تخزين مؤقت فقط
قاعدة البيانات SQLite تُحفظ في ملف مؤقت (`/tmp` على Render). قد تفقد الحسابات والمحادثات عند إعادة التشغيل أو إعادة النشر أو إيقاف الخدمة. لا تستخدم هذه النسخة لبيانات حساسة أو إنتاج حقيقي. قبل الاستخدام الدائم استبدل SQLite بـ PostgreSQL دائمة وأضف النسخ الاحتياطي ومراجعة أمنية.

## استكشاف الأخطاء
- `GEMINI_API_KEY`: أضف المفتاح كمتغير بيئة ثم أعد النشر.
- تعذر الاتصال: تحقق من المفتاح، واسم النموذج، والحصة وسجلات Render.
- محلياً استخدم `127.0.0.1:5000` وليس `0.0.0.0:5000`.
- إذا فقدت قاعدة البيانات التجريبية، أنشئ حساب المدير من متغيرات البيئة عند التشغيل الأول بعد حذف الملف المحلي `rio_temporary.sqlite3` إذا كنت تقبل فقدان كل البيانات الموجودة.

## محتويات الحزمة
`app.py` خادم Flask، `templates/landing.html` واجهة الهبوط المتحركة، `templates/` صفحات التطبيق والإدارة، `static/style.css` التصميم، `requirements.txt` المكتبات، `render.yaml` إعداد Render، `.env.example` مثال آمن بلا مفاتيح حقيقية.


## إعداد مفاتيح RIO في ملف التطبيق

افتح `app.py` وعدّل القيم `SECRET_KEY` و`GEMINI_API_KEY` في أعلى الملف. لا تستخدم مفتاحًا سبق نشره أو مشاركته. لا تحتاج إلى ملف `.env` لهذه الإعدادات في هذه النسخة.
