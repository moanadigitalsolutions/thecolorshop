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

Use SQLite for development and MySQL in production by setting `DB_ENGINE=mysql` and the database environment variables. Configure cPanel Application Manager with the project virtual environment, run migrations, collect static files, set `DJANGO_DEBUG=False`, configure allowed hosts/CSRF origins, and set SMTP or Brevo sender values in the environment. The active provider is selected by staff in the portal and defaults to SMTP.

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
