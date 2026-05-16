from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import CustomerProfile, ProductVariantSelectedOption


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_customer_profile(sender, instance, created, **kwargs):
    if created:
        CustomerProfile.objects.create(user=instance, default_pickup_name=instance.get_full_name())


def sync_variant_legacy_option_fields(variant):
    selected_values = {
        selection.option.name.strip().lower(): selection.option_value.value
        for selection in variant.selected_options.select_related('option', 'option_value')
    }
    updates = {}
    for field_name in ('color', 'size', 'finish'):
        next_value = selected_values.get(field_name, '')
        if getattr(variant, field_name) != next_value:
            updates[field_name] = next_value

    if updates:
        for field_name, field_value in updates.items():
            setattr(variant, field_name, field_value)
        variant.updated_at = timezone.now()
        variant.save(update_fields=[*updates.keys(), 'updated_at'])


@receiver(post_save, sender=ProductVariantSelectedOption)
def sync_variant_legacy_fields_after_save(sender, instance, **kwargs):
    sync_variant_legacy_option_fields(instance.variant)


@receiver(post_delete, sender=ProductVariantSelectedOption)
def sync_variant_legacy_fields_after_delete(sender, instance, **kwargs):
    sync_variant_legacy_option_fields(instance.variant)
