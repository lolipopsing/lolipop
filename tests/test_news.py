import unittest

from radar import news
from radar.main import load_companies

PAT = news.firm_patterns(load_companies())


def firms(t):
    return [f for f, _, _ in news.tag_firms(t, PAT)]


class NewsTest(unittest.TestCase):
    def test_firms(self):
        self.assertEqual(firms("John Vaske Joins Evercore as Senior Managing Director"), ["Evercore"])
        self.assertIn("J.P. Morgan", firms("Accenture Taps JPMorgan to Review $1.5 Billion Greater China Exit"))
        self.assertEqual(firms("Hamish Summerfield Joins Perella Weinberg as Partner"), ["Perella Weinberg Partners"])
        self.assertNotIn("Partners Group", firms("Morgan Stanley Capital Partners scoops up The Rapid Group"))
        self.assertEqual(firms("Robert Carlyle joins The Gentlemen Season 3"), [])
        self.assertEqual(firms("Injured Lincoln City defender signs new contract"), [])
        self.assertNotIn("Rothschild & Co", firms("Edmond de Rothschild hires banker"))

    def test_kind_and_stage(self):
        self.assertEqual(news.kind_of("Barclays taps Scott Glowinski to be managing director for its healthcare group", "firm"), "talent")
        self.assertEqual(news.kind_of("Macquarie hires Linso Pals from Blackstone to lead credit fundraising", "firm"), "talent")
        self.assertEqual(news.kind_of("Accenture Taps JPMorgan to Review $1.5 Billion Greater China Exit", "firm"), "deal")
        self.assertEqual(news.kind_of("Bank of England said to be reviewing Barclays' handling of private credit loans", "policy"), "policy")
        self.assertEqual(news.stage_of("Oaktree's Deal to Buy A-Cap Insurer Crumbles, Spawning New Talks"), "En process")
        self.assertEqual(news.stage_of("KKR to buy fund administrator Gen II in $5.1 billion deal"), "Signé / annoncé")
        self.assertEqual(news.stage_of("Korean Air finalise la fusion"), "Abouti")

    def test_junk(self):
        self.assertTrue(news.JUNK.search("Vanguard Group Inc. Acquires New Position in Lazard"))
        self.assertTrue(news.JUNK.search("Crédit immobilier : quels taux en octobre ?"))

    def test_same_story(self):
        def sig(t, f):
            return {"firms": f, "proper": news.proper(t, f), "tk": news.tokens(t)}
        a = sig("EQT To Acquire Cleanaway In A$9.3 Billion Deal", ["EQT"])
        b = sig("EQT agrees to buy Australia's Cleanaway Waste Management for $6.5 billion", ["EQT"])
        c = sig("John Song and Jean Stack Join Evercore as Senior Managing Directors", ["Evercore"])
        d = sig("John Vaske Joins Evercore as Senior Managing Director in the Chemicals Group", ["Evercore"])
        self.assertTrue(news.same_story(a, b))
        self.assertFalse(news.same_story(c, d))

    def test_rss(self):
        xml = ("<rss><channel><item><title>Lazard hires MD - Financial News</title><link>https://x/1</link>"
               "<pubDate>Mon, 19 Oct 2026 10:00:00 GMT</pubDate><source url='https://fn'>Financial News</source></item></channel></rss>")
        [it] = news.parse_rss(xml)
        self.assertEqual((it["title"], it["source"], it["published"][:10]), ("Lazard hires MD", "Financial News", "2026-10-19"))


if __name__ == "__main__":
    unittest.main()
