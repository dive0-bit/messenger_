import tempfile

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Profiles

# follows my password rule: starts with a special character, 8-16 characters
PASSWORD = '@Strong#Pass9'


class AuthApiTests(TestCase):
    def setUp(self):
        cache.clear()  # the failed-login counter lives in the cache

    def login(self, username, password):
        return self.client.post(
            '/api/auth/login/',
            {'username': username, 'password': password},
            content_type='application/json',
        )

    def register(self, **changes):
        data = {
            'username': 'new-user',
            'email': 'newuser1@gmail.com',
            'password': PASSWORD,
            'confirm_password': PASSWORD,
            'unique_id': 'new_user_1',
        }
        data.update(changes)
        return self.client.post('/api/auth/register/', data, content_type='application/json')

    def test_register_creates_user_and_profile(self):
        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['user']['unique_id'], 'new_user_1')
        self.assertTrue(User.objects.filter(username='new-user').exists())

    def test_register_rejects_different_passwords(self):
        response = self.register(confirm_password='something-else-123')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='new-user').exists())

    def test_register_rejects_duplicate_unique_id(self):
        self.register()
        response = self.register(username='other-user', unique_id='new_user_1')

        self.assertEqual(response.status_code, 400)

    def test_login_with_username_and_with_email(self):
        self.register()

        by_username = self.client.post(
            '/api/auth/login/',
            {'username': 'new-user', 'password': PASSWORD},
            content_type='application/json',
        )
        self.assertEqual(by_username.status_code, 200)

        by_email = self.client.post(
            '/api/auth/login/',
            {'username': 'newuser1@gmail.com', 'password': PASSWORD},
            content_type='application/json',
        )
        self.assertEqual(by_email.status_code, 200)

    def test_login_with_wrong_password_fails(self):
        self.register()
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'new-user', 'password': 'wrong-password'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_me_and_logout(self):
        self.register()
        self.client.post(
            '/api/auth/login/',
            {'username': 'new-user', 'password': PASSWORD},
            content_type='application/json',
        )
        self.assertEqual(self.client.get('/api/auth/me/').json()['user']['username'], 'new-user')

        self.client.post('/api/auth/logout/', content_type='application/json')
        self.assertIsNone(self.client.get('/api/auth/me/').json()['user'])

    def test_profile_update_saves_bio_and_picture(self):
        user = User.objects.create_user('picture-user', password=PASSWORD)
        Profiles.objects.create(user=user)
        self.client.login(username='picture-user', password=PASSWORD)

        with tempfile.TemporaryDirectory() as media_folder:
            with override_settings(MEDIA_ROOT=media_folder):
                image = SimpleUploadedFile('avatar.png', b'\x89PNG\r\n\x1a\n', content_type='image/png')
                response = self.client.post('/api/auth/profile/', {
                    'bio': 'Available for a chat',
                    'profile_picture': image,
                })

        self.assertEqual(response.status_code, 200)
        profile = Profiles.objects.get(user=user)
        self.assertEqual(profile.bio, 'Available for a chat')
        self.assertTrue(profile.profile_picture.name.startswith('profile_pictures/avatar'))

    def test_profile_update_needs_login(self):
        response = self.client.post('/api/auth/profile/', {'bio': 'hello'})

        self.assertEqual(response.status_code, 403)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_flow(self):
        User.objects.create_user('reset-user', email='reset@example.com', password='@OldPass#123')

        response = self.client.post(
            '/api/auth/password-reset/',
            {'email': 'reset@example.com'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        # the link is on its own line in the email: .../reset-password/<uid>/<token>
        link = mail.outbox[0].body.split('/reset-password/')[1].split()[0]
        uid, token = link.split('/')

        confirm = self.client.post(
            '/api/auth/password-reset-confirm/',
            {'uid': uid, 'token': token, 'new_password': '#NewPass@456'},
            content_type='application/json',
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertTrue(self.client.login(username='reset-user', password='#NewPass@456'))

    def test_password_reset_with_bad_token_fails(self):
        response = self.client.post(
            '/api/auth/password-reset-confirm/',
            {'uid': 'abc', 'token': 'bad-token', 'new_password': '#NewPass@456'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_register_rejects_email_that_is_not_my_gmail_pattern(self):
        for bad_email in ['john.doe@gmail.com', 'abc@gmail.com', 'abc123@yahoo.com']:
            response = self.register(email=bad_email)
            self.assertEqual(response.status_code, 400, bad_email)

        self.assertFalse(User.objects.filter(username='new-user').exists())

    def test_register_rejects_password_that_breaks_the_pattern(self):
        for bad_password in ['StrongPass9#', '@short1', '@this-has-a-dash1', '@12345678901234567']:
            response = self.register(password=bad_password, confirm_password=bad_password)
            self.assertEqual(response.status_code, 400, bad_password)

        self.assertFalse(User.objects.filter(username='new-user').exists())

    def test_register_rejects_email_that_is_already_used(self):
        self.register()
        response = self.register(username='other-user', unique_id='other_id_1', email='NEWUSER1@gmail.com')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_email_is_saved_in_lowercase(self):
        self.register(email='NewUser1@Gmail.com')

        self.assertEqual(User.objects.get(username='new-user').email, 'newuser1@gmail.com')

    def test_password_is_saved_with_argon2(self):
        self.register()

        self.assertTrue(User.objects.get(username='new-user').password.startswith('argon2'))

    def test_account_is_locked_after_5_wrong_passwords(self):
        self.register()

        for _ in range(4):
            self.assertEqual(self.login('new-user', 'wrong-password').status_code, 400)
        self.assertEqual(self.login('new-user', 'wrong-password').status_code, 429)

        # even the correct password is refused while the account is locked
        self.assertEqual(self.login('new-user', PASSWORD).status_code, 429)
        # and it does not matter if the email is used instead of the username
        self.assertEqual(self.login('newuser1@gmail.com', PASSWORD).status_code, 429)

    def test_correct_password_resets_the_failed_attempt_counter(self):
        self.register()

        for _ in range(4):
            self.login('new-user', 'wrong-password')
        self.assertEqual(self.login('new-user', PASSWORD).status_code, 200)

        # the counter started again, so 4 more wrong passwords are still allowed
        for _ in range(4):
            self.assertEqual(self.login('new-user', 'wrong-password').status_code, 400)

    def test_password_reset_unlocks_a_locked_account(self):
        self.register()
        for _ in range(5):
            self.login('new-user', 'wrong-password')
        self.assertEqual(self.login('new-user', PASSWORD).status_code, 429)

        user = User.objects.get(username='new-user')
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        response = self.client.post(
            '/api/auth/password-reset-confirm/',
            {
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
                'new_password': '#NewPass@456',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.login('new-user', '#NewPass@456').status_code, 200)

    def test_password_reset_rejects_password_that_breaks_the_pattern(self):
        self.register()
        user = User.objects.get(username='new-user')
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        response = self.client.post(
            '/api/auth/password-reset-confirm/',
            {
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
                'new_password': 'NoSpecialStart9',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_register_rejects_username_with_at_sign(self):
        response = self.register(username='someone@gmail.com')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='someone@gmail.com').exists())

    def test_profile_update_changes_name_and_bio(self):
        self.register()
        self.login('new-user', PASSWORD)

        response = self.client.post('/api/auth/profile/', {'username': 'changed-name', 'bio': 'Hello there'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['username'], 'changed-name')
        self.assertEqual(response.json()['user']['bio'], 'Hello there')
        # the new name works for login, the old one does not exist any more
        self.client.post('/api/auth/logout/', content_type='application/json')
        self.assertEqual(self.login('changed-name', PASSWORD).status_code, 200)

    def test_profile_update_rejects_a_name_that_is_taken(self):
        self.register()
        self.register(username='other-user', email='otheruser2@gmail.com', unique_id='other_id_2')
        self.login('new-user', PASSWORD)

        response = self.client.post('/api/auth/profile/', {'username': 'OTHER-user'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.filter(username='new-user').count(), 1)

    def test_profile_update_rejects_name_with_at_sign(self):
        self.register()
        self.login('new-user', PASSWORD)

        response = self.client.post('/api/auth/profile/', {'username': 'a@b.com'})

        self.assertEqual(response.status_code, 400)

    def test_profile_update_saves_nothing_when_the_picture_is_wrong(self):
        self.register()
        self.login('new-user', PASSWORD)
        not_an_image = SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')

        response = self.client.post(
            '/api/auth/profile/',
            {'username': 'changed-name', 'bio': 'New bio', 'profile_picture': not_an_image},
        )

        self.assertEqual(response.status_code, 400)
        user = User.objects.get(email='newuser1@gmail.com')
        self.assertEqual(user.username, 'new-user')
        self.assertEqual(Profiles.objects.get(user=user).bio, '')
