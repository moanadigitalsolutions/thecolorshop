from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        profile = getattr(user, 'customer_profile', None)
        is_verified = getattr(profile, 'is_email_verified', False)
        return f'{user.pk}{user.password}{user.email}{user.last_login}{timestamp}{is_verified}'


email_verification_token_generator = EmailVerificationTokenGenerator()