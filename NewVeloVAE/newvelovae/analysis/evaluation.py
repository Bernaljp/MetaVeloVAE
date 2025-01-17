import numpy as np
import pandas as pd
from ..model.model_util import make_dir
from .evaluation_util import *
from newvelovae.plotting import get_colors, plot_cluster, plot_phase_grid, plot_sig_grid, plot_time_grid
from multiprocessing import cpu_count
from scipy.stats import spearmanr


def get_n_cpu(n_cell):
    # used for scVelo parallel jobs
    return int(min(cpu_count(), max(1, n_cell/2000)))


def get_velocity_metric_placeholder(cluster_edges):
    cbdir_embed = dict.fromkeys(cluster_edges)
    cbdir = dict.fromkeys(cluster_edges)
    tscore = dict.fromkeys(cluster_edges)
    iccoh = dict.fromkeys(cluster_edges)
    return (iccoh, np.nan,
            cbdir_embed, np.nan,
            cbdir, np.nan,
            tscore, np.nan,
            np.nan)


def get_velocity_metric(adata,
                        key,
                        vkey,
                        cluster_key,
                        cluster_edges,
                        gene_mask=None,
                        embed='umap',
                        n_jobs=None):
    mean_constcy_score = velocity_consistency(adata, vkey, gene_mask)
    if cluster_edges is not None:
        try:
            from scvelo.tl import velocity_graph, velocity_embedding
            n_jobs = get_n_cpu(adata.n_obs) if n_jobs is None else n_jobs
            gene_subset = adata.var_names if gene_mask is None else adata.var_names[gene_mask]
            velocity_graph(adata, vkey=vkey, gene_subset=gene_subset, n_jobs=n_jobs)
            velocity_embedding(adata, vkey=vkey, basis=embed)
        except ImportError:
            print("Please install scVelo to compute velocity embedding.\n"
            "Skipping metrics 'Cross-Boundary Direction Correctness' and 'In-Cluster Coherence'.")
        iccoh, mean_iccoh = inner_cluster_coh(adata, cluster_key, vkey, gene_mask)
        (cbdir_embed, mean_cbdir_embed,
         tscore, mean_tscore) = calibrated_cross_boundary_correctness(adata,
                                                                      cluster_key,
                                                                      vkey,
                                                                      f'{key}_time',
                                                                      cluster_edges,
                                                                      x_emb=f"X_{embed}")
        (cbdir, mean_cbdir,
         tscore, mean_tscore) = calibrated_cross_boundary_correctness(adata,
                                                                      cluster_key,
                                                                      vkey,
                                                                      f'{key}_time',
                                                                      cluster_edges,
                                                                      x_emb="Ms",
                                                                      gene_mask=gene_mask)
    else:
        mean_cbdir_embed = np.nan
        mean_cbdir = np.nan
        mean_tscore = np.nan
        mean_iccoh = np.nan
        cbdir_embed = dict.fromkeys([])
        cbdir = dict.fromkeys([])
        tscore = dict.fromkeys([])
        iccoh = dict.fromkeys([])
    return (iccoh, mean_iccoh,
            cbdir_embed, mean_cbdir_embed,
            cbdir, mean_cbdir,
            tscore, mean_tscore,
            mean_constcy_score)
    

