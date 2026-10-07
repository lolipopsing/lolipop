"""Event filters. Run: python3 -m unittest discover -s tests -t ."""
import unittest

from radar import events


def ev(title, city="", source="Eventbrite", online=False, country="FR", free=True, summary=""):
    return {"id": title, "title": title, "city": city, "source": source, "online": online, "country": country,
            "free": free, "summary": summary, "kind": "", "org": ""}


class EventFilterTest(unittest.TestCase):
    def test_paris_needs_finance(self):
        self.assertTrue(events.relevant(ev("Petit déjeuner - L'essor de la dette privée", "Paris")))
        self.assertFalse(events.relevant(ev("Atelier budget | Dilemme Entrepreneurs", "Paris")))
        self.assertFalse(events.relevant(ev("Business lunch invitées", "Paris")))

    def test_riviera_business_networking_counts(self):
        self.assertTrue(events.relevant(ev("CANNES Ocean View Business Lunch", "Cannes")))
        self.assertTrue(events.relevant(ev("Business networking afterwork - Riviera Entrepreneurs", "Valbonne")))
        self.assertTrue(events.relevant(ev("AI in private banking: Operational reality", "Monaco", country="Monaco")))
        self.assertFalse(events.relevant(ev("Restaurant of the Week | Foodies + New Friends: Cannes", "Cannes")))
        self.assertFalse(events.relevant(ev("FORMATION : Paie Monégasque", "Monaco", country="Monaco")))
        self.assertFalse(events.relevant(ev("📚 Book Club CHAPTER 2", "Grasse")))
        self.assertFalse(events.relevant(ev("JOURNEE PORTE OUVERTE ! Toastmasters Sophia Antipolis", "Sophia Antipolis")))
        self.assertTrue(events.relevant(ev("Afterwork du Cercle Côte d'Azur", "Nice")))

    def test_riviera_ranks_first_and_monaco_is_reachable(self):
        firms = set()
        local = dict(ev("CANNES Ocean View Business Lunch", "Cannes"))
        paris = dict(ev("Business networking finance", "Paris"))
        self.assertGreater(events.score(local, firms), events.score(paris, firms))
        mc = ev("Monaco investors cocktail", "Monaco", country="Monaco")
        self.assertTrue(events.reachable(mc))
        mc["score"] = events.score(mc, firms)
        self.assertTrue(events.worth_notifying(mc))

    def test_paris_time(self):
        self.assertEqual(events._paris("2026-10-14T16:30:00.000Z"), ("2026-10-14", "18:30"))


if __name__ == "__main__":
    unittest.main()
