from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from shop.models import Product, ProductMedia


class Command(BaseCommand):
    help = 'Convert existing product image media to WebP and replace legacy source files.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show which files would be converted without changing stored media.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        converted = 0
        skipped = 0

        for product in Product.objects.exclude(image='').iterator():
            if product.image.name.lower().endswith('.webp'):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f'Would convert product cover: {product.image.name}')
                converted += 1
                continue

            try:
                product.save(update_fields=['image'])
            except (FileNotFoundError, OSError, ValidationError) as exc:
                skipped += 1
                self.stderr.write(f'Skipped product {product.pk} ({product.image.name}): {exc}')
                continue

            converted += 1
            self.stdout.write(f'Converted product cover: {product.image.name}')

        for media in ProductMedia.objects.filter(media_type=ProductMedia.TYPE_IMAGE).iterator():
            if media.file.name.lower().endswith('.webp'):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f'Would convert gallery image: {media.file.name}')
                converted += 1
                continue

            try:
                media.save(update_fields=['file'])
            except (FileNotFoundError, OSError, ValidationError) as exc:
                skipped += 1
                self.stderr.write(f'Skipped media {media.pk} ({media.file.name}): {exc}')
                continue

            converted += 1
            self.stdout.write(f'Converted gallery image: {media.file.name}')

        self.stdout.write(self.style.SUCCESS(f'Backfill complete. Converted: {converted}. Skipped: {skipped}.'))