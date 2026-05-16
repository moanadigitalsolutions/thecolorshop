from django.utils.text import slugify

from import_export import fields, resources, widgets

from .models import Category, Product, ProductTag, ProductVariant, ProductVariantSelectedOption, StoreLocation, VariantInventoryLevel


PRODUCT_IMPORT_KEY = 'products'
VARIANT_IMPORT_KEY = 'variants'
INVENTORY_IMPORT_KEY = 'inventory'


class CategoryWidget(widgets.ForeignKeyWidget):
    def clean(self, value, row=None, **kwargs):
        normalized_value = (value or '').strip()
        if not normalized_value:
            raise ValueError('Category is required.')

        category = Category.objects.filter(slug=normalized_value).first()
        if category:
            return category

        category = Category.objects.filter(name__iexact=normalized_value).first()
        if category:
            return category

        raise ValueError(f'Unknown category: {normalized_value}.')

    def render(self, value, obj=None, **kwargs):
        return value.slug if value else ''


class ProductWidget(widgets.ForeignKeyWidget):
    def clean(self, value, row=None, **kwargs):
        normalized_value = (value or '').strip()
        if not normalized_value:
            raise ValueError('Product is required.')

        product = Product.objects.filter(slug=normalized_value).first()
        if product:
            return product

        product = Product.objects.filter(name__iexact=normalized_value).first()
        if product:
            return product

        raise ValueError(f'Unknown product: {normalized_value}.')

    def render(self, value, obj=None, **kwargs):
        return value.slug if value else ''


class StoreLocationWidget(widgets.ForeignKeyWidget):
    def clean(self, value, row=None, **kwargs):
        normalized_value = (value or '').strip()
        if not normalized_value:
            raise ValueError('Location is required.')

        location = StoreLocation.objects.filter(name__iexact=normalized_value).first()
        if location:
            return location

        raise ValueError(f'Unknown location: {normalized_value}.')

    def render(self, value, obj=None, **kwargs):
        return value.name if value else ''


class ProductTagWidget(widgets.ManyToManyWidget):
    def clean(self, value, row=None, **kwargs):
        cleaned_tags = []
        for tag_name in self.split(value):
            normalized_name = tag_name.strip()
            if not normalized_name:
                continue
            tag, _created = ProductTag.objects.get_or_create(
                slug=slugify(normalized_name),
                defaults={'name': normalized_name},
            )
            if tag.name != normalized_name:
                tag.name = normalized_name
                tag.save(update_fields=['name'])
            cleaned_tags.append(tag)
        return cleaned_tags

    def render(self, value, obj=None, **kwargs):
        if value is None:
            return ''
        return self.separator.join(value.order_by('name').values_list('name', flat=True))


class StoreLocationManyToManyWidget(widgets.ManyToManyWidget):
    def clean(self, value, row=None, **kwargs):
        cleaned_locations = []
        seen_locations = set()
        for location_name in self.split(value):
            normalized_name = location_name.strip()
            if not normalized_name:
                continue
            lookup_key = normalized_name.casefold()
            if lookup_key in seen_locations:
                continue
            location = StoreLocation.objects.filter(name__iexact=normalized_name).first()
            if not location:
                raise ValueError(f'Unknown pickup location: {normalized_name}.')
            seen_locations.add(lookup_key)
            cleaned_locations.append(location)
        return cleaned_locations

    def render(self, value, obj=None, **kwargs):
        if value is None:
            return ''
        return self.separator.join(value.order_by('sort_order', 'name').values_list('name', flat=True))


def parse_option_value_string(raw_value):
    parsed_values = []
    seen_names = set()
    for chunk in (raw_value or '').split('|'):
        entry = chunk.strip()
        if not entry:
            continue
        if '=' not in entry:
            raise ValueError('Use the format "Option=Value|Option=Value" for variant option values.')
        option_name, option_value = [part.strip() for part in entry.split('=', 1)]
        if not option_name or not option_value:
            raise ValueError('Each option entry must include both an option name and a value.')
        normalized_name = option_name.casefold()
        if normalized_name in seen_names:
            raise ValueError(f'{option_name} is listed more than once.')
        seen_names.add(normalized_name)
        parsed_values.append((option_name, option_value))
    return parsed_values


