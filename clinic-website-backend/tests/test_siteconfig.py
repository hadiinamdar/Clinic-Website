import json
import unittest

from tests import _env  # noqa: F401
import siteconfig as sc

PAGE = (
    '<title>Dr. [Doctor Name] | Clinic</title>'
    '<script type="application/ld+json">{"name":"Dr. [Doctor Name]"}</script>'
    '<p>is a [specialty] with [XX] years</p><b>[XX]+</b>'
    '<p class="note" data-dev-note>Replace me</p><p class="note">Real note</p>'
    "<a href=\"#reviews\">Reviews</a>"
    '<section id="reviews" class="alt"><p>sample</p></section>'
    "<script>const T={doc:'Dr. [Doctor Name], [qualifications]',hi:'डॉ. [नाम], [योग्यता]'};</script>"
)


class ApplyTests(unittest.TestCase):
    def test_empty_config_changes_nothing(self):
        self.assertEqual(sc.apply_config(PAGE, {"show_sample_reviews": True}), PAGE)

    def test_fills_each_context_safely(self):
        cfg = {"doctor_name": "Dr. O'Brien <b>\"X\"</b>", "specialty": "Internist", "years_experience": "12",
               "qualifications": "MBBS, MD", "show_sample_reviews": True}
        out = sc.apply_config(PAGE, cfg)
        self.assertIn("<title>Dr. O&#x27;Brien &lt;b&gt;&quot;X&quot;&lt;/b&gt; | Clinic</title>", out)
        self.assertIn("is an Internist with 12 years", out)
        self.assertIn("<b>12+</b>", out)
        ld = out.split('<script type="application/ld+json">')[1].split("</script>")[0]
        self.assertEqual(json.loads(ld)["name"], "Dr. O'Brien <b>\"X\"</b>")  # valid JSON, no raw '<'
        self.assertNotIn("<b>", ld)
        js = out.split("<script>")[1]
        self.assertIn("Dr. O\\'Brien \\x3cb\\x3e", js)   # apostrophe escaped: JS string intact
        self.assertIn("MBBS, MD", js)
        self.assertIn("डॉ. [नाम]".replace("डॉ. [नाम]", "Dr. O\\'Brien"), js)

    def test_article_a(self):
        self.assertIn("is a Physician with", sc.apply_config(PAGE, {"specialty": "Physician"}))

    def test_hide_notes_and_reviews(self):
        out = sc.apply_config(PAGE, {"hide_placeholder_notes": True, "show_sample_reviews": False})
        self.assertNotIn("Replace me", out)
        self.assertIn("Real note", out)
        self.assertNotIn('id="reviews"', out)
        self.assertNotIn('href="#reviews"', out)

    def test_unfilled_keys(self):
        out = sc.apply_config(PAGE, {"doctor_name": "Dr. A"})
        self.assertEqual(sc.unfilled_keys(out), ["qualifications", "specialty", "years_experience"])


if __name__ == "__main__":
    unittest.main()
