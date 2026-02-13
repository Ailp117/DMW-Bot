import unittest
from pathlib import Path


class AutoTemplateSyncSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raid_src = Path('commands_raid.py').read_text(encoding='utf-8')
        cls.view_src = Path('views_raid.py').read_text(encoding='utf-8')

    def test_raidplan_uses_auto_template_defaults(self):
        self.assertIn('AUTO_DUNGEON_TEMPLATE_NAME', self.raid_src)
        self.assertIn('if s.templates_enabled:', self.raid_src)
        self.assertIn('auto_tpl = await get_template_by_name', self.raid_src)

    def test_manual_template_parameter_removed(self):
        self.assertNotIn('template: str | None = None', self.raid_src)
        self.assertNotIn('@raidplan.autocomplete("template")', self.raid_src)

    def test_modal_submit_upserts_auto_template(self):
        self.assertIn('upsert_auto_dungeon_template', self.view_src)
        self.assertIn('if s.templates_enabled:', self.view_src)
        self.assertIn('select(Dungeon).where(Dungeon.name == self.dungeon_name)', self.view_src)


if __name__ == '__main__':
    unittest.main()
