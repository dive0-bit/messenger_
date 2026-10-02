from django.core.cache import cache

# Same idea as my Email Automation System: 5 wrong passwords and the account is locked.
# Here the lock is stored on the server (in the cache), so refreshing the page or opening
# a new browser does not reset it.
MAX_ATTEMPTS = 5
LOCK_SECONDS = 15 * 60  # the lock ends 15 minutes after the first wrong attempt


def _key(lock_id):
    return f'login_failed:{lock_id}'


def is_locked(lock_id):
    return cache.get(_key(lock_id), 0) >= MAX_ATTEMPTS


def add_failure(lock_id):
    # returns how many attempts are still left
    key = _key(lock_id)
    try:
        count = cache.incr(key)
    except ValueError:
        # the key does not exist yet, so this is the first wrong attempt
        cache.set(key, 1, LOCK_SECONDS)
        count = 1
    return max(MAX_ATTEMPTS - count, 0)


def clear(lock_id):
    cache.delete(_key(lock_id))
