"""Generate squidpy_xenium_virtual.ipynb.

This repository defines no pixi task for the notebook, and it declares no squidpy environment.
Regenerate it with `python scripts/build_squidpy_xenium_notebook.py`.

Executing it needs an Arraylake account and squidpy, so the committed outputs ship executed.

squidpy needs an environment of its own. It pins `imagecodecs <2026`, and that pin keeps
tifffile at one version. The Zarr view of a TIFF in that version does not import against zarr
3.3. Thus the `spatial` environment took the newer tifffile.

The notebook replaces squidpy's `tutorial_xenium.ipynb`. It uses the same Human Lung Cancer sample.
It reads the sample from `earthmover-demos/xenium-lung-virtual`, not from a downloaded and converted
bundle. Its markdown and its calls are squidpy's, near-verbatim.

One section at the top holds all commentary about the store, as in
`build_xenium_tutorial_notebook.py`. The napari section at the end stays, with the tag
`skip-execution`. It opens an interactive viewer, and a generated notebook cannot run that viewer.
Without the section, this notebook would be a shorter tutorial, not the same one.
"""

from _notebook import code, md, write

md("""
> **This notebook needs an Arraylake account.** It reads the Arraylake repository
> `earthmover-demos/xenium-lung-virtual`, and Arraylake has no anonymous read. The committed run
> built an AnnData of 162,254 cells by 541 genes from that repository. It then ran the whole
> squidpy Xenium tutorial on it. The outputs below ship executed. A reader without an account
> sees every figure this run produced.
""")

TUTORIAL = "https://squidpy.readthedocs.io/en/stable/notebooks/tutorials/tutorial_xenium.html"

md("# Analyze Xenium data")

md(f"""
This notebook replaces [squidpy's notebook of the same name]({TUTORIAL}). It keeps their text and
their calls, and it uses the same Human Lung Cancer sample. It reads the sample from an Arraylake
repository that **holds almost none of the data**. The counts, the images, the segmentation masks
and the transcripts are byte ranges into the files that 10x published. We did not download or
convert any file.

The full list of differences:

- **Loading.** `sd.read_zarr(session.store)` replaces `xenium()` plus `sdata.write()` plus
  `sd.read_zarr(path)`, because the notebook converts nothing. `isd.parquet_in_store()` lets the
  shapes read from the store. The loading cell has no other change. The TIFF parser that wrote the
  image references also supplies their JPEG 2000 codec.
- **Reads.** `isd.repository_config()` retries a dropped connection. `isd.bounded_reads()` limits
  the number of connections that one compute opens. Neither function changes a result.
- **`morphology_focus` has one channel, not four.** 10x publish the other three only inside their
  8 GB `outs.zip`, and they deflate them there. A deflated member is one Huffman-coded stream, so
  no offset inside it is addressable. The channel present is DAPI.
- **The napari cell is present, with the tag `skip-execution`.** It opens a GUI, so a generated
  notebook cannot run it. Run it by hand, after `pip install napari-spatialdata`. This project's
  environment deliberately does not include that package.
- **The two gene figures plot `MET` only.** squidpy's version asks for `["AREG", "MET"]`. `AREG`
  is not in this sample's panel. 10x's own `gene_panel.json` lists 397 targets, and `AREG` is not
  among them. Thus the cells cannot run on the dataset that the notebook says it uses. `MET` and
  `EPCAM` are present.
- **The last `render_shapes` does not pass `use_raw=False`.** `spatialdata-plot` no longer accepts
  it, in the version that squidpy resolves here or in the next version. The rest of that call is
  squidpy's.

Everything else is squidpy's. One more fact is useful, and it is *not* a difference. The store holds
`adata.obsm["spatial"]` and all of `adata.obs` as native data, not as references. They are small,
and the analysis below actually reads them. `X` holds no counts at all, only byte ranges into 10x's
`cell_feature_matrix.h5`. `scanpy` and `squidpy` cannot see the difference.
""")

code("""
import warnings

warnings.simplefilter("ignore")

import matplotlib.pyplot as plt
import seaborn as sns

import scanpy as sc
import squidpy as sq
import spatialdata as sd  # noqa: F401

import icechunk_spatialdata as isd
""")

md("""
A reader for Xenium data is available in `spatialdata-io`. We use it to parse and convert to Zarr a [Xenium dataset of Human Lung Cancer](https://www.10xgenomics.com/datasets/preview-data-ffpe-human-lung-cancer-with-xenium-multimodal-cell-segmentation-1-standard).
""")

md("""
Here that step is already complete, and it copied nothing. The repository below references 10x's
published files directly. It follows the conventions of `spatialdata_io`, so the analysis does not
change.
""")

code("""
repo_name = "earthmover-demos/xenium-lung-virtual"
""")

md("From now on we only read directly from the store.")

