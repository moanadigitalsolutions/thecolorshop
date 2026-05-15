The Color Shop eCommerce Platform — Project Plan
1) Project Overview
Client: The Color Shop
Location: 569J+3VH, Togafu'afu'a Rd, Apia, Samoa
Contact: +68525577

Business model
The platform will support:
Local customers in Samoa
Samoan customers overseas buying for family back home in Samoa
Fulfillment model
Pick-up only
No delivery
No shipping
Payment model
Phase 1: No payment gateway
Customers place orders online
Customers pay cash at the store when picking up
Communication
Email notifications via Brevo API
System access
Customer authentication required
Admin backend access required
Technical constraints
Backend aligned with Python + MySQL
Use SQLite during development
Deploy to VPS via cPanel Application Manager
2) Project Goals
Primary goals
Allow customers to browse products online
Let customers place pickup orders
Support overseas users ordering for family in Samoa
Provide admin management for products, orders, and customers
Automate email communications through Brevo
Launch Phase 1 quickly with cash-on-pickup workflow
3) Recommended Platform Scope
Customer-facing features
User registration and login
Product catalog
Product categories
Product search and filtering
Product detail pages
Add to cart
Checkout with pickup-only order flow
Customer order history
Order status tracking
Email notifications for order confirmation and status updates
Admin features
Admin login
Dashboard
Product management
Category management
Inventory/stock management
Order management
Customer management
Manual order status updates
Email trigger controls through Brevo
Reports/basic analytics
4) Phase Plan
Phase 1 — MVP Launch
Focus: get the store online quickly with core ordering and admin management.
Phase 1 features
Customer authentication
Product listing and categories
Cart and checkout
Pickup-only order placement
Cash-at-store payment method
Email notifications via Brevo
Admin dashboard
Admin product/order management
Basic SEO and mobile responsiveness
Deployment to VPS using cPanel Application Manager
Phase 1 exclusions
Online payment gateway
Delivery/shipping
Advanced loyalty features
Multi-branch support
Advanced reporting
SMS notifications
Phase 2 — Expansion
Possible future additions:
Payment gateway integration
Saved family recipient details
Order gifting notes
Inventory alerts
Promo codes / discount campaigns
Advanced reporting
WhatsApp/SMS notifications
Better customer account features
5) Suggested Tech Stack
Because you want Python/MySQL backend and SQLite during development, here is a good fit:

Backend
Python
Django recommended for speed, admin panel, authentication, ORM, and deployment maturity
Django REST Framework only if you want API-first architecture
Database
SQLite for development
MySQL for production
Frontend
Options:
Django templates + Bootstrap
- Best for speed and simpler deployment
React frontend + Django API
- Better for long-term scalability, but more complex
Email
Brevo API
Deployment
cPanel Application Manager
VPS-hosted Python app
MySQL database on production server
Other tools
Git/GitHub for version control
Celery + Redis optional for background email jobs if needed later
Pillow for image handling
Django admin for quick backend management
6) Recommended System Architecture
High-level flow
Customer registers or logs in
Browses products
Adds products to cart
Chooses pickup
Submits order
System creates order with status like Pending Pickup Payment
Brevo sends confirmation email
Admin reviews order
Customer picks up and pays cash in store
Admin marks order as completed
7) Core Data Entities
Main database tables
Users
Customer profiles
Admin users
Products
Product categories
Product images
Orders
Order items
Pickup locations
Email logs
Inventory/stock records
Important order fields
Order number
Customer name
Customer email
Pickup location
Pickup status
Payment method = cash at store
Order status
Notes / special instructions
Created date
8) Business Rules
Pickup rules
Only pickup allowed
No delivery option shown
No shipping option shown
Pickup must be from:
569J+3VH, Togafu'afu'a Rd, Apia, Samoa
Payment rules
Phase 1 payment method is cash at store
Orders are created online without online payment
Admin can confirm pickup payment manually
Communication rules
Email confirmation after order placement
Email status updates when order changes
Use Brevo API for outgoing emails
9) Suggested Development Phases and Timeline
Here is a practical implementation plan:

Phase 0 — Discovery and Planning
Duration: 1 week
Confirm product categories
Confirm order workflow
Confirm email templates
Confirm admin roles
Finalize sitemap and user journey
Phase 1 — Core Build
Duration: 2–4 weeks
Set up Django project
Create authentication
Build product catalog
Build cart and checkout
Build order model
Build admin dashboard
Integrate Brevo API
Add basic UI
Phase 2 — Testing and Refinement
Duration: 1–2 weeks
Functional testing
Mobile testing
Email testing
Admin workflow testing
Fix bugs and improve UX
Phase 3 — Deployment
Duration: 1 week
Configure VPS/cPanel Application Manager
Set production MySQL
Set environment variables
Deploy code
Run production checks
Go live
10) Suggested MVP User Journey
Local customer
Visits site
Registers/logs in
Browses products
Adds items to cart
Places pickup order
Receives email
Collects and pays at store
Overseas customer
Visits site
Registers/logs in
Selects products for family in Samoa
Places pickup order
Enters family member pickup name if needed
Receives confirmation email
Family picks up and pays cash at store
11) Risks and Considerations
Potential risks
Product catalog complexity if many paint variants/colors exist
Inventory accuracy if stock is managed manually
Overseas users may need clear pickup instructions
Email deliverability needs proper Brevo setup
cPanel Python deployment needs careful environment configuration
Mitigation
Use structured product categories and attributes
Add stock tracking in admin
Make pickup instructions very clear
Configure Brevo domain/email properly
Test deployment on staging before production