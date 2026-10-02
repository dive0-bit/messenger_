import re

from django.core.exceptions import ValidationError

# The same rules I used in my Email Automation System project.

# Gmail: letters first, then digits, then @gmail.com  (example: abc123@gmail.com)
GMAIL_PATTERN = re.compile(r'^[a-zA-Z]+[0-9]+@gmail\.com$')
GMAIL_MESSAGE = 'Enter a valid Gmail address (letters followed by digits, e.g. abc123@gmail.com).'

# Password: starts with a special character, then letters / digits / special characters,
# 8 to 16 characters in total  (example: @dev12345#dee2)
PASSWORD_PATTERN = re.compile(r'^[@#$%&*!][A-Za-z0-9@#$%&*!]{7,15}$')
PASSWORD_MESSAGE = (
    'Password must start with a special character (@ # $ % & * !), use only letters, '
    'digits and those special characters, and be 8-16 characters long.'
)


def validate_gmail(value):
    if not GMAIL_PATTERN.fullmatch(value):
        raise ValidationError(GMAIL_MESSAGE)


class PasswordPatternValidator:
    """
    Django calls validate() through validate_password() (see AUTH_PASSWORD_VALIDATORS
    in settings.py), so this rule is used everywhere a password is set:
    registration and password reset.
    """

    def validate(self, password, user=None):
        if not PASSWORD_PATTERN.fullmatch(password):
            raise ValidationError(PASSWORD_MESSAGE, code='password_pattern')

    def get_help_text(self):
        return PASSWORD_MESSAGE
