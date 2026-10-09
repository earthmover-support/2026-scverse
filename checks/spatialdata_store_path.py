"""SpatialData writes images to an Icechunk store, but shapes need a filesystem path.

Run: pixi run check-store-path

The script commits an image to an Icechunk repository and reads it back, which works on
released packages. It writes the same shapes to a local store, which works. It then writes them
to an Icechunk store, which raises, because the shapes writer reads `store.root` to build a
parquet file path. The five commits linked in the output remove that limit.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
import icechunk
import numpy as np
import zarr
from shapely.geometry import Point
from spatialdata.models import Image2DModel, ShapesModel

BRANCH = (
    "https://github.com/selmanozleyen/spatialdata/compare/"
    "feat/zarr-store-class...li-em:spatialdata:li-em/store-without-a-path?expand=1"
)


def main():
    from spatialdata._io.io_raster import write_image
    from spatialdata._io.io_shapes import write_shapes

    with tempfile.TemporaryDirectory() as tmp:
        repo = icechunk.Repository.create(icechunk.local_filesystem_storage(f"{tmp}/repo"))

        session = repo.writable_session("main")
        root = zarr.open_group(session.store, mode="a")
        image = Image2DModel.parse(np.zeros((3, 16, 16), dtype="uint8"))
        write_image(image=image, group=root.require_group("images/img"), name="img")
        session.commit("image")
        reopened = zarr.open_group(repo.readonly_session("main").store, mode="r")
        assert reopened["images/img/s0"].shape == (3, 16, 16), "the committed image is missing."
        print("image committed to an Icechunk store and read back: ok")

        shapes = ShapesModel.parse(
            gpd.GeoDataFrame({"radius": [1.0, 1.0]}, geometry=[Point(0, 0), Point(1, 1)])
        )
        local = zarr.open_group(Path(tmp) / "x.zarr", mode="a")
        write_shapes(shapes=shapes, group=local.require_group("shapes/pts"))
        assert (Path(tmp) / "x.zarr/shapes/pts/shapes.parquet").exists()
        print("same shapes written to a local store: ok")

        icechunk_root = zarr.open_group(repo.writable_session("main").store, mode="a")
        raised = None
        try:
            write_shapes(shapes=shapes, group=icechunk_root.require_group("shapes/pts"))
        except Exception as exc:  # noqa: BLE001 - the type and message are asserted below
            raised = exc

        assert raised is not None, (
            "shapes wrote to an Icechunk store. The store-path limit is gone, so this "
            "check and the README claim are both out of date."
        )
        print(f"same shapes to an Icechunk store raised {type(raised).__name__}: {raised}")

        assert isinstance(raised, AttributeError) and "root" in str(raised), (
            f"shapes failed with {type(raised).__name__}: {raised}. This is not the "
            "store-path limit, so re-read the upstream branch before trusting this."
        )

    print()
    print("Images work today. Shapes need a filesystem path.")
    print(f"The five commits that remove the limit: {BRANCH}")


if __name__ == "__main__":
    main()
