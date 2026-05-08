"""
Hardcoded baseline of typical prices per route, in USD round-trip.

This is the "what's normal?" table the scorer compares against. Edit these
values as you learn the market — these are starting estimates based on
typical 2026 prices from Argentine sources.

Schema per route:
  historical_avg:        average round-trip in USD
  historical_min:        the floor seen in good years
  expected_low:          "good price" threshold (≈ p25)
  exceptional_threshold: "this is rare" threshold
  avg_duration_min:      typical total trip duration (used by quality scorer)
  region:                used for tab grouping in the frontend

The learning module will OVERRIDE these once a route has 15+ samples in history.
"""
from __future__ import annotations

HARDCODED_BASELINE: dict[str, dict] = {
    # ===== USA =====
    "EZE-MIA": {"historical_avg": 850, "historical_min": 580, "expected_low": 700,
                "exceptional_threshold": 600, "avg_duration_min": 660, "region": "USA"},
    "EZE-JFK": {"historical_avg": 950, "historical_min": 650, "expected_low": 780,
                "exceptional_threshold": 680, "avg_duration_min": 700, "region": "USA"},
    "EZE-MCO": {"historical_avg": 880, "historical_min": 600, "expected_low": 720,
                "exceptional_threshold": 620, "avg_duration_min": 720, "region": "USA"},
    "EZE-LAX": {"historical_avg": 1050, "historical_min": 750, "expected_low": 880,
                "exceptional_threshold": 780, "avg_duration_min": 900, "region": "USA"},
    "COR-MIA": {"historical_avg": 1050, "historical_min": 720, "expected_low": 880,
                "exceptional_threshold": 770, "avg_duration_min": 800, "region": "USA"},

    # ===== Europa =====
    "EZE-MAD": {"historical_avg": 950, "historical_min": 580, "expected_low": 780,
                "exceptional_threshold": 650, "avg_duration_min": 780, "region": "Europa"},
    "EZE-BCN": {"historical_avg": 1000, "historical_min": 620, "expected_low": 820,
                "exceptional_threshold": 680, "avg_duration_min": 820, "region": "Europa"},
    "EZE-FCO": {"historical_avg": 1100, "historical_min": 700, "expected_low": 880,
                "exceptional_threshold": 750, "avg_duration_min": 900, "region": "Europa"},
    "EZE-CDG": {"historical_avg": 1050, "historical_min": 680, "expected_low": 850,
                "exceptional_threshold": 720, "avg_duration_min": 870, "region": "Europa"},
    "EZE-LHR": {"historical_avg": 1080, "historical_min": 720, "expected_low": 880,
                "exceptional_threshold": 770, "avg_duration_min": 870, "region": "Europa"},
    "EZE-LIS": {"historical_avg": 1050, "historical_min": 700, "expected_low": 850,
                "exceptional_threshold": 730, "avg_duration_min": 850, "region": "Europa"},
    "EZE-OPO": {"historical_avg": 1100, "historical_min": 750, "expected_low": 880,
                "exceptional_threshold": 780, "avg_duration_min": 900, "region": "Europa"},
    "EZE-AMS": {"historical_avg": 1100, "historical_min": 750, "expected_low": 900,
                "exceptional_threshold": 800, "avg_duration_min": 880, "region": "Europa"},
    "EZE-MXP": {"historical_avg": 1100, "historical_min": 720, "expected_low": 900,
                "exceptional_threshold": 780, "avg_duration_min": 920, "region": "Europa"},
    "EZE-MUC": {"historical_avg": 1150, "historical_min": 780, "expected_low": 920,
                "exceptional_threshold": 820, "avg_duration_min": 900, "region": "Europa"},
    "EZE-FRA": {"historical_avg": 1130, "historical_min": 770, "expected_low": 900,
                "exceptional_threshold": 800, "avg_duration_min": 880, "region": "Europa"},
    "EZE-IST": {"historical_avg": 1200, "historical_min": 850, "expected_low": 980,
                "exceptional_threshold": 880, "avg_duration_min": 1020, "region": "Europa"},
    "COR-MAD": {"historical_avg": 1100, "historical_min": 750, "expected_low": 900,
                "exceptional_threshold": 800, "avg_duration_min": 900, "region": "Europa"},

    # ===== Caribe / México =====
    "EZE-CUN": {"historical_avg": 750, "historical_min": 450, "expected_low": 580,
                "exceptional_threshold": 500, "avg_duration_min": 720, "region": "Caribe"},
    "EZE-MEX": {"historical_avg": 720, "historical_min": 470, "expected_low": 580,
                "exceptional_threshold": 490, "avg_duration_min": 600, "region": "México"},
    "EZE-PUJ": {"historical_avg": 800, "historical_min": 520, "expected_low": 650,
                "exceptional_threshold": 560, "avg_duration_min": 720, "region": "Caribe"},
    "COR-PUJ": {"historical_avg": 850, "historical_min": 580, "expected_low": 700,
                "exceptional_threshold": 620, "avg_duration_min": 700, "region": "Caribe"},
    "ROS-PUJ": {"historical_avg": 850, "historical_min": 580, "expected_low": 700,
                "exceptional_threshold": 620, "avg_duration_min": 700, "region": "Caribe"},
    "EZE-AUA": {"historical_avg": 850, "historical_min": 580, "expected_low": 700,
                "exceptional_threshold": 620, "avg_duration_min": 750, "region": "Caribe"},
    "EZE-CUR": {"historical_avg": 800, "historical_min": 550, "expected_low": 680,
                "exceptional_threshold": 600, "avg_duration_min": 720, "region": "Caribe"},
    "EZE-ADZ": {"historical_avg": 800, "historical_min": 550, "expected_low": 680,
                "exceptional_threshold": 600, "avg_duration_min": 600, "region": "Caribe"},
    "EZE-HAV": {"historical_avg": 950, "historical_min": 650, "expected_low": 780,
                "exceptional_threshold": 700, "avg_duration_min": 720, "region": "Caribe"},
    "EZE-PTY": {"historical_avg": 700, "historical_min": 420, "expected_low": 550,
                "exceptional_threshold": 470, "avg_duration_min": 480, "region": "Caribe"},

    # ===== Brasil =====
    "EZE-GRU": {"historical_avg": 320, "historical_min": 180, "expected_low": 230,
                "exceptional_threshold": 190, "avg_duration_min": 180, "region": "Brasil"},
    "EZE-GIG": {"historical_avg": 380, "historical_min": 220, "expected_low": 280,
                "exceptional_threshold": 230, "avg_duration_min": 200, "region": "Brasil"},
    "EZE-FLN": {"historical_avg": 380, "historical_min": 220, "expected_low": 280,
                "exceptional_threshold": 240, "avg_duration_min": 200, "region": "Brasil"},
    "AEP-FLN": {"historical_avg": 380, "historical_min": 220, "expected_low": 280,
                "exceptional_threshold": 240, "avg_duration_min": 200, "region": "Brasil"},
    "EZE-BPS": {"historical_avg": 470, "historical_min": 280, "expected_low": 360,
                "exceptional_threshold": 310, "avg_duration_min": 240, "region": "Brasil"},
    "AEP-BPS": {"historical_avg": 470, "historical_min": 280, "expected_low": 360,
                "exceptional_threshold": 310, "avg_duration_min": 240, "region": "Brasil"},
    "EZE-SSA": {"historical_avg": 500, "historical_min": 280, "expected_low": 380,
                "exceptional_threshold": 320, "avg_duration_min": 360, "region": "Brasil"},
    "EZE-NAT": {"historical_avg": 600, "historical_min": 350, "expected_low": 470,
                "exceptional_threshold": 400, "avg_duration_min": 480, "region": "Brasil"},
    "EZE-REC": {"historical_avg": 580, "historical_min": 340, "expected_low": 450,
                "exceptional_threshold": 380, "avg_duration_min": 480, "region": "Brasil"},
    "EZE-FOR": {"historical_avg": 620, "historical_min": 380, "expected_low": 480,
                "exceptional_threshold": 410, "avg_duration_min": 480, "region": "Brasil"},
    "EZE-MCZ": {"historical_avg": 550, "historical_min": 320, "expected_low": 420,
                "exceptional_threshold": 360, "avg_duration_min": 420, "region": "Brasil"},
    "AEP-MCZ": {"historical_avg": 550, "historical_min": 320, "expected_low": 420,
                "exceptional_threshold": 360, "avg_duration_min": 420, "region": "Brasil"},

    # ===== Sudamérica =====
    "EZE-SCL": {"historical_avg": 280, "historical_min": 150, "expected_low": 200,
                "exceptional_threshold": 170, "avg_duration_min": 140, "region": "Sudamérica"},
    "EZE-LIM": {"historical_avg": 480, "historical_min": 290, "expected_low": 380,
                "exceptional_threshold": 310, "avg_duration_min": 290, "region": "Sudamérica"},
    "AEP-LIM": {"historical_avg": 480, "historical_min": 290, "expected_low": 380,
                "exceptional_threshold": 310, "avg_duration_min": 290, "region": "Sudamérica"},
    "EZE-BOG": {"historical_avg": 520, "historical_min": 320, "expected_low": 410,
                "exceptional_threshold": 350, "avg_duration_min": 360, "region": "Sudamérica"},
    "EZE-MDE": {"historical_avg": 580, "historical_min": 360, "expected_low": 470,
                "exceptional_threshold": 400, "avg_duration_min": 420, "region": "Sudamérica"},
    "EZE-CUZ": {"historical_avg": 620, "historical_min": 400, "expected_low": 510,
                "exceptional_threshold": 440, "avg_duration_min": 480, "region": "Sudamérica"},
    "EZE-ASU": {"historical_avg": 280, "historical_min": 160, "expected_low": 220,
                "exceptional_threshold": 180, "avg_duration_min": 120, "region": "Sudamérica"},
    "EZE-MVD": {"historical_avg": 200, "historical_min": 100, "expected_low": 150,
                "exceptional_threshold": 120, "avg_duration_min": 60, "region": "Sudamérica"},
    "EZE-PDP": {"historical_avg": 230, "historical_min": 130, "expected_low": 180,
                "exceptional_threshold": 150, "avg_duration_min": 80, "region": "Sudamérica"},
    "MDZ-SCL": {"historical_avg": 180, "historical_min": 90, "expected_low": 130,
                "exceptional_threshold": 110, "avg_duration_min": 50, "region": "Sudamérica"},

    # ===== Asia / Oceanía / África =====
    "EZE-TLV": {"historical_avg": 1500, "historical_min": 1100, "expected_low": 1280,
                "exceptional_threshold": 1180, "avg_duration_min": 1080, "region": "Asia"},
    "EZE-DXB": {"historical_avg": 1500, "historical_min": 1050, "expected_low": 1230,
                "exceptional_threshold": 1100, "avg_duration_min": 1080, "region": "Asia"},
    "EZE-HND": {"historical_avg": 1900, "historical_min": 1300, "expected_low": 1550,
                "exceptional_threshold": 1380, "avg_duration_min": 1620, "region": "Asia"},
    "EZE-BKK": {"historical_avg": 1700, "historical_min": 1200, "expected_low": 1400,
                "exceptional_threshold": 1280, "avg_duration_min": 1500, "region": "Asia"},
    "EZE-SYD": {"historical_avg": 2200, "historical_min": 1500, "expected_low": 1750,
                "exceptional_threshold": 1600, "avg_duration_min": 1800, "region": "Oceanía"},

    # ===== Doméstico (USD equivalente) =====
    "AEP-COR": {"historical_avg": 75, "historical_min": 40, "expected_low": 55,
                "exceptional_threshold": 47, "avg_duration_min": 75, "region": "Doméstico"},
    "AEP-MDZ": {"historical_avg": 85, "historical_min": 50, "expected_low": 65,
                "exceptional_threshold": 55, "avg_duration_min": 105, "region": "Doméstico"},
    "AEP-ROS": {"historical_avg": 65, "historical_min": 35, "expected_low": 50,
                "exceptional_threshold": 42, "avg_duration_min": 60, "region": "Doméstico"},
    "AEP-BRC": {"historical_avg": 130, "historical_min": 75, "expected_low": 100,
                "exceptional_threshold": 85, "avg_duration_min": 165, "region": "Doméstico"},
    "AEP-IGR": {"historical_avg": 110, "historical_min": 60, "expected_low": 85,
                "exceptional_threshold": 70, "avg_duration_min": 120, "region": "Doméstico"},
    "AEP-USH": {"historical_avg": 180, "historical_min": 110, "expected_low": 145,
                "exceptional_threshold": 125, "avg_duration_min": 220, "region": "Doméstico"},
    "AEP-FTE": {"historical_avg": 170, "historical_min": 95, "expected_low": 130,
                "exceptional_threshold": 110, "avg_duration_min": 200, "region": "Doméstico"},
    "AEP-SLA": {"historical_avg": 110, "historical_min": 60, "expected_low": 85,
                "exceptional_threshold": 70, "avg_duration_min": 130, "region": "Doméstico"},
    "AEP-NQN": {"historical_avg": 100, "historical_min": 55, "expected_low": 75,
                "exceptional_threshold": 65, "avg_duration_min": 130, "region": "Doméstico"},
    "AEP-MDQ": {"historical_avg": 60, "historical_min": 35, "expected_low": 45,
                "exceptional_threshold": 40, "avg_duration_min": 50, "region": "Doméstico"},
}