code("""
from arraylake import Client
from arraylake import config as al_config

# The published repo is on prod. A local config can point the client at dev.
al_config.set({"service.uri": "https://api.earthmover.io"})

session = Client().get_repo(repo_name, config=isd.repository_config()).readonly_session("main")
isd.bounded_reads()
with isd.parquet_in_store():
    sdata = sd.read_zarr(session.store)

for kind in ("images", "labels", "shapes", "tables"):
    for name in getattr(sdata, kind):
        print(f"{kind}/{name}")
""")

md("""
For the analysis we use the `anndata.AnnData` object, which contains the count matrix, cell and gene annotations. It is stored in the `spatialdata.tables` layer.
""")

code("""
adata = sdata.tables["table"]
adata
""")

code("""
adata.obs
""")

md("""
Squidpy looks for cell coordinates in `.obsm["spatial"]`. By using the Xenium reader from `spatialdata-io` this is already automatically set. For more complex data this needs to be set manually, more details can be found in this [spatialdata tutorial on squidpy integration](https://spatialdata.scverse.org/en/latest/tutorials/notebooks/notebooks/examples/squidpy_integration.html).
""")

code("""
adata.obsm["spatial"]
""")

md("""
## Calculate quality control metrics

Calculate the quality control metrics on the `anndata.AnnData` using `scanpy.pp.calculate_qc_metrics`.
""")

code("""
sc.pp.calculate_qc_metrics(adata, percent_top=(10, 20, 50, 150), inplace=True)
""")

md("The percentage of control probes and control codewords can be calculated from `adata.obs`")

code("""
cprobes = (
    adata.obs["control_probe_counts"].sum() / adata.obs["total_counts"].sum() * 100
)
cwords = (
    adata.obs["control_codeword_counts"].sum() / adata.obs["total_counts"].sum() * 100
)
print(f"Negative DNA probe count % : {cprobes}")
print(f"Negative decoding count % : {cwords}")
""")

md("""
Next we plot the distribution of total transcripts per cell, unique transcripts per cell, area of segmented cells and the ratio of nuclei area to their cells
""")

code("""
fig, axs = plt.subplots(1, 4, figsize=(15, 4))

axs[0].set_title("Total transcripts per cell")
sns.histplot(
    adata.obs["total_counts"],
    kde=False,
    ax=axs[0],
)

axs[1].set_title("Unique transcripts per cell")
sns.histplot(
    adata.obs["n_genes_by_counts"],
    kde=False,
    ax=axs[1],
)

axs[2].set_title("Area of segmented cells")
sns.histplot(
    adata.obs["cell_area"],
    kde=False,
    ax=axs[2],
)

axs[3].set_title("Nucleus ratio")
sns.histplot(
    adata.obs["nucleus_area"] / adata.obs["cell_area"],
    kde=False,
    ax=axs[3],
)
fig.tight_layout()
""")

md("""
Filter the cells based on the minimum number of counts required using `scanpy.pp.filter_cells`. Filter the genes based on the minimum number of cells required with `scanpy.pp.filter_genes`. The parameters for the both were specified based on the plots above.
""")

code("""
sc.pp.filter_cells(adata, min_counts=10)
sc.pp.filter_genes(adata, min_cells=5)
""")

md("""
Normalize counts per cell using `scanpy.pp.normalize_total`.

Logarithmize, do principal component analysis, compute a neighborhood graph of the observations using `scanpy.pp.log1p`, `scanpy.pp.pca` and `scanpy.pp.neighbors` respectively.

Use `scanpy.tl.umap` to embed the neighborhood graph of the data and cluster the cells into subgroups employing `scanpy.tl.leiden`.
""")

code("""
adata.layers["counts"] = adata.X.copy()
sc.pp.normalize_total(adata, inplace=True)
sc.pp.log1p(adata)
sc.pp.pca(adata)
sc.pp.neighbors(adata)
sc.tl.umap(adata)
sc.tl.leiden(adata)
""")

md("""
## Visualize annotation on UMAP and spatial coordinates
""")

code("""
sc.pl.umap(
    adata,
    color=[
        "total_counts",
        "n_genes_by_counts",
        "leiden",
    ],
    wspace=0.4,
)
""")

code("""
sq.pl.spatial_scatter(
    adata,
    library_id="spatial",
    shape=None,
    color=[
        "leiden",
    ],
    wspace=0.4,
)
""")

md("""
## Computation of spatial statistics

This example shows how to compute centrality scores, given a spatial graph and cell type annotation.

The scores calculated are closeness centrality, degree centrality and clustering coefficient with the following properties:

- closeness centrality - measure of how close the group is to other nodes.
- clustering coefficient - measure of the degree to which nodes cluster together.
- degree centrality - fraction of non-group members connected to group members.

All scores are descriptive statistics of the spatial graph.
""")

