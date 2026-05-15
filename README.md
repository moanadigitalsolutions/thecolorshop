# The Color Shop eCommerce Platform

Django MVP for The Color Shop in Apia, Samoa. Phase 1 supports product browsing, variant/SKU inventory, authenticated carts, pickup-only checkout, cash-at-store payment, order history, Django admin management, and Brevo-ready email logging.

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
- Customers must log in before checkout.
- Products sell through first-class variants/SKUs for stock accuracy.
- Brevo email is skipped locally until `BREVO_API_KEY` is configured.

## Production Notes

Use SQLite for development and MySQL in production by setting `DB_ENGINE=mysql` and the database environment variables. Configure cPanel Application Manager with the project virtual environment, run migrations, collect static files, set `DJANGO_DEBUG=False`, configure allowed hosts/CSRF origins, and set Brevo sender/API values.
