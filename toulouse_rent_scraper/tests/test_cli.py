# tests/test_cli.py
# =========================
# CLI en sous-commandes + compatibilité avec l'ancienne syntaxe
# =========================

from unittest.mock import patch

import pytest

import main
from main import build_parser, translate_legacy_args


@pytest.mark.parametrize("legacy,expected", [
    ([], ["scrape"]),
    (["--all"], ["scrape"]),
    (["--seloger"], ["scrape", "--site", "seloger"]),
    (["--leboncoin", "--profile", "blagnac"], ["scrape", "--site", "leboncoin", "--profile", "blagnac"]),
    (["--profile", "enac", "--profile", "blagnac"], ["scrape", "--profile", "enac", "--profile", "blagnac"]),
    (["--export", "csv"], ["scrape", "--export", "csv"]),
    (["--leboncoin", "--enrich", "--limit", "5"], ["scrape", "--site", "leboncoin", "--limit", "5", "--enrich"]),
    (["--enrich", "--limit", "20"], ["enrich", "--limit", "20"]),
    (["--check-links", "--limit", "10"], ["check-links", "--limit", "10"]),
    (["--ui", "--port", "8080"], ["ui", "--port", "8080"]),
    (["--purge"], ["scrape", "--purge"]),
])
def test_legacy_translation(legacy, expected, capsys):
    assert translate_legacy_args(legacy) == expected
    build_parser().parse_args(expected)  # la traduction est toujours valide
    if legacy:
        assert "obsolète" in capsys.readouterr().err


def test_new_syntax_untouched():
    argv = ["scrape", "--site", "leboncoin"]
    assert translate_legacy_args(argv) is argv


def test_scrape_defaults():
    args = build_parser().parse_args(["scrape"])
    assert args.sites is None and args.profile is None and not args.enrich
    assert args.open_details is True


def test_invalid_site_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["scrape", "--site", "logicimmo"])


@pytest.mark.parametrize("argv,target", [
    (["enrich", "--site", "seloger"], "cmd_enrich"),
    (["check-links"], "cmd_check_links"),
    (["purge"], "cmd_purge"),
    (["export", "json"], "cmd_export"),
    (["scrape"], "cmd_scrape"),
])
def test_dispatch(argv, target):
    with patch.object(main, target) as cmd:
        main.main(argv)
    cmd.assert_called_once()


def test_enrich_site_filter_uses_db_site_name():
    with patch("scrapers.enricher.enrich_annonces", return_value={"enriched": 0, "total": 0, "errors": 0}) as enrich:
        main.main(["enrich", "--site", "leboncoin", "--limit", "3"])
    enrich.assert_called_once_with(site_filter="LeBonCoin", limit=3, unattended=False, ids=None)


def test_scrape_runs_pipeline_then_post_steps():
    with patch("pipeline.run_scraping") as run, \
         patch.object(main, "cmd_enrich") as enrich, \
         patch.object(main, "cmd_export") as export:
        main.main(["scrape", "--site", "leboncoin", "--profile", "blagnac", "--export", "csv"])
    profiles, sites = run.call_args.args
    assert [p.key for p in profiles] == ["blagnac"] and sites == ["leboncoin"]
    enrich.assert_not_called()          # Sprint 16 : les fiches sont ouvertes dans le pipeline
    export.assert_called_once_with("csv")


@pytest.mark.parametrize("argv,enrich,limit", [
    (["scrape"], True, None),                                   # ouvre les fiches par défaut
    (["scrape", "--no-enrich"], False, None),                   # recherche seule
    (["scrape", "--enrich", "--limit", "20"], True, 20),        # --enrich toléré, --limit global
    (["scrape", "--unattended"], True, None),                   # timer systemd
])
def test_scrape_opens_details_by_default(argv, enrich, limit):
    with patch("pipeline.run_scraping") as run, patch.object(main, "cmd_enrich") as cmd_enrich:
        main.main(argv)
    assert run.call_args.kwargs["enrich"] is enrich
    assert run.call_args.kwargs["limit"] == limit
    cmd_enrich.assert_not_called()


def test_pap_site_accepted():
    """Sprint 4 : PAP est une source à part entière."""
    assert build_parser().parse_args(["scrape", "--site", "pap"]).sites == ["pap"]
