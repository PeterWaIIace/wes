from functools import wraps

def thread_safe(lock_name):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            with getattr(self, lock_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator