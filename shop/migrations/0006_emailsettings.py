from django.db import migrations, models


def create_default_email_settings(apps, schema_editor):
    EmailSettings = apps.get_model('shop', 'EmailSettings')
    EmailSettings.objects.get_or_create(pk=1, defaults={'email_provider': 'smtp'})


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0005_storelocation_variantinventorylevel_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('email_provider', models.CharField(choices=[('smtp', 'SMTP'), ('brevo', 'Brevo')], default='smtp', max_length=20)),
            ],
            options={
                'verbose_name': 'email settings',
                'verbose_name_plural': 'email settings',
            },
        ),
        migrations.RunPython(create_default_email_settings, migrations.RunPython.noop),
    ]