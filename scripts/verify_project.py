"""Run profile-platform tests offline, with optional rollback-only PostgreSQL integration tests.

No test database is created. No external HTTP requests are allowed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.core.checks import run_checks
from django.db import connection
from django.test.utils import setup_test_environment, teardown_test_environment


def snapshot():
    with connection.cursor() as cursor:
        result = {}
        for name in connection.introspection.table_names(cursor):
            cursor.execute('SELECT * FROM ' + connection.ops.quote_name(name))
            result[name] = hashlib.sha256(repr(sorted(cursor.fetchall(), key=repr)).encode()).digest()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres', action='store_true', help='Include transactional auth tests on the configured PostgreSQL database')
    args = parser.parse_args()
    names = ['core.tests', 'core.test_stabilization.AiContractTests']
    before = None
    if args.postgres:
        if connection.vendor != 'postgresql':
            parser.error('--postgres requires a PostgreSQL database')
        before = snapshot()
        names.append('core.test_stabilization.AuthenticationIntegrationTests')
        names.append('core.test_profile_platform')
    setup_test_environment()
    try:
        with patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP blocked during verification')):
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    finally:
        teardown_test_environment()
    unchanged = before is None or before == snapshot()
    if before is not None:
        print('Existing PostgreSQL table contents unchanged:', unchanged)
    checks = run_checks(databases=[])
    print('Django check issues:', len(checks))
    connection.close()
    return 0 if result.wasSuccessful() and unchanged and not checks else 1


if __name__ == '__main__':
    raise SystemExit(main())
