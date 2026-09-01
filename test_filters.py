import unittest

from job_filters import Job, matches
from urllib.parse import parse_qs, urlparse


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.job = Job("1", "Backend Software Engineer", "Example Ltd", "London, UK", "https://example.test")

    def test_title_include_and_exclude(self):
        self.assertTrue(matches(self.job, {"include_titles": ["software engineer"]}))
        self.assertFalse(matches(self.job, {"exclude_titles": ["backend"]}))

    def test_location_and_company(self):
        self.assertTrue(matches(self.job, {"include_locations": ["London"], "include_companies": ["example"]}))
        self.assertFalse(matches(self.job, {"exclude_companies": ["Example Ltd"]}))

    def test_description_keywords(self):
        detailed = Job(**{**self.job.__dict__, "description": "Python, PostgreSQL, and AWS"})
        self.assertTrue(matches(detailed, {"description_keywords_any": ["Go", "Python"]}))
        self.assertTrue(matches(detailed, {"description_keywords_all": ["Python", "AWS"]}))
        self.assertFalse(matches(detailed, {"description_keywords_all": ["Python", "Azure"]}))

    def test_search_url_enables_easy_apply(self):
        # Assert the encoding contract used by LinkedIn's Easy Apply facet.
        from urllib.parse import urlencode
        url = "https://www.linkedin.com/jobs/search/?" + urlencode({"f_AL": "true", "start": 25})
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["f_AL"], ["true"])
        self.assertEqual(query["start"], ["25"])


if __name__ == "__main__":
    unittest.main()
