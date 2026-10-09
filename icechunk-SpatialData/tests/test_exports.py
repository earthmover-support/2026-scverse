"""The package exports exactly the names this repository documents."""

from __future__ import annotations

import icechunk_spatialdata as isd

EXPECTED = {
    "ZarrArrayFileSystem",
    "bounded_reads",
    "declare_container",
    "images_in_h5ad_are_channel_last",
    "parquet_in_store",
    "parquet_in_store_available",
    "reference_count",
    "reference_file",
    "repository_config",
    "transaction",
    "virtual_image",
    "virtual_table",
    "write_csc_layer",
}


def test_all_matches_the_documented_set():
    assert set(isd.__all__) == EXPECTED


def test_every_exported_name_resolves():
    missing = [n for n in isd.__all__ if not hasattr(isd, n)]
    assert missing == []


def test_tiles_view_is_gone():
    assert not hasattr(isd, "tiles_view")
