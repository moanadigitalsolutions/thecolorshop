from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .services import send_password_reset_email

from .models import (
    EmailSettings,
    Order,
    Product,
    ProductMedia,
    ProductOption,
    ProductOptionValue,
    ProductTag,
    ProductVariant,
    ProductVariantSelectedOption,
    StoreLocation,
    VariantInventoryLevel,
)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        if not data:
            return []
        return [single_file_clean(data, initial)]


def parse_option_values(raw_value):
    parsed_values = []
    seen_values = set()
    for item in raw_value.split(','):
        value = item.strip()
        if not value:
            continue
        normalized_value = value.casefold()
        if normalized_value in seen_values:
            continue
        seen_values.add(normalized_value)
        parsed_values.append(value)
    return parsed_values


def parse_inventory_breakdown(raw_value):
    entries = []
    seen_locations = set()

    for chunk in raw_value.split(';'):
        entry = chunk.strip()
        if not entry:
            continue
        if ':' not in entry:
            raise forms.ValidationError('Use the format "Location: quantity" for inventory entries.')

        location_name, quantity_value = [value.strip() for value in entry.split(':', 1)]
        if not location_name:
            raise forms.ValidationError('Each inventory entry must include a location name.')
        if not quantity_value.isdigit():
            raise forms.ValidationError('Inventory quantities must be whole numbers.')

        normalized_name = location_name.casefold()
        if normalized_name in seen_locations:
            raise forms.ValidationError(f'{location_name} is listed more than once.')

        seen_locations.add(normalized_name)
        entries.append((location_name, int(quantity_value)))

    return entries


def build_product_option_definitions(product=None, data=None, prefix='options'):
    definitions = []

    if data is not None:
        total_forms = int(data.get(f'{prefix}-TOTAL_FORMS', 0) or 0)
        for index in range(total_forms):
            if (data.get(f'{prefix}-{index}-DELETE') or '').strip():
                continue
            name = (data.get(f'{prefix}-{index}-name') or '').strip()
            values = parse_option_values(data.get(f'{prefix}-{index}-option_values', ''))
            if not name or not values:
                continue
            definitions.append({'name': name, 'values': values, 'sort_order': len(definitions) + 1})
        return definitions

    if product and product.pk:
        for option in product.options.prefetch_related('option_values').order_by('sort_order', 'id'):
            values = list(option.option_values.order_by('sort_order', 'id').values_list('value', flat=True))
            if not values:
                continue
            definitions.append({'name': option.name, 'values': values, 'sort_order': option.sort_order})

    return definitions


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    phone_number = forms.CharField(max_length=40, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            user.customer_profile.phone_number = self.cleaned_data.get('phone_number', '')
            user.customer_profile.default_pickup_name = user.get_full_name()
            user.customer_profile.is_email_verified = False
            user.customer_profile.email_verified_at = None
            user.customer_profile.email_verification_sent_at = None
            user.customer_profile.save(
                update_fields=[
                    'phone_number',
                    'default_pickup_name',
                    'is_email_verified',
                    'email_verified_at',
                    'email_verification_sent_at',
                    'updated_at',
                ]
            )
        return user


class CustomerAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'unverified': 'Please verify your email address before logging in.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update(
            {
                'class': 'form-control',
                'autocomplete': 'username',
                'placeholder': 'Username',
            }
        )
        self.fields['password'].widget.attrs.update(
            {
                'class': 'form-control',
                'autocomplete': 'current-password',
                'placeholder': 'Password',
            }
        )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_staff:
            return
        profile = getattr(user, 'customer_profile', None)
        if not profile or not profile.is_email_verified:
            raise forms.ValidationError(self.error_messages['unverified'], code='unverified')


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}))


class PasswordResetRequestForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({'class': 'form-control', 'autocomplete': 'email'})

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        user = context['user']
        reset_path = reverse(
            'password_reset_confirm',
            kwargs={'uidb64': context['uid'], 'token': context['token']},
        )
        reset_url = f"{context['protocol']}://{context['domain']}{reset_path}"
        send_password_reset_email(user, reset_url)


class PasswordResetSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update({'class': 'form-control', 'autocomplete': 'new-password'})
        self.fields['new_password2'].widget.attrs.update({'class': 'form-control', 'autocomplete': 'new-password'})


class StaffAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'non_staff': 'This account does not have staff portal access.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update(
            {
                'class': 'form-control staff-input',
                'autocomplete': 'username',
                'placeholder': 'Staff username',
            }
        )
        self.fields['password'].widget.attrs.update(
            {
                'class': 'form-control staff-input',
                'autocomplete': 'current-password',
                'placeholder': 'Password',
            }
        )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(self.error_messages['non_staff'], code='non_staff')


