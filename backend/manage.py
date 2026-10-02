#!/usr/bin/env python
"""Django's command-line utility."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as error:
        raise ImportError(
            "Could not import Django. Is the virtual environment (.venv) activated?"
        ) from error
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