def get_metric(adata,
               method,
               key,
               vkey,
               cluster_key="clusters",
               gene_key='velocity_genes',
               cluster_edges=[],
               embed='umap',
               n_jobs=None):
    """Get specific metrics given a method.

    Arguments
    ---------
    adata : :class:`anndata.AnnData`
    key : str
       Key in .var or .varm for extracting the ODE parameters learned by the model
    vkey : str
        Key in .layers for extracting rna velocity
    cluster_key : str
        Key in .obs for extracting cell type annotation
    gene_key : str, optional
       Key for filtering the genes.
    cluster_edges : str, optional
        List of tuples. Each tuple contains the progenitor cell type and its descendant cell type.
    embed : str, optional
        Low-dimensional embedding name.
    n_jobs : int, optional
        Number of parallel jobs. Used in scVelo velocity graph computation.
    Returns
    -------
    stats : :class:`pandas.DataFrame`
        Stores the performance metrics. Rows are metric names and columns are method names
    """

    stats = {
        'MSE Train': np.nan,
        'MSE Test': np.nan,
        'MAE Train': np.nan,
        'MAE Test': np.nan,
        'LL Train': np.nan,
        'LL Test': np.nan,
        'Training Time': np.nan
    }  # contains the performance metrics
    if gene_key is not None and gene_key in adata.var:
        gene_mask = adata.var[gene_key].to_numpy()
    else:
        gene_mask = None

    if method == 'scVelo':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_scv(adata)
    elif method == 'Vanilla VAE':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_vanilla(adata, key, gene_mask)
    elif method == 'Cycle VAE':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_cycle(adata, key, gene_mask)
    elif method == 'VeloVAE' or method == 'FullVB':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_velovae(adata, key, gene_mask, 'FullVB' in method)
    elif method == 'BrODE':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_brode(adata, key, gene_mask)
    elif method == 'Discrete VeloVAE' or method == 'Discrete FullVB':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_velovae(adata, key, gene_mask, 'FullVB' in method, True)
    elif method == 'UniTVelo':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_utv(adata, key, gene_mask)
    elif method == 'DeepVelo':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_dv(adata, key, gene_mask)
    elif 'PyroVelocity' in method:
        if 'err' in adata.uns:
            mse_train, mse_test = adata.uns['err']['MSE Train'], adata.uns['err']['MSE Test']
            mae_train, mae_test = adata.uns['err']['MAE Train'], adata.uns['err']['MAE Test']
            logp_train, logp_test = adata.uns['err']['LL Train'], adata.uns['err']['LL Test']
            run_time = adata.uns[f'{key}_run_time'] if f'{key}_run_time' in adata.uns else np.nan
        else:
            (mse_train, mse_test,
             mae_train, mae_test,
             logp_train, logp_test,
             run_time) = get_err_pv(adata, key, gene_mask, 'Continuous' not in method)
    elif method == 'VeloVI':
        (mse_train, mse_test,
         mae_train, mae_test,
         logp_train, logp_test,
         run_time) = get_err_velovi(adata, key, gene_mask)
    else:
        mse_train, mse_test = np.nan, np.nan
        mae_train, mae_test = np.nan, np.nan
        logp_train, logp_test = np.nan, np.nan
        try:
            run_time = adata.uns[f'{key}_run_time']
        except KeyError:
            run_time = np.nan
    stats['MSE Train'] = mse_train
    stats['MSE Test'] = mse_test
    stats['MAE Train'] = mae_train
    stats['MAE Test'] = mae_test
    stats['LL Train'] = logp_train
    stats['LL Test'] = logp_test
    stats['Training Time'] = run_time

    if 'tprior' in adata.obs:
        if method == 'DeepVelo':
            stats['corr'] = np.nan
        else:
            tprior = adata.obs['tprior'].to_numpy()
            t = (adata.obs["latent_time"].to_numpy()
                 if (method in ['scVelo', 'UniTVelo']) else
                 adata.obs[f"{key}_time"].to_numpy())
            corr, pval = spearmanr(t, tprior)
            stats['corr'] = corr
    else:
        stats['corr'] = np.nan

    print("Computing velocity embedding using scVelo")
    # Compute velocity metrics using a subset of genes defined by gene_mask
    if gene_mask is not None:
        (iccoh_sub, mean_iccoh_sub,
         cbdir_sub_embed, mean_cbdir_sub_embed,
         cbdir_sub, mean_cbdir_sub,
         tscore_sub, mean_tscore_sub,
         mean_vel_consistency_sub) = get_velocity_metric(adata,
                                                         key,
                                                         vkey,
                                                         cluster_key,
                                                         cluster_edges,
                                                         gene_mask,
                                                         embed,
                                                         n_jobs)
    else:
        (iccoh_sub, mean_iccoh_sub,
         cbdir_sub_embed, mean_cbdir_sub_embed,
         cbdir_sub, mean_cbdir_sub,
         tscore_sub, mean_tscore_sub,
         mean_vel_consistency_sub) = get_velocity_metric_placeholder(cluster_edges)
    stats['CBDir (Embed, Subset)'] = mean_cbdir_sub_embed
    stats['CBDir (Subset)'] = mean_cbdir_sub
    stats['In-Cluster Coherence (Subset)'] = mean_iccoh_sub
    stats['Vel Consistency (Subset)'] = mean_vel_consistency_sub

    # Compute velocity metrics on all genes
    (iccoh, mean_iccoh,
     cbdir_embed, mean_cbdir_embed,
     cbdir, mean_cbdir,
     tscore, mean_tscore,
     mean_vel_consistency) = get_velocity_metric(adata,
                                                 key,
                                                 vkey,
                                                 cluster_key,
                                                 cluster_edges,
                                                 None,
                                                 embed,
                                                 n_jobs)
    stats['CBDir (Embed)'] = mean_cbdir_embed
    stats['CBDir'] = mean_cbdir
    stats['Time Score'] = mean_tscore
    stats['In-Cluster Coherence'] = mean_iccoh
    stats['Vel Consistency'] = mean_vel_consistency
    stats_type = pd.concat([pd.DataFrame.from_dict(cbdir_sub, orient='index'),
                            pd.DataFrame.from_dict(cbdir_sub_embed, orient='index'),
                            pd.DataFrame.from_dict(cbdir, orient='index'),
                            pd.DataFrame.from_dict(cbdir_embed, orient='index'),
                            pd.DataFrame.from_dict(tscore, orient='index')],
                           axis=1).T
    stats_type.index = pd.Index(['CBDir (Subset)',
                                 'CBDir (Embed, Subset)',
                                 'CBDir',
                                 'CBDir (Embed)',
                                 'Time Score'])
    return stats, stats_type


