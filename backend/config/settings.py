import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Read values from backend/.env (if the file exists). This must happen first,
# because the lines below read environment variables.
load_dotenv(BASE_DIR / '.env')

# Folder for the database file and uploaded pictures.
# Normally it is the backend folder; Docker sets DATA_DIR=/data (a persistent volume).
DATA_DIR = Path(os.getenv('DATA_DIR', BASE_DIR))


def env_list(name, default):
    # "a,b,c" in the .env file becomes ['a', 'b', 'c'] in python
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(',') if item.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-secret-key-change-me')

# DEBUG is False unless it is switched on (backend/.env has DEBUG=True for local work).
# So a live server can never run in debug mode by mistake.
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')

# Origins that are allowed to send POST requests (CSRF check). The website and the API
# share one address, so for local use this is just our own address.
CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:8000,http://127.0.0.1:8000',
)

# Only used to create the link in the password reset email
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://127.0.0.1:8000')

# Render tells the app its own public address in RENDER_EXTERNAL_HOSTNAME
# (for example messenger-abcd.onrender.com), so we allow it automatically.
RENDER_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_HOST}')
    if 'FRONTEND_URL' not in os.environ:
        FRONTEND_URL = f'https://{RENDER_HOST}'

# The web page (ui/index.html, app.js, style.css) is served by Django itself,
# so the website, the REST API and the WebSocket all share one address.
FRONTEND_DIST = Path(os.getenv('FRONTEND_DIST', BASE_DIR / 'ui'))


INSTALLED_APPS = [
    'daphne',  # must be first, so "runserver" can handle websockets too
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'channels',

    'accounts',
    'chats',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,  # the admin panel needs its templates
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Channel layer: this is how different websocket connections talk to each other.
# With Redis, messages travel through Redis, so it also works with many server processes.
# Without Redis we fall back to an in-memory layer (fine for one local process).
USE_REDIS = os.getenv('USE_REDIS', 'False').lower() == 'true'
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379')

if USE_REDIS:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }


# On Render a Postgres database gives us one DATABASE_URL like
# postgresql://user:password@host:5432/dbname . Without it we use a local SQLite file.
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    db_url = urlparse(DATABASE_URL)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': db_url.path.lstrip('/'),
            'USER': unquote(db_url.username or ''),
            'PASSWORD': unquote(db_url.password or ''),
            'HOST': db_url.hostname,
            'PORT': db_url.port or 5432,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': DATA_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    # my own rule: starts with a special character, 8-16 characters (accounts/validators.py)
    {'NAME': 'accounts.validators.PasswordPatternValidator'},
]

# New passwords are hashed with Argon2 (the first hasher in the list is used to create hashes).
# PBKDF2 stays in the list so passwords saved earlier can still be checked.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# The failed-login counter (accounts/login_limit.py) lives in this cache.
# LocMemCache is kept inside one server process, which is fine for one Daphne process.
# With several server processes use a shared cache (for example Redis) instead.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise serves app.js and style.css. The page itself (index.html) is sent by the
# view in config/views.py.
if FRONTEND_DIST.is_dir():
    WHITENOISE_ROOT = FRONTEND_DIST

# Uploaded profile pictures are stored here
MEDIA_URL = '/media/'
MEDIA_ROOT = DATA_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Emails are just printed in the terminal (no real email server needed)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@messenger.local'

# Login is cookie/session based, the browser sends the cookie automatically
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}


# ---------- production security (only when DEBUG is False) ----------
if not DEBUG:
    # Render (and most hosts) put a proxy in front of Django that handles https.
    # This header tells Django that the original request was https.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookies only travel over https when SECURE_COOKIES=True (set on Render, not for
# http://localhost, because browsers do not send secure cookies over plain http)
SECURE_COOKIES = os.getenv('SECURE_COOKIES', 'False').lower() == 'true'
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