md("""
### Building a spatial neighborhood graph

First, we need to compute a connectivity matrix from spatial coordinates to calculate the centrality scores. We can use `squidpy.gr.spatial_neighbors` for this purpose.
""")

code("""
sq.gr.spatial_neighbors(adata, coord_type="generic", delaunay=True)
""")

md("""
### Compute centrality scores

Centrality scores are calculated with `squidpy.gr.centrality_scores`, with the Leiden groups as clusters.
""")

code("""
sq.gr.centrality_scores(adata, cluster_key="leiden")
""")

code("""
sq.pl.centrality_scores(adata, cluster_key="leiden", figsize=(16, 5))
""")

md("""
### Compute co-occurrence probability

This example shows how to compute the co-occurrence probability.

First we create a new table, which is a subset of the original Anndata object, and store it in tables.
""")

code("""
sdata.tables["subsample"] = sc.pp.subsample(adata, fraction=0.5, copy=True)
adata_subsample = sdata.tables["subsample"]
""")

code("""
sq.gr.co_occurrence(
    adata_subsample,
    cluster_key="leiden",
)
sq.pl.co_occurrence(
    adata_subsample,
    cluster_key="leiden",
    clusters="12",
    figsize=(10, 10),
)
sq.pl.spatial_scatter(
    adata_subsample,
    color="leiden",
    shape=None,
    size=2,
)
""")

md("""
### Neighbors enrichment analysis

It calculates an enrichment score based on proximity on the connectivity graph of cell clusters. The number of observed events is compared against permutations and a z-score is computed.
""")

code("""
sq.gr.nhood_enrichment(adata, cluster_key="leiden")
""")

code("""
fig, ax = plt.subplots(1, 2, figsize=(13, 7))
sq.pl.nhood_enrichment(
    adata,
    cluster_key="leiden",
    figsize=(8, 8),
    title="Neighborhood enrichment adata",
    ax=ax[0],
)
sq.pl.spatial_scatter(adata_subsample, color="leiden", shape=None, size=2, ax=ax[1])
fig.tight_layout()
""")

md("""
### Compute Moran's I score

Identification of spatially variable genes with spatial autocorrelation statistics can be done with
`squidpy.gr.spatial_autocorr`.

We can compute the Moran's I score with `squidpy.gr.spatial_autocorr` and mode = 'moran'. We first
need to compute a spatial graph with `squidpy.gr.spatial_neighbors`. We will also subset the number
of genes to evaluate.
""")

code("""
sq.gr.spatial_neighbors(adata_subsample, coord_type="generic", delaunay=True)
sq.gr.spatial_autocorr(
    adata_subsample,
    mode="moran",
    n_perms=100,
    n_jobs=1,
)
adata_subsample.uns["moranI"].head(10)
""")

md("""
We can visualize some of those genes with `squidpy.pl.spatial_scatter`. We could also pass
`mode = 'geary'` to compute a closely related auto-correlation statistic, Geary's C. See
`squidpy.gr.spatial_autocorr` for more information.
""")

code("""
sq.pl.spatial_scatter(
    adata_subsample,
    library_id="spatial",
    color=["MET"],   # squidpy's version also asks for AREG, which this panel does not contain
    shape=None,
    size=2,
    img=False,
)
""")

md("""
For plotting we can also use `spatialdata-plot`, a package for static plotting of `spatialdata` objects.
""")

code("""
import spatialdata_plot  # noqa: F401

gene_name = ["MET"]   # squidpy's version also asks for AREG, which this panel does not contain
for name in gene_name:
    sdata.pl.render_images("morphology_focus").pl.render_shapes(
        "cell_circles",
        color=name,
        table_name="table",
    ).pl.show(
        title=f"{name} expression over Morphology image",
        coordinate_systems="global",
        figsize=(10, 5),
    )
""")

md("""
# Interactive Analysis and Visualization with `napari-spatialdata`

One can leverage `napari-spatialdata` to interactively explore Xenium data through a graphical interface.
""")

md("""
The cell below has the tag `skip-execution`. Thus the run that produced this notebook's outputs did
not execute it. The cell opens a Qt window, and a headless run cannot execute that. To get the
viewer, install `napari-spatialdata` and run the cell by hand. This project's environment does not
include napari or its Qt bindings. They are a large dependency for a figure that a headless run
cannot generate anyway.
""")

code("""
from napari_spatialdata import Interactive

Interactive(sdata)
""", tags=("skip-execution",))

md("""
The following demonstrates AREG gene expression visualization across all cells using the interactive viewer:
""")

md("""
![title](https://squidpy.readthedocs.io/en/stable/_images/Xenium_tutorial_napari_viewer.png)

That screenshot is squidpy's, not this notebook's. It shows AREG, and this sample's panel does not
contain AREG. The note at the top gives the details. The elements that it lists are the elements
that the store holds.
""")

write("squidpy_xenium_virtual.ipynb")
