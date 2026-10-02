from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import login_limit
from .models import Profiles
from .validators import validate_gmail

MAX_PICTURE_SIZE = 2 * 1024 * 1024  # 2 MB


def bad_request(message):
    return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)


def too_many_attempts():
    minutes = login_limit.LOCK_SECONDS // 60
    return Response(
        {'detail': f'Too many wrong attempts. Account locked, try again after {minutes} minutes or reset your password.'},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def check_username(username, current_user=None):
    # returns an error text, or an empty string when the username is fine
    if not username:
        return 'Username is required.'
    if len(username) > 150:
        return 'Username can have at most 150 characters.'

    # login accepts "username or email". A username with @ could look like somebody
    # else's email and would be found first, so it is not allowed.
    if '@' in username:
        return 'Username can not contain the @ character.'

    others = User.objects.filter(username__iexact=username)
    if current_user is not None:
        others = others.exclude(pk=current_user.pk)  # keeping your own name is fine
    if others.exists():
        return 'Username already exists.'
    return ''


def get_profile(user):
    # older users might not have a profile yet, so create it when missing
    profile, _ = Profiles.objects.get_or_create(user=user)
    return profile


def user_data(user):
    # the small dictionary the client needs to know about the logged in user
    profile = get_profile(user)
    if profile.profile_picture:
        picture = profile.profile_picture.url
    else:
        picture = ''

    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'bio': profile.bio,
        'unique_id': profile.unique_id,
        'profile_picture': picture,
    }


# ensure_csrf_cookie makes Django send the "csrftoken" cookie,
# the client reads it and sends it back in the X-CSRFToken header for POST/DELETE calls
@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def current_user(request):
    # the client calls this when the page loads to find out if someone is logged in
    if request.user.is_authenticated:
        return Response({'user': user_data(request.user)})
    return Response({'user': None})


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    username = str(request.data.get('username', '')).strip()
    email = str(request.data.get('email', '')).strip().lower()
    password = str(request.data.get('password', ''))
    confirm_password = str(request.data.get('confirm_password', ''))
    unique_id = str(request.data.get('unique_id', '')).strip()

    if not username or not email or not password:
        return bad_request('Username, email and password are required.')

    if password != confirm_password:
        return bad_request('Passwords do not match.')

    try:
        validate_gmail(email)
    except ValidationError as error:
        return bad_request(' '.join(error.messages))

    problem = check_username(username)
    if problem:
        return bad_request(problem)

    # login and password reset both use the email, so it must belong to one account only
    if User.objects.filter(email__iexact=email).exists():
        return bad_request('An account with this email already exists.')

    if unique_id:
        if len(unique_id) > 15:
            return bad_request('Unique ID can have at most 15 characters.')
        if Profiles.objects.filter(unique_id=unique_id).exists():
            return bad_request('Unique ID already exists. Please choose another one.')

    try:
        validate_password(password)
    except ValidationError as error:
        return bad_request(' '.join(error.messages))

    user = User.objects.create_user(username=username, email=email, password=password)

    profile = get_profile(user)
    if unique_id:
        profile.unique_id = unique_id
        profile.save()

    return Response({'user': user_data(user)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    # the "username" field can contain either the username or the email
    identifier = str(request.data.get('username', '')).strip()
    password = str(request.data.get('password', ''))

    # find the account first, so "abc" and "abc@gmail.com" count as the same person
    account = (
        User.objects.filter(username__iexact=identifier).first()
        or User.objects.filter(email__iexact=identifier).first()
    )

    # Unknown names are counted too. Otherwise "locked" vs "wrong password"
    # would tell an attacker which accounts exist.
    lock_id = f'user-{account.pk}' if account else f'name-{identifier.lower()}'

    if login_limit.is_locked(lock_id):
        return too_many_attempts()

    user = None
    if account:
        user = authenticate(request, username=account.username, password=password)

    if user is None:
        attempts_left = login_limit.add_failure(lock_id)
        if attempts_left == 0:
            return too_many_attempts()
        return bad_request(f'Invalid username or password. {attempts_left} attempts left.')

    login_limit.clear(lock_id)
    login(request, user)  # this creates the session cookie
    return Response({'user': user_data(user)})


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_user(request):
    logout(request)
    return Response({'detail': 'Logged out.'})


@api_view(['POST'])
def update_profile(request):
    user = request.user
    profile = get_profile(user)

    # 1) check everything first, so a wrong picture does not leave a half-saved profile
    new_username = None
    if 'username' in request.data:
        new_username = str(request.data.get('username', '')).strip()
        problem = check_username(new_username, current_user=user)
        if problem:
            return bad_request(problem)

    picture = request.FILES.get('profile_picture')
    if picture:
        if not picture.content_type.startswith('image/'):
            return bad_request('Please upload an image file.')
        if picture.size > MAX_PICTURE_SIZE:
            return bad_request('Image is too big. Maximum size is 2 MB.')

    # 2) all checks passed, now save
    if new_username is not None and new_username != user.username:
        user.username = new_username
        user.save()

    if 'bio' in request.data:
        profile.bio = str(request.data.get('bio', '')).strip()[:500]
    if picture:
        profile.profile_picture = picture
    profile.save()

    return Response({'user': user_data(user)})


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    email = str(request.data.get('email', '')).strip()
    user = User.objects.filter(email__iexact=email, is_active=True).first()

    # same answer whether the email exists or not, so nobody can check who is registered
    response_data = {
        'detail': 'If an account exists with that email, a reset link has been generated.'
    }

    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}"

        send_mail(
            subject='Reset your Messenger password',
            message=(
                f"Hi {user.username},\n\n"
                "Open the link below to choose a new password:\n"
                f"{reset_link}\n\n"
                "If you did not ask for this, you can ignore this email.\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )

        # There is no real email server while developing (the email is printed in the
        # terminal), so in DEBUG mode we also return the link to show it on the page.
        if settings.DEBUG:
            response_data['reset_link'] = reset_link

    return Response(response_data)


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    uid = str(request.data.get('uid', ''))
    token = str(request.data.get('token', ''))
    new_password = str(request.data.get('new_password', ''))

    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        return bad_request('This reset link is invalid or has expired.')

    if not default_token_generator.check_token(user, token):
        return bad_request('This reset link is invalid or has expired.')

    try:
        validate_password(new_password, user)
    except ValidationError as error:
        return bad_request(' '.join(error.messages))

    user.set_password(new_password)
    user.save()

    # a locked person can get back in by resetting the password
    login_limit.clear(f'user-{user.pk}')
    return Response({'detail': 'Password changed. You can log in now.'})
