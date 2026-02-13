import unittest
from pathlib import Path


class AdminPermissionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.permissions_src = Path('permissions.py').read_text(encoding='utf-8')
        cls.main_src = Path('main.py').read_text(encoding='utf-8')
        cls.admin_src = Path('commands_admin.py').read_text(encoding='utf-8')
        cls.purge_src = Path('commands_purge.py').read_text(encoding='utf-8')

    def test_privileged_user_id_is_configured(self):
        self.assertIn('PRIVILEGED_USER_ID = 403988960638009347', self.permissions_src)

    def test_admin_commands_use_admin_or_privileged_check(self):
        for src in (self.main_src, self.admin_src, self.purge_src):
            self.assertIn('@admin_or_privileged_check()', src)


if __name__ == '__main__':
    unittest.main()
