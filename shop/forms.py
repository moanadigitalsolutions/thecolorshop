from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Order


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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            user.customer_profile.phone_number = self.cleaned_data.get('phone_number', '')
            user.customer_profile.default_pickup_name = user.get_full_name()
            user.customer_profile.save(update_fields=['phone_number', 'default_pickup_name', 'updated_at'])
        return user


class CheckoutForm(forms.ModelForm):
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


class ProductFilterForm(forms.Form):
    q = forms.CharField(required=False, label='Search')
    category = forms.CharField(required=False)