class CheckoutForm(forms.ModelForm):
    pickup_location_choice = forms.ModelChoiceField(
        required=False,
        queryset=StoreLocation.objects.none(),
        empty_label=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Order
        fields = [
            'customer_name',
            'customer_email',
            'customer_phone',
            'pickup_name',
            'pickup_phone',
            'special_instructions',
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'name'}),
            'customer_email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'tel'}),
            'pickup_name': forms.TextInput(attrs={'class': 'form-control'}),
            'pickup_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'special_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        StoreLocation.ensure_default_location()
        pickup_locations = StoreLocation.objects.filter(is_active=True, is_pickup_enabled=True)
        self.fields['pickup_location_choice'].queryset = pickup_locations
        if not self.initial.get('pickup_location_choice'):
            self.initial['pickup_location_choice'] = pickup_locations.first()

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data['pickup_location_object'] = cleaned_data.get('pickup_location_choice') or StoreLocation.ensure_default_location()
        return cleaned_data


class OrderStaffStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ('status', 'special_instructions')
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select staff-select'}),
            'special_instructions': forms.Textarea(
                attrs={
                    'class': 'form-control staff-textarea',
                    'rows': 4,
                    'placeholder': 'Internal notes or pickup handoff details.',
                }
            ),
        }


class ProductFilterForm(forms.Form):
    q = forms.CharField(required=False, label='Search')
    category = forms.CharField(required=False)


class StaffCatalogExportForm(forms.Form):
    resource = forms.ChoiceField(
        choices=[
            ('products', 'Products'),
            ('variants', 'Variants'),
            ('inventory', 'Inventory by location'),
        ],
        widget=forms.Select(attrs={'class': 'form-select staff-select'}),
    )


class StaffCatalogImportForm(forms.Form):
    resource = forms.ChoiceField(
        choices=[
            ('products', 'Products'),
            ('variants', 'Variants'),
            ('inventory', 'Inventory by location'),
        ],
        widget=forms.Select(attrs={'class': 'form-select staff-select'}),
    )
    import_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-control staff-file-input', 'accept': '.csv,text/csv'}),
    )

    def clean_import_file(self):
        import_file = self.cleaned_data['import_file']
        if not import_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('Upload a CSV file exported from the bulk tools or Django admin.')
        return import_file


class StoreLocationStaffForm(forms.ModelForm):
    class Meta:
        model = StoreLocation
        fields = ('name', 'address', 'pickup_instructions', 'sort_order', 'is_active', 'is_pickup_enabled')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'Apia Store'}),
            'address': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': "569J+3VH, Togafu'afu'a Rd, Apia, Samoa"}),
            'pickup_instructions': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'Front counter pickup'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control staff-input', 'min': '0'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_pickup_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class EmailSettingsStaffForm(forms.ModelForm):
    class Meta:
        model = EmailSettings
        fields = ('email_provider',)
        widgets = {
            'email_provider': forms.Select(attrs={'class': 'form-select staff-select'}),
        }


