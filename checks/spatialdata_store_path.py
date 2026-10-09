"""SpatialData writes images to an Icechunk store, but shapes need a filesystem path.

Run: pixi run check-store-path

The script writes an image into an Icechunk session, which succeeds on released packages.
It then writes shapes, which raises, because the shapes writer reads `store.root` to build a
parquet file path. The five commits linked below remove that limit.
"""

from __future__ import annotations

import tempfile
import traceback

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


def session_store(tmp):
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(tmp))
    return repo.writable_session("main").store


def main():
    from spatialdata._io.io_raster import write_image
    from spatialdata._io.io_shapes import write_shapes

    with tempfile.TemporaryDirectory() as tmp:
        store = session_store(tmp)
        root = zarr.open_group(store, mode="a")

        image = Image2DModel.parse(np.zeros((3, 16, 16), dtype="uint8"))
        write_image(image=image, group=root.require_group("images"), name="img")
        print("image written to an Icechunk store: ok")

        shapes = ShapesModel.parse(
            gpd.GeoDataFrame({"radius": [1.0, 1.0]}, geometry=[Point(0, 0), Point(1, 1)])
        )
        raised = None
        try:
            write_shapes(shapes=shapes, group=root.require_group("shapes/pts"))
        except Exception as exc:  # noqa: BLE001 - the type is what the check measures
            raised = exc

        assert raised is not None, (
            "shapes wrote to an Icechunk store. The store-path limit is gone, so this "
            "check and the README row above it are both out of date."
        )

        frame = traceback.extract_tb(raised.__traceback__)[-1]
        print(f"shapes raised {type(raised).__name__} at {frame.filename}:{frame.lineno}")
        print(f"  {raised}")

        assert frame.filename.endswith("spatialdata/_io/io_shapes.py"), (
            f"shapes failed, but not in the shapes writer: {frame.filename}. "
            "The limit may have moved, so re-read the upstream branch before trusting this."
        )

    print()
    print("Images work today. Shapes need a filesystem path.")
    print(f"The five commits that remove the limit: {BRANCH}")


if __name__ == "__main__":
    main()
