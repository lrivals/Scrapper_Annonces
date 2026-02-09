# tests/test_exporter.py
# =========================
# Tests unitaires pour l'export CSV/JSON
# =========================

import csv
import json
from pathlib import Path

from reporting.exporter import export_csv, export_json, EXPORT_FIELDS


SAMPLE_ANNONCES = [
    {
        "id": 1,
        "site": "SeLoger",
        "title": "Studio Rangueil",
        "price": 430,
        "location_raw": "Toulouse 31400",
        "distance_enac_km": 2.5,
        "url": "https://www.seloger.com/annonce/123",
        "created_at": "2025-01-15T10:00:00",
    },
    {
        "id": 2,
        "site": "LeBonCoin",
        "title": "T2 Saint-Agne",
        "price": 480,
        "location_raw": "Toulouse 31400",
        "distance_enac_km": 3.1,
        "url": "https://www.leboncoin.fr/annonce/456",
        "created_at": "2025-01-16T14:30:00",
    },
]


class TestExportCSV:
    def test_csv_creates_file(self, tmp_path):
        out = tmp_path / "test.csv"
        result = export_csv(SAMPLE_ANNONCES, out)
        assert result == out
        assert out.exists()

    def test_csv_has_correct_headers(self, tmp_path):
        out = tmp_path / "test.csv"
        export_csv(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == EXPORT_FIELDS

    def test_csv_has_correct_row_count(self, tmp_path):
        out = tmp_path / "test.csv"
        export_csv(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_csv_contains_data(self, tmp_path):
        out = tmp_path / "test.csv"
        export_csv(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["price"] == "430"
        assert row["title"] == "Studio Rangueil"
        assert row["site"] == "SeLoger"

    def test_csv_empty_list(self, tmp_path):
        out = tmp_path / "test.csv"
        export_csv([], out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0


class TestExportJSON:
    def test_json_creates_file(self, tmp_path):
        out = tmp_path / "test.json"
        result = export_json(SAMPLE_ANNONCES, out)
        assert result == out
        assert out.exists()

    def test_json_is_valid(self, tmp_path):
        out = tmp_path / "test.json"
        export_json(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_json_contains_only_export_fields(self, tmp_path):
        out = tmp_path / "test.json"
        export_json(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            assert set(entry.keys()) == set(EXPORT_FIELDS)

    def test_json_contains_data(self, tmp_path):
        out = tmp_path / "test.json"
        export_json(SAMPLE_ANNONCES, out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["price"] == 430
        assert data[0]["title"] == "Studio Rangueil"
        assert data[1]["site"] == "LeBonCoin"

    def test_json_empty_list(self, tmp_path):
        out = tmp_path / "test.json"
        export_json([], out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert data == []
