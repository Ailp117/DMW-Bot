import unittest

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from models import Dungeon


class BooleanFilterSQLTests(unittest.TestCase):
    def test_active_filter_compiles_without_integer_comparison(self):
        stmt = select(Dungeon).where(Dungeon.is_active.is_(True))
        sql = str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("dungeons.is_active IS true", sql)
        self.assertNotIn("dungeons.is_active = 1", sql)


if __name__ == "__main__":
    unittest.main()
