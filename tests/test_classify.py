"""Regression tests for the A / B / None classifier. Run: python3 -m unittest"""
import unittest

from radar.classify import classify

A, B = "A", "B"
CASES = [
    # (title, firm category, expected level)
    ("March 2027 - M&A intern - Large Cap Generalist / Technology team - Paris", "Boutique M&A", A),
    ("Technology M&A Analyst - Paris - January or March 2027 (Internship)", "Boutique M&A", A),
    ("2027 - Investment Banking Off Cycle Internship – Milan Technology", "Banque BB", A),
    ("2028 Strategic Advisory: Mergers & Acquisitions Summer Analyst Program – Menlo Park / San Francisco Technology", "Banque BB", A),
    ("2027 Investment Banking Off-Cycle Internship - Real Estate Banking (Paris)", "Banque BB", A),
    ("Paris Investment Group internship | 6-months | Start in Mar. 2027", "Private Equity", A),
    ("2027 Spring Insights: Shape & Advance at JPMorganChase – Bournemouth", "Banque BB", A),
    ("2027 Investment Banking Technology Summer Analyst", "Banque BB", B),
    ("2027 Technology Summer Analyst Program - London", "Banque BB", B),
    ("2027 Spring Insights: Engineer & Innovate at JPMorganChase – London", "Banque BB", B),
    ("2027 Commercial & Investment Bank - Markets Program - Research - Summer Analyst - Tokyo", "Banque BB", B),
    ("2027 Summer Commercial Bank Internship - Denver (Credit)", "M&A Mid-Market", B),
    ("Summer 2027 Key Investment Services Internship (Certified Financial Planner Track) - Cleveland", "M&A Mid-Market", B),
    ("2026 Houlihan Lokey Investment Banking Insight Day", "M&A Mid-Market", B),  # past cycle
    ("Stage Software Engineer - Paris 2027", "Private Equity", B),
    ("Alternance M&A 2027", "Boutique M&A", None),
    ("Vice President, M&A", "Boutique M&A", None),
    ("Stagiaire Avocat - Corporate M&A - Neuilly (H/F)", "Autre", B),
    ("Stage - M&A Juridique (F/H) - 6 mois - Juillet 2027", "Autre", B),
    ("Stagiaire en M&A – Droit des sociétés (F/H) - S2 2027", "Autre", B),
    ("Private Equity - Analyst internship - Investor Relations M/F", "Private Equity", B),
    ("Stage Chargé d'études Middle-Office Private Equity", "Banque BB", B),
    ("2027 Off-Cycle Internship - Investment Bank Quants - London", "Banque BB", B),
    ("Private Equity - Analyst internship - Development M/F", "Private Equity", A),
    ("Investment Banking H2-2027 Off-Cycle Analyst - Paris", "Banque BB", A),
]

# Job boards: the posting is known to be an internship, the firm may be unknown (strict).
BOARD_CASES = [
    ("Analyste Private Equity / Equipe Territoires - mars 2027", A),
    ("INTERNSHIP - STRATEGY AND M&A - PARIS - S1 2027", A),
    ("Analyste LBO - Stage 6 mois", A),
    ("Consultant Stagiaire Transaction Services F/H", B),
    ("Stage - Analyste Junior Finance Inclusive", B),
    ("Assistant(e) Marketing Opérationnel - Stage", B),
]


class ClassifyTest(unittest.TestCase):
    def test_levels(self):
        for title, category, want in CASES:
            with self.subTest(title=title):
                self.assertEqual(classify(title, category)[0], want)

    def test_job_boards(self):
        for title, want in BOARD_CASES:
            with self.subTest(title=title):
                self.assertEqual(classify(title, "Autre", internship=True, strict=True)[0], want)


class SpringTrackerTest(unittest.TestCase):
    def test_anything_on_the_spring_tracker_is_a_spring(self):
        from radar.classify import spring_tracker_level
        for t in ["Black Talent in Business", "Women in Business", "Advancing Social Mobility", "2027 - Discover Nomura Programme"]:
            self.assertEqual(spring_tracker_level(t), "A", t)
        for t in ["Discovery Programme: Quantitative Trading", "FutureFocus: Quants 2027", "Spring into Technology",
                  "Summer 2027 Intern"]:
            self.assertEqual(spring_tracker_level(t), "B", t)
        self.assertEqual(spring_tracker_level("FOCUS / FTTP", ["Trading and Quant"]), "B")
        self.assertEqual(spring_tracker_level("Investing Simulator Challenge 2026", ["Promoted"]), "B")
        self.assertEqual(spring_tracker_level("Black Talent in Business", ["Big 4"]), "A")


class NormTitleTest(unittest.TestCase):
    def test_same_posting_on_two_boards(self):
        from radar.main import norm_title
        self.assertEqual(norm_title("STAGE - Analyste private equity France Investissement Régions F/H"),
                         norm_title("Analyste private equity France Investissement Régions F/H"))
        self.assertNotEqual(norm_title("M&A Internship - January 2027"), norm_title("M&A Internship - July 2027"))


if __name__ == "__main__":
    unittest.main()