class ProductResource(resources.ModelResource):
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=CategoryWidget(Category, field='slug'),
    )
    tags = fields.Field(
        column_name='tags',
        attribute='tags',
        widget=ProductTagWidget(ProductTag, field='name', separator='|'),
    )
    pickup_locations = fields.Field(
        column_name='pickup_locations',
        attribute='pickup_locations',
        widget=StoreLocationManyToManyWidget(StoreLocation, field='name', separator='|'),
    )

    class Meta:
        model = Product
        import_id_fields = ('slug',)
        fields = (
            'category',
            'name',
            'slug',
            'description',
            'meta_title',
            'meta_description',
            'is_active',
            'is_featured',
            'tags',
            'pickup_locations',
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = False
        clean_model_instances = True

    def before_import_row(self, row, **kwargs):
        row['slug'] = (row.get('slug') or '').strip() or slugify((row.get('name') or '').strip())
        if not row['slug']:
            raise ValueError('Each product row needs either a slug or a name.')
        return super().before_import_row(row, **kwargs)


class ProductVariantResource(resources.ModelResource):
    product = fields.Field(
        column_name='product',
        attribute='product',
        widget=ProductWidget(Product, field='slug'),
    )
    option_values = fields.Field(column_name='option_values')

    class Meta:
        model = ProductVariant
        import_id_fields = ('sku',)
        fields = (
            'product',
            'sku',
            'option_values',
            'color',
            'size',
            'finish',
            'price',
            'sale_price',
            'stock_quantity',
            'low_stock_threshold',
            'is_active',
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = False
        clean_model_instances = True

    def dehydrate_option_values(self, variant):
        return '|'.join(f'{name}={value}' for name, value in variant.option_summary)

    def before_import_row(self, row, **kwargs):
        product_value = (row.get('product') or '').strip()
        if not product_value:
            raise ValueError('Each variant row needs a product slug or product name.')

        product = Product.objects.prefetch_related('options__option_values').filter(slug=product_value).first()
        if product is None:
            product = Product.objects.prefetch_related('options__option_values').filter(name__iexact=product_value).first()

        option_pairs = parse_option_value_string(row.get('option_values', ''))
        product_options = {option.name.casefold(): option for option in product.options.all()} if product else {}
        if product_options:
            if not option_pairs:
                raise ValueError('Option-driven variants must provide option_values for every product option.')
            missing_options = [option.name for option in product.options.all() if option.name.casefold() not in {name.casefold() for name, _value in option_pairs}]
            if missing_options:
                raise ValueError(f'Missing option value(s): {", ".join(missing_options)}.')
            for option_name, option_value in option_pairs:
                product_option = product_options.get(option_name.casefold())
                if not product_option:
                    raise ValueError(f'{option_name} is not defined on {product.name}.')
                if not product_option.option_values.filter(value=option_value).exists():
                    raise ValueError(f'{option_value} is not a valid value for {option_name} on {product.name}.')

        return super().before_import_row(row, **kwargs)

    def after_save_instance(self, instance, row, **kwargs):
        super().after_save_instance(instance, row, **kwargs)
        if kwargs.get('dry_run'):
            return

        option_pairs = parse_option_value_string(row.get('option_values', ''))
        if option_pairs:
            product_options = {
                option.name.casefold(): option
                for option in instance.product.options.prefetch_related('option_values').all()
            }
            kept_option_ids = set()
            for sort_order, (option_name, option_value) in enumerate(option_pairs, start=1):
                product_option = product_options.get(option_name.casefold())
                if not product_option:
                    continue
                selected_value = product_option.option_values.get(value=option_value)
                selection, created = ProductVariantSelectedOption.objects.get_or_create(
                    variant=instance,
                    option=product_option,
                    defaults={'option_value': selected_value, 'sort_order': sort_order},
                )
                if not created and (selection.option_value_id != selected_value.id or selection.sort_order != sort_order):
                    selection.option_value = selected_value
                    selection.sort_order = sort_order
                    selection.save(update_fields=['option_value', 'sort_order', 'updated_at'])
                kept_option_ids.add(product_option.id)

            instance.selected_options.exclude(option_id__in=kept_option_ids).delete()


class VariantInventoryLevelResource(resources.ModelResource):
    variant = fields.Field(
        column_name='variant',
        attribute='variant',
        widget=widgets.ForeignKeyWidget(ProductVariant, field='sku'),
    )
    location = fields.Field(
        column_name='location',
        attribute='location',
        widget=StoreLocationWidget(StoreLocation, field='name'),
    )

    class Meta:
        model = VariantInventoryLevel
        import_id_fields = ('variant', 'location')
        fields = ('variant', 'location', 'quantity')
        export_order = fields
        skip_unchanged = True
        report_skipped = False
        clean_model_instances = True

    def after_save_instance(self, instance, row, **kwargs):
        super().after_save_instance(instance, row, **kwargs)
        if kwargs.get('dry_run'):
            return
        instance.variant.sync_stock_quantity_from_inventory_levels()


IMPORT_EXPORT_DEFINITIONS = {
    PRODUCT_IMPORT_KEY: {
        'label': 'Products',
        'filename': 'products',
        'resource_class': ProductResource,
        'description': 'Bulk update product catalogue rows, SEO text, tags, and pickup availability.',
    },
    VARIANT_IMPORT_KEY: {
        'label': 'Variants',
        'filename': 'variants',
        'resource_class': ProductVariantResource,
        'description': 'Bulk update SKU pricing, stock thresholds, active flags, and option-driven variant assignments.',
    },
    INVENTORY_IMPORT_KEY: {
        'label': 'Inventory by location',
        'filename': 'inventory-levels',
        'resource_class': VariantInventoryLevelResource,
        'description': 'Bulk update on-hand quantities per SKU and pickup location.',
    },
}


def get_import_export_definition(resource_key):
    return IMPORT_EXPORT_DEFINITIONS.get(resource_key)