from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def mark_existing_users_as_verified(apps, schema_editor):
    UserModel = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    CustomerProfile = apps.get_model('shop', 'CustomerProfile')
    now = timezone.now()

    for user in UserModel.objects.all().iterator():
        full_name = ' '.join(part for part in [getattr(user, 'first_name', ''), getattr(user, 'last_name', '')] if part).strip()
        CustomerProfile.objects.update_or_create(
            user_id=user.pk,
            defaults={
                'default_pickup_name': full_name or getattr(user, 'username', ''),
                'is_email_verified': True,
                'email_verified_at': now,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0006_emailsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerprofile',
            name='email_verification_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customerprofile',
            name='email_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customerprofile',
            name='is_email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_users_as_verified, migrations.RunPython.noop),
    ]