from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Product


class StaticViewSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return ['product_list']

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Product.objects.filter(is_active=True).order_by('name')

    def lastmod(self, item):
        return item.updated_at


sitemaps = {
    'static': StaticViewSitemap,
    'products': ProductSitemap,
}