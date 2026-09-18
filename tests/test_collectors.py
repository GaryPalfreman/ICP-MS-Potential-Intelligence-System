from icpms_intel import collectors


class FakeResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "notices": [
                {
                    "publication-number": "123456-2026",
                    "notice-title": {"eng": "Two inductively coupled plasma mass spectrometers"},
                    "description-lot": {"eng": "ICP-MS instruments for elemental analysis"},
                    "publication-date": "2026-09-18+02:00",
                    "deadline-receipt-tender-date-lot": ["2026-10-30+01:00"],
                    "organisation-name-buyer": ["Example Scientific Institute"],
                    "organisation-country-buyer": ["CHE"],
                    "classification-cpv": ["38433100"],
                    "notice-type": "cn-standard",
                },
                {
                    "publication-number": "654321-2026",
                    "notice-title": {"eng": "LC-MS system for proteomics"},
                    "description-lot": {"eng": "Liquid chromatography tandem mass spectrometer"},
                    "publication-date": "2026-09-18+02:00",
                },
                {
                    "publication-number": "123457-2026",
                    "notice-title": {"eng": "Two inductively coupled plasma mass spectrometers"},
                    "description-lot": {"eng": "Amended ICP-MS procurement notice"},
                    "publication-date": "2026-09-17+02:00",
                    "organisation-name-buyer": ["Example Scientific Institute"],
                },
            ]
        }


def test_ted_collector_keeps_icp_and_excludes_unrelated_mass_spec(monkeypatch):
    request = {}

    def fake_post(*args, **kwargs):
        request.update(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(collectors.requests, "post", fake_post)
    rows = collectors.collect_ted_procurement(days=30, limit=20)

    assert request["scope"] == "ACTIVE"
    assert "deadline-receipt-tender-date-lot>=" in request["query"]
    assert len(rows) == 1
    assert rows[0]["organization"] == "Example Scientific Institute"
    assert rows[0]["signal_kind"] == "Procurement"
    assert rows[0]["buying_intent"] == 0.98
    assert rows[0]["published_date"] == "2026-09-18"
    assert rows[0]["url"].endswith("123456-2026")
