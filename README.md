# The Color Shop eCommerce Platform

Django MVP for The Color Shop in Apia, Samoa. Phase 1 supports product browsing, variant/SKU inventory, authenticated carts, pickup-only checkout, cash-at-store payment, order history, Django admin management, SMTP-first email delivery with optional Brevo switching, and email verification for new customer accounts.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/ for the storefront and http://127.0.0.1:8000/admin/ for admin.

## Phase 1 Rules

- Pickup only from `569J+3VH, Togafu'afu'a Rd, Apia, Samoa`.
- Payment method is cash at store.
- Customers must verify their email address before they can log in and checkout.
- Products sell through first-class variants/SKUs for stock accuracy.
- SMTP is the default email method and uses the configured `EMAIL_HOST`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD` values.
- Staff can switch the active email provider in the custom staff portal at `/staff/email-settings/`.
- Brevo remains optional and is skipped until `BREVO_API_KEY` is configured.
- New customer signups receive a verification email and must confirm their email before login.

## Production Notes

Use SQLite for development and MySQL in production by setting `DB_ENGINE=mysql` and the database environment variables. The project now uses `PyMySQL` for production MySQL access so cPanel deployments do not depend on compiling `mysqlclient`. Configure cPanel Application Manager with the project virtual environment, run migrations, collect static files, set `DJANGO_DEBUG=False`, configure allowed hosts/CSRF origins, and set SMTP or Brevo sender values in the environment. The active provider is selected by staff in the portal and defaults to SMTP.

Static and media roots are now environment-driven so production can point Apache directly at filesystem paths:

- `DJANGO_STATIC_URL` defaults to `/static/`
- `DJANGO_STATIC_ROOT` defaults to `BASE_DIR/staticfiles`
- `DJANGO_MEDIA_URL` defaults to `/media/`
- `DJANGO_MEDIA_ROOT` defaults to `BASE_DIR/media`

For cPanel + Apache, set the roots to web-served directories, then run collectstatic during deployment:

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Typical production values look like:

```env
DJANGO_STATIC_ROOT=/home/username/public_html/static
DJANGO_MEDIA_ROOT=/home/username/public_html/media
```

Then configure Apache aliases or cPanel application mappings so `/static/` serves the static root and `/media/` serves the media root. In production, static files use manifest storage for cache-busted asset names, so `collectstatic` must be part of each deployment.

## Release Packaging

Build the deployment archives from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\package_release.ps1
```

This creates:

- `dist/tcs-app-release.zip` for the Django application code and cPanel startup file
- `dist/tcs-media-bootstrap.zip` for the existing `media/` tree used on the first deployment or when curated media changes

The app archive intentionally includes only the deployment payload:

- `config/`
- `shop/`
- `templates/`
- `static/`
- `manage.py`
- `requirements.txt`
- `README.md`
- `.env.example`
- `.env.production.example`
- `passenger_wsgi.py`

Do not upload `.env`, `.venv/`, `db.sqlite3`, `*.sqlite3`, `staticfiles/`, `__pycache__/`, or `.git/`.

## cPanel Application Manager

Create a Python application in cPanel Application Manager with:

- App root: `/home/USERNAME/colourshop`
- Startup file: `passenger_wsgi.py`
- Entry point: `application`
- Application URL: `https://colourshop.ws/`

Create the production `.env` directly on the server in the app root. Do not upload the local `.env` file.

Use `.env.production.example` as the exact production starting point, then fill in only the blank database and mail values.

Example cPanel terminal release commands after the app has been created and the zip files have been uploaded:

```bash
cd /home/USERNAME/colourshop
unzip -o /home/USERNAME/uploads/tcs-app-release.zip -d /home/USERNAME/colourshop

/opt/alt/python-internal/bin/python3.11 -m venv venv
source /home/USERNAME/colourshop/venv/bin/activate
pip install -r requirements.txt

mkdir -p /home/USERNAME/public_html/static
mkdir -p /home/USERNAME/public_html/media

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

For Passenger on this VPS, set the shebang at the top of `passenger_wsgi.py` to the application virtual environment after you create it:

```python
#!/home/USERNAME/colourshop/venv/bin/python
```

Only run a media unzip command if `dist/tcs-media-bootstrap.zip` exists. The current repository media tree has no files, so the packaging script skips that archive until real media is present.

The production template looks like:

```env
DJANGO_SECRET_KEY=replace-with-a-new-secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=colourshop.ws,www.colourshop.ws
DJANGO_CSRF_TRUSTED_ORIGINS=https://colourshop.ws,https://www.colourshop.ws
DJANGO_TIME_ZONE=Pacific/Apia
SITE_BASE_URL=https://colourshop.ws
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=False

DB_ENGINE=mysql
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=3306

DJANGO_STATIC_URL=/static/
DJANGO_STATIC_ROOT=/home/<cpanel-username>/public_html/static
DJANGO_MEDIA_URL=/media/
DJANGO_MEDIA_ROOT=/home/<cpanel-username>/public_html/media

DEFAULT_FROM_EMAIL=
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=465
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_SSL=True
EMAIL_USE_TLS=False
EMAIL_TIMEOUT=10

PASSWORD_RESET_TIMEOUT=86400
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS=300

BREVO_API_KEY=
BREVO_SENDER_EMAIL=
BREVO_SENDER_NAME=The Color Shop

STORE_CONTACT_PHONE=+68525577
STORE_PICKUP_ADDRESS=569J+3VH, Togafu'afu'a Rd, Apia, Samoa
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_MINUTES=30
RATELIMIT_ENABLE=True
```

Use the virtual environment activation path shown by Application Manager if it differs from the example above.
