#!/usr/bin/env python3
"""Which pages a PR's screenshots cover, and what happens when nothing maps."""
import contextlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import tempfile


@contextlib.contextmanager
def project_with(values):
    """A temp project whose .claude/settings.json sets `values`, entered as the working folder,
    with an empty home and no PROOFS_ variables, so only the file speaks."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, home = Path(tmp).resolve() / "proj", Path(tmp).resolve() / "home"
        (proj / ".claude").mkdir(parents=True)
        home.mkdir()
        (proj / ".claude" / "settings.json").write_text(json.dumps({"env": values}))
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PROOFS_")}
        keep.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
        old = os.getcwd()
        os.chdir(proj)
        try:
            with mock.patch.dict(os.environ, keep, clear=True):
                yield proj
        finally:
            os.chdir(old)

from pr_qa_plan import fill, is_visual, load_map, plan, read_map

PAGES = [
    {"name": "contact", "match": ["app/views/admin/contacts/show*"],
     "urls": [{"label": "Contact page", "path": "/admin/contacts/{contact_id}"},
              {"label": "Edit form", "path": "/admin/contacts/{contact_id}/edit"}]},
    {"name": "todos", "match": ["app/views/admin/todos/**"],
     "urls": [{"label": "To-dos", "path": "/admin/todos"}]},
]
IDS = {"contact_id": 14}


class IsVisualTest(unittest.TestCase):
    def test_app_code_is_visual(self):
        self.assertTrue(is_visual("app/views/admin/contacts/show.html.erb"))
        self.assertTrue(is_visual("app/javascript/controllers/clear_field_controller.js"))

    def test_routes_is_visual(self):
        self.assertTrue(is_visual("config/routes.rb"))

    def test_tests_and_docs_are_not(self):
        self.assertFalse(is_visual("test/controllers/admin/contacts_controller_test.rb"))
        self.assertFalse(is_visual("docs/FIELD_GUIDE.md"))
        self.assertFalse(is_visual("script/agent_run.py"))

    def test_a_map_can_supply_its_own_visual_prefixes(self):
        self.assertFalse(is_visual("docs/news/main.md"))
        self.assertTrue(is_visual("docs/news/main.md", ("docs/news/",)))


class FillTest(unittest.TestCase):
    def test_substitutes(self):
        self.assertEqual(fill("/admin/contacts/{contact_id}", IDS), "/admin/contacts/14")

    def test_a_missing_placeholder_yields_no_url_at_all(self):
        # Better nothing than /admin/contacts/{contact_id}, which 404s and would
        # be published as a before/after pair.
        self.assertIsNone(fill("/admin/contacts/{contact_id}", {}))

    def test_a_plain_path_needs_no_ids(self):
        self.assertEqual(fill("/admin/todos", {}), "/admin/todos")


class PlanTest(unittest.TestCase):
    def test_maps_a_view_change_to_its_pages(self):
        got = plan(["app/views/admin/contacts/show.html.erb"], IDS, PAGES)
        self.assertEqual([p["path"] for p in got["pages"]],
                         ["/admin/contacts/14", "/admin/contacts/14/edit"])
        self.assertEqual(got["matched"], ["contact"])

    def test_a_test_only_pr_has_nothing_to_photograph(self):
        got = plan(["test/controllers/admin/contacts_controller_test.rb"], IDS, PAGES)
        self.assertEqual(got["pages"], [])
        self.assertEqual(got["matched"], [])

    def test_an_unmapped_view_is_reported_not_swallowed(self):
        # The signal that the map needs a new entry. Silence here would mean a
        # PR quietly getting no screenshots and nobody knowing why.
        got = plan(["app/views/something/new.html.erb"], IDS, PAGES)
        self.assertEqual(got["pages"], [])
        self.assertEqual(got["unmatched_changes"], ["app/views/something/new.html.erb"])

    def test_does_not_repeat_a_page_two_entries_both_want(self):
        pages = PAGES + [{"name": "dup", "match": ["app/views/admin/contacts/show*"],
                          "urls": [{"label": "Again", "path": "/admin/contacts/{contact_id}"}]}]
        got = plan(["app/views/admin/contacts/show.html.erb"], IDS, pages)
        self.assertEqual([p["path"] for p in got["pages"]].count("/admin/contacts/14"), 1)

    def test_several_areas_at_once(self):
        got = plan(["app/views/admin/contacts/show.html.erb",
                    "app/views/admin/todos/_lists.html.erb"], IDS, PAGES)
        self.assertEqual(sorted(got["matched"]), ["contact", "todos"])
        self.assertIn("/admin/todos", [p["path"] for p in got["pages"]])

    def test_without_ids_the_page_is_dropped_but_the_match_is_still_reported(self):
        got = plan(["app/views/admin/contacts/show.html.erb"], {}, PAGES)
        self.assertEqual(got["pages"], [])
        self.assertEqual(got["matched"], ["contact"])

    def test_separates_non_visual_changes(self):
        got = plan(["app/views/admin/contacts/show.html.erb", "docs/x.md"], IDS, PAGES)
        self.assertEqual(got["non_visual_changes"], ["docs/x.md"])


class MapFileTest(unittest.TestCase):
    def test_a_missing_map_stops_with_a_plain_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                load_map(os.path.join(tmp, "nope.json"))
        self.assertIn("no page map", str(ctx.exception))

    def test_loads_pages_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "map.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"pages": PAGES, "visual_prefixes": ["docs/news/"]}, handle)
            self.assertEqual(load_map(path), PAGES)
            self.assertEqual(read_map(path)["visual_prefixes"], ["docs/news/"])


class SettingsTest(unittest.TestCase):
    def test_the_visual_paths_come_from_the_setting(self):
        with project_with({}):
            self.assertFalse(is_visual("web/page.tsx"))
        with project_with({"PROOFS_QA_PATHS": "web/,app/"}):
            self.assertTrue(is_visual("web/page.tsx"))
            self.assertTrue(is_visual("app/x.rb"))
            self.assertFalse(is_visual("src/x.js"))

    def test_a_map_visual_prefixes_list_still_wins(self):
        with project_with({"PROOFS_QA_PATHS": "web/"}):
            got = plan(["web/a.tsx", "docs/x.md"], {}, [], ["docs/"])
        self.assertEqual(got["non_visual_changes"], ["web/a.tsx"])

    def test_the_default_map_name_comes_from_the_setting(self):
        from pr_qa_plan import default_map
        with project_with({}):
            self.assertEqual(default_map(), "pr_qa_pages.json")
        with project_with({"PROOFS_QA_MAP": "qa/map.json"}):
            self.assertEqual(default_map(), "qa/map.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
