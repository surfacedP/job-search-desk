import unittest
from urllib.parse import parse_qs, urlparse

from app import SearchController
from scrape import search_url


class SearchModeTests(unittest.TestCase):
    def test_easy_search_adds_linkedin_facet(self):
        query = parse_qs(urlparse(search_url("desktop support", "London", 0, True)).query)
        self.assertEqual(query["f_AL"], ["true"])

    def test_external_search_does_not_add_easy_apply_facet(self):
        query = parse_qs(urlparse(search_url("desktop support", "London", 0, False)).query)
        self.assertNotIn("f_AL", query)

    def test_controller_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            SearchController().start("everything")

    def test_controller_prevents_concurrent_searches(self):
        controller = SearchController()
        with controller.lock:
            controller.state["running"] = True
        self.assertFalse(controller.start("easy"))


if __name__ == "__main__":
    unittest.main()