class ProductStaffForm(forms.ModelForm):
    tags_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'interior, premium, bestseller'}),
    )
    media_files = MultipleFileField(
        required=False,
        widget=MultipleFileInput(
            attrs={
                'class': 'form-control staff-file-input',
                'accept': 'image/*,video/*,audio/*',
                'data-media-input': 'true',
            }
        ),
    )
    pickup_locations = forms.ModelMultipleChoiceField(
        required=False,
        queryset=StoreLocation.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select staff-select', 'size': '4'}),
    )

    class Meta:
        model = Product
        fields = ('name', 'slug', 'description', 'meta_title', 'meta_description', 'image', 'category', 'is_active', 'is_featured')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'Product title'}),
            'slug': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'product-handle'}),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control staff-textarea',
                    'rows': 8,
                    'placeholder': 'Write product details, usage notes, or pickup guidance.',
                }
            ),
            'meta_title': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'Search result title'}),
            'meta_description': forms.Textarea(
                attrs={
                    'class': 'form-control staff-textarea',
                    'rows': 4,
                    'placeholder': 'Short search summary for Google and social previews.',
                }
            ),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control staff-file-input'}),
            'category': forms.Select(attrs={'class': 'form-select staff-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        StoreLocation.ensure_default_location()
        self.fields['slug'].required = False
        self.fields['category'].empty_label = 'Select a category'
        self.fields['pickup_locations'].queryset = StoreLocation.objects.filter(is_active=True, is_pickup_enabled=True)
        if self.instance.pk:
            self.fields['tags_input'].initial = ', '.join(self.instance.tags.order_by('name').values_list('name', flat=True))
            self.fields['pickup_locations'].initial = self.instance.pickup_locations.filter(is_active=True, is_pickup_enabled=True)

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip()
        name = (self.cleaned_data.get('name') or '').strip()
        candidate = slugify(slug or name)
        if not candidate:
            raise forms.ValidationError('Enter a product title so a handle can be created.')
        slug_query = Product.objects.filter(slug=candidate)
        if self.instance.pk:
            slug_query = slug_query.exclude(pk=self.instance.pk)
        if slug_query.exists():
            raise forms.ValidationError('A product with this handle already exists.')
        return candidate

    def clean_tags_input(self):
        return ', '.join(parse_option_values(self.cleaned_data.get('tags_input', '')))

    def clean_media_files(self):
        uploads = self.cleaned_data.get('media_files', [])
        for upload in uploads:
            if ProductMedia.detect_media_type(upload) == ProductMedia.TYPE_FILE:
                raise forms.ValidationError('Only image, video, or audio files are supported in the product gallery.')
        return uploads

    def save(self, commit=True):
        product = super().save(commit=commit)
        if not commit:
            return product

        tag_names = parse_option_values(self.cleaned_data.get('tags_input', ''))
        tags = []
        for tag_name in tag_names:
            tag, _created = ProductTag.objects.get_or_create(
                slug=slugify(tag_name),
                defaults={'name': tag_name},
            )
            if tag.name != tag_name:
                tag.name = tag_name
                tag.save(update_fields=['name'])
            tags.append(tag)
        product.tags.set(tags)
        product.pickup_locations.set(self.cleaned_data.get('pickup_locations', []))
        return product

    def save_media_files(self, product):
        uploads = self.cleaned_data.get('media_files', [])
        if not uploads:
            return

        next_sort_order = product.media_assets.count()
        has_primary_media = product.media_assets.filter(is_primary=True).exists()
        for index, upload in enumerate(uploads, start=1):
            ProductMedia.objects.create(
                product=product,
                file=upload,
                media_type=ProductMedia.detect_media_type(upload),
                alt_text=product.name,
                sort_order=next_sort_order + index,
                is_primary=not has_primary_media and index == 1,
            )

    def save_existing_media_state(self, product, data):
        media_items = list(product.media_assets.all())
        if not media_items:
            return

        delete_ids = set()
        for raw_media_id in data.getlist('delete_media'):
            try:
                delete_ids.add(int(raw_media_id))
            except (TypeError, ValueError):
                continue

        timestamp = timezone.now()
        sortable_media = []
        for media_item in media_items:
            if media_item.pk in delete_ids:
                continue
            try:
                requested_sort_order = int(data.get(f'media_sort_{media_item.pk}', media_item.sort_order) or media_item.sort_order)
            except (TypeError, ValueError):
                requested_sort_order = media_item.sort_order
            sortable_media.append((max(requested_sort_order, 0), media_item.sort_order, media_item.pk, media_item))

        for media_item in media_items:
            if media_item.pk not in delete_ids:
                continue
            media_item.file.delete(save=False)
            media_item.delete()

        if not sortable_media:
            return

        remaining_ids = {media_item.pk for _requested_order, _current_order, _pk, media_item in sortable_media}
        try:
            primary_media_id = int(data.get('primary_media_id') or 0)
        except (TypeError, ValueError):
            primary_media_id = 0
        if primary_media_id not in remaining_ids:
            primary_media_id = min(sortable_media, key=lambda item: (item[0], item[1], item[2]))[3].pk

        ProductMedia.objects.filter(product=product).update(is_primary=False, updated_at=timestamp)
        for normalized_order, (_requested_order, _current_order, _pk, media_item) in enumerate(
            sorted(sortable_media, key=lambda item: (item[0], item[1], item[2])),
            start=1,
        ):
            ProductMedia.objects.filter(pk=media_item.pk).update(
                sort_order=normalized_order,
                is_primary=media_item.pk == primary_media_id,
                updated_at=timestamp,
            )


class ProductOptionStaffForm(forms.ModelForm):
    option_values = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control staff-input',
                'placeholder': 'Small, Medium, Large',
            }
        ),
    )

    class Meta:
        model = ProductOption
        fields = ('name', 'sort_order')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'Option name'}),
            'sort_order': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['option_values'].initial = ', '.join(
                self.instance.option_values.order_by('sort_order', 'id').values_list('value', flat=True)
            )

    def has_changed(self):
        if self.is_bound and not self.instance.pk:
            meaningful_fields = ('name', 'option_values')
            has_option_data = any(
                (self.data.get(f'{self.prefix}-{field_name}') or '').strip()
                for field_name in meaningful_fields
            )
            if not has_option_data:
                return False
        return super().has_changed()

    def clean_option_values(self):
        raw_value = self.cleaned_data.get('option_values', '')
        parsed_values = parse_option_values(raw_value)
        self.cleaned_data['option_values_list'] = parsed_values
        return ', '.join(parsed_values)

    def clean(self):
        cleaned_data = super().clean()
        option_name = (cleaned_data.get('name') or '').strip()
        option_values = cleaned_data.get('option_values_list', [])
        if option_values and not option_name:
            self.add_error('name', 'Option name is required when option values are provided.')
        return cleaned_data

    def save_option_values(self):
        if not self.instance.pk:
            return
        requested_values = self.cleaned_data.get('option_values_list', [])
        existing_values = {value.value: value for value in self.instance.option_values.all()}

        for sort_order, value in enumerate(requested_values, start=1):
            option_value = existing_values.pop(value, None)
            if option_value:
                fields_to_update = []
                if option_value.sort_order != sort_order:
                    option_value.sort_order = sort_order
                    fields_to_update.append('sort_order')
                if fields_to_update:
                    option_value.save(update_fields=[*fields_to_update, 'updated_at'])
                continue

            ProductOptionValue.objects.create(option=self.instance, value=value, sort_order=sort_order)

        for leftover_value in existing_values.values():
            leftover_value.delete()


