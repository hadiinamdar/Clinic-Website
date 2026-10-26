import unittest

from tests import _env  # noqa: F401
import security as sec


class TokenTests(unittest.TestCase):
    def test_roundtrip_and_expiry(self):
        t = sec.sign_token("k", 60, now=1000)
        self.assertTrue(sec.verify_token("k", t, now=1059))
        self.assertFalse(sec.verify_token("k", t, now=1061))

    def test_rejects_tampering_and_wrong_key(self):
        t = sec.sign_token("k", 60, now=1000)
        self.assertFalse(sec.verify_token("other", t, now=1001))
        payload, sig = t.split(".")
        forged = sec.sign_token("k", 99999, now=1000).split(".")[0]
        self.assertFalse(sec.verify_token("k", forged + "." + sig, now=1001))
        for bad in ("", None, "abc", "a.b.c", "x." + sig):
            self.assertFalse(sec.verify_token("k", bad, now=1001))

    def test_passwords(self):
        self.assertTrue(sec.passwords_match("abc", "abc"))
        self.assertFalse(sec.passwords_match("abc", "abd"))
        self.assertFalse(sec.passwords_match("", ""))  # unset password never matches


class RateLimiterTests(unittest.TestCase):
    def test_window_and_reset(self):
        r = sec.RateLimiter(10)
        self.assertEqual([r.hit("a", now=t) for t in (0, 1, 2)], [1, 2, 3])
        self.assertEqual(r.hit("b", now=2), 1)
        self.assertEqual(r.count("a", now=9), 3)
        self.assertEqual(r.count("a", now=11), 1)  # hits at 0 and 1 expired
        r.reset("a")
        self.assertEqual(r.count("a", now=11), 0)


if __name__ == "__main__":
    unittest.main()