def post_analysis(adata,
                  test_id,
                  methods,
                  keys,
                  gene_key='velocity_genes',
                  compute_metrics=True,
                  raw_count=False,
                  genes=[],
                  plot_type=['time', 'gene', 'stream'],
                  cluster_key="clusters",
                  cluster_edges=[],
                  nplot=500,
                  frac=0.0,
                  embed="umap",
                  grid_size=(1, 1),
                  figure_path="figures",
                  save=None,
                  **kwargs):
    """Main function for post analysis.
    This function computes performance metrics and generates plots based on user input.

    Arguments
    ---------
    adata : :class:`anndata.AnnData`
    test_id : str
        Used for naming the figures.
        For example, it can be set as the name of the dataset.
    methods : string list
        Contains the methods to compare with.
        Valid methods are "scVelo", "Vanilla VAE", "VeloVAE" and "BrODE".
    keys : string list
        Used for extracting ODE parameters from .var or .varm from anndata
        It should be of the same length as methods.
    gene_key : string, optional
        Key in .var for gene filtering. Usually set to select velocity genes.
    compute_metrics : bool, optional
        Whether to compute the performance metrics for the methods
    raw_count : bool, optional
        Whether to plot raw count numbers. Used for discrete models.
    genes : string list, optional
        Genes to plot. Used when plot_type contains "phase" or "gene"
    plot_type : string list, optional
        Type of plots to generate.
        Currently supports phase, gene (u/s/v vs. t), time and cell type
    cluster_key : str, optional
        Key in .obs containing the cell type labels
    cluster_edges : list of tuples, optional
        List of ground-truth cell type ancestor-descendant relations, e.g. (A, B)
        means cell type A is the ancestor of type B. This is used for computing
        velocity metrics.
    nplot : int, optional
        (Optional) Number of data points in the prediction (or for each cell type in VeloVAE and BrODE).
        This is to save computation. For plotting the prediction, we don't need
        as many points as the original dataset contains.
    frac : float in (0,1), optional
        Parameter for the loess plot.
        A higher value means larger time window and the resulting fitted line will
        be smoother.
    embed : str, optional
        2D embedding used for visualization of time and cell type.
        The true key for the embedding is f"X_{embed}" in .obsm
    grid_size : int tuple, optional
        Grid size for plotting the genes.
        n_row*n_col >= len(genes)
    figure_path : str, optional
        Path to save the figures.
    save : str, optional
        Path + output file name to save the AnnData object to a .h5ad file
    Returns
    -------
    stats_df : :class:`pandas.DataFrame`
        Contains the dataset-wise performance metrics of all methods.
        Saves the figures to 'figure_path'.
    stats_df_type : :class:`pandas.DataFrame`
        Contains the performance metrics of each pair of ancestor 
        and desendant cell types.
        Saves the figures to 'figure_path'.
    """
    make_dir(figure_path)
    # Retrieve data
    if raw_count:
        U, S = adata.layers["unspliced"].A, adata.layers["spliced"].A
    else:
        U, S = adata.layers["Mu"], adata.layers["Ms"]
    X_embed = adata.obsm[f"X_{embed}"]
    cell_labels_raw = adata.obs[cluster_key].to_numpy()
    cell_types_raw = np.unique(cell_labels_raw)
    label_dic = {}
    for i, x in enumerate(cell_types_raw):
        label_dic[x] = i
    cell_labels = np.array([label_dic[x] for x in cell_labels_raw])

    # Get gene indices
    if len(genes) > 0:
        gene_indices = []
        gene_rm = []
        for gene in genes:
            idx = np.where(adata.var_names == gene)[0]
            if len(idx) > 0:
                gene_indices.append(idx[0])
            else:
                print(f"Warning: gene name {gene} not found in AnnData. Removed.")
                gene_rm.append(gene)
        for gene in gene_rm:
            genes.remove(gene)

        if len(gene_indices) == 0:
            print("Warning: No gene names found. Randomly select genes...")
            gene_indices = np.random.choice(adata.n_vars, grid_size[0]*grid_size[1], replace=False).astype(int)
            genes = adata.var_names[gene_indices].to_numpy()
    else:
        print("Warning: No gene names are provided. Randomly select genes...")
        gene_indices = np.random.choice(adata.n_vars, grid_size[0]*grid_size[1], replace=False).astype(int)
        genes = adata.var_names[gene_indices].to_numpy()
        print(genes)

    stats = {}
    stats_type_list = []
    Uhat, Shat, V = {}, {}, {}
    That, Yhat = {}, {}
    vkeys = []
    for i, method in enumerate(methods):
        vkey = 'velocity' if method in ['scVelo', 'UniTVelo', 'DeepVelo'] else f'{keys[i]}_velocity'
        vkeys.append(vkey)

    # Compute metrics and generate plots for each method
    for i, method in enumerate(methods):
        if compute_metrics:
            stats_i, stats_type_i = get_metric(adata,
                                               method,
                                               keys[i],
                                               vkeys[i],
                                               cluster_key,
                                               gene_key,
                                               cluster_edges,
                                               embed,
                                               n_jobs=(kwargs['n_jobs']
                                                       if 'n_jobs' in kwargs
                                                       else None))
            stats_type_list.append(stats_type_i)
            # avoid duplicate methods with different keys
            method_ = f"{method} ({keys[i]})" if method in stats else method
            stats[method_] = stats_i
        # Compute prediction for the purpose of plotting (a fixed number of plots)
        if 'phase' in plot_type or 'gene' in plot_type or 'all' in plot_type:
            # avoid duplicate methods with different keys
            method_ = f"{method} ({keys[i]})" if method in V else method
            # Integer-encoded cell type
            cell_labels_raw = adata.obs[cluster_key].to_numpy()
            cell_types_raw = np.unique(cell_labels_raw)
            cell_labels = np.zeros((len(cell_labels_raw)))
            for j in range(len(cell_types_raw)):
                cell_labels[cell_labels_raw == cell_types_raw[j]] = j

            if method == 'scVelo':
                t_i, Uhat_i, Shat_i = get_pred_scv_demo(adata, keys[i], genes, nplot)
                Yhat[method_] = np.concatenate((np.zeros((nplot)), np.ones((nplot))))
                V[method_] = adata.layers["velocity"][:, gene_indices]
            elif method == 'Vanilla VAE':
                t_i, Uhat_i, Shat_i = get_pred_vanilla_demo(adata, keys[i], genes, nplot)
                Yhat[method_] = None
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
            elif method == 'Cycle VAE':
                t_i, Uhat_i, Shat_i = get_pred_cycle_demo(adata, keys[i], genes, nplot)
                Yhat[method_] = None
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
            elif method in ['VeloVAE', 'FullVB', 'Discrete VeloVAE', 'Discrete FullVB']:
                Uhat_i, Shat_i = get_pred_velovae_demo(adata, keys[i], genes, 'FullVB' in method, 'Discrete' in method)
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
                t_i = adata.obs[f'{keys[i]}_time'].to_numpy()
                Yhat[method_] = cell_labels
            elif method == 'BrODE':
                Uhat_i, Shat_i = get_pred_brode_demo(adata, keys[i], genes)
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
                t_i = adata.obs[f'{keys[i]}_time'].to_numpy()
                Yhat[method_] = cell_labels
            elif method == "UniTVelo":
                t_i, Uhat_i, Shat_i = get_pred_utv_demo(adata, genes, nplot)
                V[method_] = adata.layers["velocity"][:, gene_indices]
                Yhat[method_] = None
            elif method == "DeepVelo":
                t_i = adata.obs[f'{keys[i]}_time'].to_numpy()
                V[method_] = adata.layers["velocity"][:, gene_indices]
                Uhat_i = adata.layers["Mu"][:, gene_indices]
                Shat_i = adata.layers["Ms"][:, gene_indices]
                Yhat[method_] = None
            elif method in ["PyroVelocity", "Continuous PyroVelocity"]:
                t_i = adata.obs[f'{keys[i]}_time'].to_numpy()
                Uhat_i = adata.layers[f'{keys[i]}_u'][:, gene_indices]
                Shat_i = adata.layers[f'{keys[i]}_s'][:, gene_indices]
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
                Yhat[method_] = cell_labels
            elif method == "VeloVI":
                t_i = adata.layers['fit_t'][:, gene_indices]
                Uhat_i = adata.layers[f'{keys[i]}_uhat'][:, gene_indices]
                Shat_i = adata.layers[f'{keys[i]}_shat'][:, gene_indices]
                V[method_] = adata.layers[f"{keys[i]}_velocity"][:, gene_indices]
                Yhat[method_] = cell_labels
            elif method == "cellDancer":
                t_i = adata.obs[f'{keys[i]}_time'].to_numpy()
                Uhat_i = adata.layers["Mu"][:, gene_indices]
                Shat_i = adata.layers["Ms"][:, gene_indices]
                V[method_] = adata.layers[f"{keykeys[i]}_velocity"][:, gene_indices]
                Yhat[method_] = cell_labels

            That[method_] = t_i
            Uhat[method_] = Uhat_i
            Shat[method_] = Shat_i

    if compute_metrics:
        print("---     Computing Peformance Metrics     ---")
        print(f"Dataset Size: {adata.n_obs} cells, {adata.n_vars} genes")
        stats_df = pd.DataFrame(stats)
        stats_type_df = pd.concat(stats_type_list,
                                  axis=1,
                                  keys=methods,
                                  names=['Model'])
        pd.set_option("display.precision", 3)

    print("---   Plotting  Results   ---")
    if 'cluster' in plot_type or "all" in plot_type:
        plot_cluster(adata.obsm[f"X_{embed}"],
                     adata.obs[cluster_key].to_numpy(),
                     embed=embed,
                     save=f"{figure_path}/{test_id}_umap.png")

    # Generate plots
    if "time" in plot_type or "all" in plot_type:
        T = {}
        capture_time = adata.obs["tprior"].to_numpy() if "tprior" in adata.obs else None
        for i, method in enumerate(methods):
            # avoid duplicate methods with different keys
            method_ = f"{method} ({keys[i]})" if method in T else method
            if method == 'scVelo':
                T[method_] = adata.obs["latent_time"].to_numpy()
            else:
                T[method_] = adata.obs[f"{keys[i]}_time"].to_numpy()
        plot_time_grid(T,
                       X_embed,
                       capture_time,
                       None,
                       down_sample=min(10, max(1, adata.n_obs//5000)),
                       save=f"{figure_path}/{test_id}_time.png")

    if len(genes) == 0:
        return

    format = kwargs["format"] if "format" in kwargs else "png"
    if "phase" in plot_type or "all" in plot_type:
        Labels_phase = {}
        Legends_phase = {}
        Labels_phase_demo = {}
        for i, method in enumerate(methods):
            # avoid duplicate methods with different keys
            method_ = f"{method} ({keys[i]})" if method in Labels_phase else method
            Labels_phase[method_] = cell_state(adata, method, keys[i], gene_indices)
            Legends_phase[method_] = ['Induction', 'Repression', 'Off', 'Unknown']
            Labels_phase_demo[method] = None
        plot_phase_grid(grid_size[0],
                        grid_size[1],
                        genes,
                        U[:, gene_indices],
                        S[:, gene_indices],
                        Labels_phase,
                        Legends_phase,
                        Uhat,
                        Shat,
                        Labels_phase_demo,
                        path=figure_path,
                        figname=test_id,
                        format=format)

    if 'gene' in plot_type or 'all' in plot_type:
        T = {}
        Labels_sig = {}
        Legends_sig = {}
        for i, method in enumerate(methods):
            # avoid duplicate methods with different keys
            method_ = f"{method} ({keys[i]})" if method in Labels_sig else method
            Labels_sig[method_] = np.array([label_dic[x] for x in adata.obs[cluster_key].to_numpy()])
            Legends_sig[method_] = cell_types_raw
            if method == 'scVelo':
                T[method_] = adata.layers[f"{keys[i]}_t"][:, gene_indices]
                T['scVelo Global'] = adata.obs['latent_time'].to_numpy()*20
                Labels_sig['scVelo Global'] = Labels_sig[method]
                Legends_sig['scVelo Global'] = cell_types_raw
            elif method == 'UniTVelo':
                T[method_] = adata.layers["fit_t"][:, gene_indices]
            elif method == 'VeloVI':
                T[method_] = adata.layers["fit_t"][:, gene_indices]
            else:
                T[method_] = adata.obs[f"{keys[i]}_time"].to_numpy()

        sparsity_correction = kwargs['sparsity_correction'] if 'sparsity_correction' in kwargs else False
        plot_sig_grid(grid_size[0],
                      grid_size[1],
                      genes,
                      T,
                      U[:, gene_indices],
                      S[:, gene_indices],
                      Labels_sig,
                      Legends_sig,
                      That,
                      Uhat,
                      Shat,
                      V,
                      Yhat,
                      frac=frac,
                      down_sample=min(20, max(1, adata.n_obs//2500)),
                      sparsity_correction=sparsity_correction,
                      path=figure_path,
                      figname=test_id,
                      format=format)

    if 'stream' in plot_type or 'all' in plot_type:
        try:
            from scvelo.tl import velocity_graph
            from scvelo.pl import velocity_embedding_stream
            colors = get_colors(len(cell_types_raw))
            for i, vkey in enumerate(vkeys):
                if f"{vkey}_graph" not in adata.uns:
                    velocity_graph(adata, vkey=vkey, n_jobs=get_n_cpu(adata.n_obs))
                velocity_embedding_stream(adata,
                                          basis=embed,
                                          vkey=vkey,
                                          title="",
                                          palette=colors,
                                          legend_fontsize=np.clip(15 - np.clip(len(colors)-10, 0, None), 8, None),
                                          legend_loc='on data' if len(colors) <= 10 else 'right margin',
                                          dpi=150,
                                          show=False,
                                          save=f'{figure_path}/{test_id}_{keys[i]}_stream.png')
        except ImportError:
            print('Please install scVelo in order to generate stream plots')
            pass

    if compute_metrics:
        stats_df.to_csv(f"{figure_path}/metrics_{test_id}.csv", sep='\t')
        return stats_df, stats_type_df
    if save is not None:
        adata.write_h5ad(save)
    return None, None