class BaseProductOptionStaffFormSet(BaseInlineFormSet):
    def save(self, commit=True):
        instances = super().save(commit=commit)
        if not commit:
            return instances

        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            form.save_option_values()
        return instances


ProductOptionStaffFormSet = inlineformset_factory(
    Product,
    ProductOption,
    form=ProductOptionStaffForm,
    formset=BaseProductOptionStaffFormSet,
    extra=1,
    can_delete=True,
)


class ProductVariantStaffForm(forms.ModelForm):
    is_active = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    inventory_breakdown = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control staff-input',
                'placeholder': 'Apia Store: 4; Warehouse: 2',
            }
        ),
    )

    class Meta:
        model = ProductVariant
        fields = ('sku', 'price', 'sale_price', 'stock_quantity', 'low_stock_threshold', 'is_active')
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'form-control staff-input', 'placeholder': 'SKU'}),
            'price': forms.NumberInput(attrs={'class': 'form-control staff-input', 'step': '0.01', 'min': '0'}),
            'sale_price': forms.NumberInput(attrs={'class': 'form-control staff-input', 'step': '0.01', 'min': '0', 'placeholder': 'Optional'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control staff-input', 'min': '0'}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control staff-input', 'min': '0'}),
        }

    def __init__(self, *args, option_definitions=None, **kwargs):
        self.option_definitions = option_definitions or []
        super().__init__(*args, **kwargs)
        self.option_field_map = []
        current_selected_values = {}
        if self.instance.pk:
            current_selected_values = {
                selection.option.name.casefold(): selection.option_value.value
                for selection in self.instance.selected_options.select_related('option', 'option_value')
            }

        legacy_initial_map = {
            'color': self.instance.color,
            'size': self.instance.size,
            'finish': self.instance.finish,
        }

        StoreLocation.ensure_default_location()
        self.location_map = {
            location.name.casefold(): location
            for location in StoreLocation.objects.filter(is_active=True).order_by('sort_order', 'name')
        }
        if self.instance.pk:
            self.fields['inventory_breakdown'].initial = '; '.join(
                f'{inventory_level.location.name}: {inventory_level.quantity}'
                for inventory_level in self.instance.inventory_levels.select_related('location').all()
            )

        for index, option_definition in enumerate(self.option_definitions, start=1):
            field_name = f'option_choice_{index}'
            option_name = option_definition['name']
            self.fields[field_name] = forms.ChoiceField(
                required=False,
                label=option_name,
                choices=[('', f'Select {option_name}')] + [(value, value) for value in option_definition['values']],
                widget=forms.Select(attrs={'class': 'form-select staff-select'}),
            )
            initial_value = current_selected_values.get(option_name.casefold())
            if initial_value is None:
                initial_value = legacy_initial_map.get(option_name.strip().lower(), '')
            self.initial[field_name] = initial_value
            self.option_field_map.append((field_name, option_name))

    @property
    def option_choice_fields(self):
        return [self[field_name] for field_name, _option_name in self.option_field_map]

    def has_meaningful_variant_data(self):
        if not self.is_bound:
            return self.instance.pk is not None

        meaningful_fields = ['sku', 'price', 'sale_price', 'inventory_breakdown', *[field_name for field_name, _option_name in self.option_field_map]]
        return any((self.data.get(f'{self.prefix}-{field_name}') or '').strip() for field_name in meaningful_fields)

    def clean_inventory_breakdown(self):
        raw_value = self.cleaned_data.get('inventory_breakdown', '')
        entries = parse_inventory_breakdown(raw_value)
        unknown_locations = [name for name, _quantity in entries if name.casefold() not in self.location_map]
        if unknown_locations:
            raise forms.ValidationError(f'Unknown location(s): {", ".join(unknown_locations)}.')
        self.cleaned_data['inventory_breakdown_entries'] = entries
        return '; '.join(f'{name}: {quantity}' for name, quantity in entries)

    def has_changed(self):
        if self.is_bound and not self.instance.pk:
            if not self.has_meaningful_variant_data():
                return False
        return super().has_changed()

    def clean(self):
        cleaned_data = super().clean()
        if not self.has_meaningful_variant_data():
            return cleaned_data

        for field_name, option_name in self.option_field_map:
            if cleaned_data.get(field_name):
                continue
            self.add_error(field_name, f'Select a value for {option_name}.')
        return cleaned_data

    def save_selected_options(self, product_options_by_name):
        if not self.instance.pk:
            return

        kept_option_ids = set()
        for sort_order, (field_name, option_name) in enumerate(self.option_field_map, start=1):
            selected_value = self.cleaned_data.get(field_name)
            product_option = product_options_by_name.get(option_name.casefold())
            if not product_option:
                continue

            if not selected_value:
                self.instance.selected_options.filter(option=product_option).delete()
                continue

            option_value = product_option.option_values.get(value=selected_value)
            selection, created = ProductVariantSelectedOption.objects.get_or_create(
                variant=self.instance,
                option=product_option,
                defaults={'option_value': option_value, 'sort_order': sort_order},
            )
            if not created and (selection.option_value_id != option_value.id or selection.sort_order != sort_order):
                selection.option_value = option_value
                selection.sort_order = sort_order
                selection.save(update_fields=['option_value', 'sort_order', 'updated_at'])
            kept_option_ids.add(product_option.id)

        if kept_option_ids:
            self.instance.selected_options.exclude(option_id__in=kept_option_ids).delete()
        else:
            self.instance.selected_options.all().delete()

    def save_inventory_levels(self, locations_by_name):
        if not self.instance.pk:
            return

        requested_entries = self.cleaned_data.get('inventory_breakdown_entries', [])
        if not requested_entries:
            self.instance.inventory_levels.all().delete()
            return

        existing_levels = {level.location_id: level for level in self.instance.inventory_levels.all()}
        kept_location_ids = set()
        total_quantity = 0

        for location_name, quantity in requested_entries:
            location = locations_by_name.get(location_name.casefold())
            if not location:
                continue

            total_quantity += quantity
            inventory_level = existing_levels.pop(location.id, None)
            if inventory_level is None:
                VariantInventoryLevel.objects.create(variant=self.instance, location=location, quantity=quantity)
            elif inventory_level.quantity != quantity:
                inventory_level.quantity = quantity
                inventory_level.save(update_fields=['quantity', 'updated_at'])
            kept_location_ids.add(location.id)

        if kept_location_ids:
            self.instance.inventory_levels.exclude(location_id__in=kept_location_ids).delete()

        if self.instance.stock_quantity != total_quantity:
            self.instance.stock_quantity = total_quantity
            self.instance.save(update_fields=['stock_quantity', 'updated_at'])


class BaseProductVariantStaffFormSet(BaseInlineFormSet):
    def __init__(self, *args, option_definitions=None, **kwargs):
        self.option_definitions = option_definitions or []
        super().__init__(*args, **kwargs)

    @property
    def option_labels(self):
        return [definition['name'] for definition in self.option_definitions]

    def _construct_form(self, i, **kwargs):
        kwargs['option_definitions'] = self.option_definitions
        return super()._construct_form(i, **kwargs)

    def save(self, commit=True):
        instances = super().save(commit=commit)
        if not commit or not self.instance.pk:
            return instances

        product_options = {
            option.name.casefold(): option
            for option in self.instance.options.prefetch_related('option_values').all()
        }
        locations_by_name = {
            location.name.casefold(): location
            for location in StoreLocation.objects.filter(is_active=True).order_by('sort_order', 'name')
        }

        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            form.save_selected_options(product_options)
            form.save_inventory_levels(locations_by_name)
        return instances


ProductVariantStaffFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantStaffForm,
    formset=BaseProductVariantStaffFormSet,
    extra=2,
    can_delete=True,
)
