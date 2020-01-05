""""
This file provides functions for plotting and analyzing the results from running compositional analysis models over multiple parameter sets
"""


import numpy as np
import arviz as az
import seaborn as sns
import pandas as pd
import pickle as pkl
import os
import ast
import matplotlib.pyplot as plt

from util import compositional_analysis_generation_toolbox as gen
from util import result_classes as res
from util import multi_parameter_sampling as mult

#%%

# Helpers for loading result classes from old environment
import io

class RenameUnpickler(pkl.Unpickler):
    def find_class(self, module, name):
        renamed_module = module
        if module == "multi_parameter_sampling" or module == "model.multi_parameter_sampling":
            renamed_module = "util.multi_parameter_sampling"
        if module == "compositional_analysis_generation_toolbox" or module == "model.compositional_analysis_generation_toolbox":
            renamed_module = "util.compositional_analysis_generation_toolbox"
        if module == "result_classes" or module == "model.result_classes":
            renamed_module = "util.result_classes"
        if module == "final_models" or module == "model.final_models":
            renamed_module = "model.dirichlet_models"

        return super(RenameUnpickler, self).find_class(renamed_module, name)


def renamed_load(file_obj):
    return RenameUnpickler(file_obj).load()


def renamed_loads(pickled_bytes):
    file_obj = io.BytesIO(pickled_bytes)
    return renamed_load(file_obj)

#%%


def multi_run_study_analysis_prepare(path, file_identifier="result_", custom_threshold=0.5, keep_results=False):

    """
    Function to calculate discovery rates, ... for an entire directory of multi_parameter_sampling files
    :param path: string - path to directory
    :param file_identifier: string - an (optional) identifier that is part of all files we want to analyze
    :param custom_threshold: float - custom spike-and-slab threshold
    :param keep_results: boolean - if True: Load entire MCMC chains - very memory consuming!!!
    :return: results: List of raw result files
    all_study_params: pandas DataFrame - Parameters and result data for all files
    all_study_params_agg: pandas DataFrame - Parameters and result data, aggregated over all files with identical parameters
    """

    files = os.listdir(path)

    results = []

    print("Calculating discovery rates...")
    i = 0

    # For all files:
    for f in files:
        i += 1

        print("Preparing: ", i / len(files))
        if file_identifier in f:
            # Load file
            r = renamed_load(open(path + "/" + f, "rb"))

            # Calculate final parameters (average over MCMC chain, 0 if inclusion probability < custom_threshold)
            for r_k, r_i in r.mcmc_results.items():
                r.mcmc_results[r_k].params["final_parameter"] = np.where(np.isnan(r_i.params["mean_nonzero"]),
                                                          r_i.params["mean"],
                                                          np.where(r_i.params["inclusion_prob"] > custom_threshold,
                                                                   r_i.params["mean_nonzero"],
                                                                   0))
            # Discovery rates for beta
            r.get_discovery_rates()

            # Add to results
            if keep_results:
                results.append(r)
            else:
                r._MCMCResult__raw_params = {}
                results.append(r)

    # Generate all_study_params
    all_study_params = pd.concat([r.parameters for r in results])
    simulation_parameters = ["cases", "K", "n_total", "n_samples", "b_true", "w_true", "num_results"]
    all_study_params[simulation_parameters] = all_study_params[simulation_parameters].astype(str)

    # Aggregate over identical parameter sets
    all_study_params_agg = all_study_params.groupby(simulation_parameters).sum()

    return results, all_study_params, all_study_params_agg.reset_index()


def get_scores(agg_df):
    """
    Calculates extended summary statistics, such as TPR, TNR, youden index, f1-score, MCC
    :param agg_df: pandas DataFrame - format as all_study_params_agg from multi_run_study_analysis_prepare
    :return: agg_df: input with added columns for summary statistics
    """
    tp = agg_df["tp"]
    tn = agg_df["tn"]
    fp = agg_df["fp"]
    fn = agg_df["fn"]

    tpr = (tp / (tp + fn)).fillna(0)
    agg_df["tpr"] = tpr
    tnr = (tn / (tn + fp)).fillna(0)
    agg_df["tnr"] = tnr
    precision = (tp / (tp + fp)).fillna(0)
    agg_df["precision"] = precision
    acc = (tp + tn) / (tp + tn + fp + fn).fillna(0)
    agg_df["accuracy"] = acc

    agg_df["youden"] = tpr + tnr - 1
    agg_df["f1_score"] = 2 * (tpr * precision / (tpr + precision)).fillna(0)

    agg_df["mcc"] = (((tp * tn) - (fp * fn)) / np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))).fillna(0)

    return agg_df


def plot_discovery_rates_agg(rates_df, dim_1='w_true', dim_2=None, path = None):
    """
    Plot heatmap of TPR and TNR for one parameter series vs. another
    :param rates_df: pandas DataFrame - format as all_study_params_agg from multi_run_study_analysis_prepare
    :param dim_1: string - parameter on x-axis
    :param dim_2: string - parameter on y-axis
    :param path: string - directory to save plot to
    :return:
    """
    sns.set_style("whitegrid")
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))

    # If no second dimension specified, make a 1d-heatmap
    if dim_2 is None:
        rates_df = rates_df.groupby(dim_1).mean().reset_index()
        dim_2 = "x"
        # Generate dataframe for plotting
        plot_data = pd.DataFrame({dim_1: rates_df[dim_1],
                                  dim_2: [1 for i in range(rates_df.shape[0])],
                                  "tpr": rates_df["tpr"],
                                  "tnr": rates_df["tnr"]
                                  })
        # plot Heatmaps
        sns.heatmap(plot_data.pivot(dim_1, dim_2, 'tpr'), ax=ax[0], vmin=0, vmax=1).set_title("MCMC TPR")
        sns.heatmap(plot_data.pivot(dim_1, dim_2, 'tnr'), ax=ax[1], vmin=0, vmax=1).set_title("MCMC TNR")
    else:
        rates_df = rates_df.groupby([dim_1, dim_2]).mean().reset_index()
        # Generate dataframe for plotting
        plot_data = pd.DataFrame({dim_1: rates_df[dim_1],
                                  dim_2: rates_df[dim_2],
                                  "tpr": rates_df["tpr"],
                                  "tnr": rates_df["tnr"]
                                  })
        # plot Heatmaps
        sns.heatmap(plot_data.pivot(dim_1, dim_2, 'tpr'), ax=ax[0], vmin=0, vmax=1).set_title("MCMC TPR")
        sns.heatmap(plot_data.pivot(dim_1, dim_2, 'tnr'), ax=ax[1], vmin=0, vmax=1).set_title("MCMC TNR")

    # Save
    if path is not None:
        plt.savefig(path)

    plt.show()

def plot_cases_vs_controls(rates_df, results, identifier_w, type="MCMC", path = None, suptitle=None):
    """
    Plot heatmaps of TPR and TNR for number of case vs. number of control samples.
    Also plots counts of cases vs. controls for all cell types
    :param rates_df: pandas DataFrame - format as all_study_params_agg from multi_run_study_analysis_prepare
    :param results: pandas DataFrame - same format as results from multi_run_study_analysis_prepare
    :param identifier_w: string - if plotting only a subset of all ground truth effects
    :param path: string - directory to save plot to
    :param suptitle: string - Header for entirety of plots
    :return:
    """
    sns.set_style("whitegrid")
    fig, ax = plt.subplots(2, 2, figsize=(12, 10))

    # DataFrame for heatmaps
    rates_df = rates_df.loc[(rates_df["w_true"]==str(identifier_w))].groupby("n_samples").mean().reset_index()
    plot_data = pd.DataFrame({"controls": [ast.literal_eval(x)[0] for x in rates_df["n_samples"].tolist()],
                              "cases": [ast.literal_eval(x)[1] for x in rates_df["n_samples"].tolist()],
                              "tpr": rates_df["tpr"],
                              "tnr": rates_df["tnr"]
                              })

    # Plot heatmaps
    sns.heatmap(plot_data.pivot("controls", "cases", 'tpr'), ax=ax[0,0], vmin=0, vmax=1).set_title("MCMC TPR")
    sns.heatmap(plot_data.pivot("controls", "cases", 'tnr'), ax=ax[0,1], vmin=0, vmax=1).set_title("MCMC TNR")

    # Case vs. control count boxplots
    cases_y = []
    controls_y = []

    # Get count data
    for r in results:
        if r.parameters.loc[0, "w_true"] == identifier_w:
            for i in r.mcmc_results:
                n_cases = r.parameters.loc[i, "n_samples"][0]

                controls_y.extend(r.mcmc_results[i].y[:n_cases].tolist())
                cases_y.extend(r.mcmc_results[i].y[n_cases:].tolist())

    cases_y = pd.DataFrame(cases_y)
    controls_y = pd.DataFrame(controls_y)

    # Generate boxplots
    sns.boxplot(data=controls_y, ax=ax[1, 0]).set_title("control group cell counts")
    sns.boxplot(data=cases_y, ax=ax[1, 1]).set_title("case group cell counts")

    # Add title
    if suptitle is not None:
        plt.suptitle(suptitle)
    plt.tight_layout()

    # Save plot
    if path is not None:
        plt.savefig(path)

    plt.show()


def multi_run_study_analysis_prepare_per_param(path, file_identifier="result_", custom_threshold=0.5, keep_results=False):
    """
    Function to calculate discovery rates, ... for an entire directory of multi_parameter_sampling files
    Effect Discovery rates are calculated separately for each cell type
    :param path: string - path to directory
    :param file_identifier: string - an (optional) identifier that is part of all files we want to analyze
    :param custom_threshold: float - custom spike-and-slab threshold
    :param keep_results: boolean - if True: Load entire MCMC chains - very memory consuming!!!
    :return: results: List of raw result files
    all_study_params: pandas DataFrame - Parameters and result data for all files
    all_study_params_agg: pandas DataFrame - Parameters and result data, aggregated over all files with identical parameters
    """
    files = os.listdir(path)

    results = []

    print("Calculating discovery rates...")
    i=0

    for f in files:
        i+=1

        print("Preparing: ", i / len(files))
        if file_identifier in f:
            # Load file
            r = renamed_load(open(path + "/" + f, "rb"))
            # Calculate final parameters (average over MCMC chain, 0 if inclusion probability < custom_threshold)
            for r_k, r_i in r.mcmc_results.items():
                r.mcmc_results[r_k].params["final_parameter"] = np.where(np.isnan(r_i.params["mean_nonzero"]),
                                                          r_i.params["mean"],
                                                          np.where(r_i.params["inclusion_prob"] > custom_threshold,
                                                                   r_i.params["mean_nonzero"],
                                                                   0))
            # Discovery rates for beta per parameter
            r.get_discovery_rates_per_param()

            if keep_results:
                results.append(r)
            else:
                r._MCMCResult__raw_params = {}
                results.append(r)

    # Generate all_study_params
    all_study_params = pd.concat([r.parameters for r in results])
    simulation_parameters = ["cases", "K", "n_total", "n_samples", "b_true", "w_true", "num_results"]
    all_study_params[simulation_parameters] = all_study_params[simulation_parameters].astype(str)

    # Aggregate over identical parameter sets
    all_study_params_agg = all_study_params.groupby(simulation_parameters).sum()

    return results, all_study_params, all_study_params_agg.reset_index()


def plot_cases_vs_controls_per_param(K, rates_df, results, identifier_w, path=None, suptitle=None):
    """
    Plot heatmaps of discovery rate for number of case vs. number of control samples, for each cell type.
    Also plots counts of cases vs. controls for all cell types
    :param K: int - number of cell types
    :param rates_df: pandas DataFrame - format as all_study_params_agg from multi_run_study_analysis_prepare
    :param results: pandas DataFrame - same format as results from multi_run_study_analysis_prepare
    :param identifier_w: string - if plotting only a subset of all ground truth effects
    :param path: string - directory to save plot to
    :param suptitle: string - Header for entirety of plots
    :return:
    """

    # plot initialization
    sns.set_style("whitegrid")
    fig, ax = plt.subplots(2, K, figsize=(K*6, 10))
    for a in ax[1, :]:
        a.set_ylim(0, 1000)

    # Get heatmap data relevant for plotting
    rates_df = rates_df.loc[(rates_df["w_true"]==str(identifier_w))].groupby("n_samples").mean().reset_index()
    rates_df["controls"] = [ast.literal_eval(x)[0] for x in rates_df["n_samples"].tolist()]
    rates_df["cases"] = [ast.literal_eval(x)[1] for x in rates_df["n_samples"].tolist()]

    # For each cell type:
    for i in range(K):
        plot_df = rates_df.loc[:,["controls", "cases", "correct_"+str(i), "false_"+str(i)]]
        plot_df["disc_rate"] = plot_df["correct_"+str(i)]/(plot_df["correct_"+str(i)] + plot_df["false_"+str(i)])
        # If Effect on cell type ==0: plot in blue, else plot in red
        if identifier_w[0][i] == 0:
            cmap = "Blues_r"
        else:
            cmap = "Reds_r"
        # Plot heatmap
        sns.heatmap(plot_df.pivot("controls", "cases", 'disc_rate'), ax=ax[0,i], vmin=0, vmax=1, cmap=cmap).\
            set_title("Cell type "+str(i+1)+" accuracy - " + "Effect: " + str(identifier_w[0][i]))

    # Get cell count data for each cell type
    cases_y = []
    controls_y = []
    for r in results:
        if r.parameters.loc[0, "w_true"] == identifier_w:
            for i in r.mcmc_results:
                n_cases = r.parameters.loc[i, "n_samples"][0]

                controls_y.extend(r.mcmc_results[i].y[:n_cases].tolist())
                cases_y.extend(r.mcmc_results[i].y[n_cases:].tolist())
    cases_y = cases_y
    controls_y = controls_y

    # Plot boxplots
    for i in range(K):
        box_df = pd.DataFrame({"controls": [y[i] for y in controls_y],
                               "cases": [y[i] for y in cases_y]})
        lf_change = np.round(np.log2(box_df["cases"].mean() / box_df["controls"].mean()), 2)
        sns.boxplot(data=box_df.loc[:, ["cases", "controls"]], ax=ax[1, i], order=["controls", "cases"]).\
            set_title("Log-fold change: "+str(lf_change))

    # Add title
    if suptitle is not None:
        plt.suptitle(suptitle)

    # Save plot
    plt.tight_layout()
    if path is not None:
        plt.savefig(path)

    plt.show()


def multi_run_study_analysis_multi_model_prepare(path, file_identifier="result_", custom_threshold=0.5, keep_results=False):
    """
    Function to calculate discovery rates, ... for an entire directory of multi_parameter_sampling_multi_model files
    :param path: string - path to directory
    :param file_identifier: string - an (optional) identifier that is part of all files we want to analyze
    :param custom_threshold: float - custom spike-and-slab threshold
    :param keep_results: boolean - if True: Load entire MCMC chains - very memory consuming!!!
    :return: results: List of raw result files
    all_study_params: pandas DataFrame - Parameters and result data for all files
    all_study_params_agg: pandas DataFrame - Parameters and result data, aggregated over all files with identical parameters
    """

    files = os.listdir(path)
    results = []
    print("Calculating discovery rates...")
    i = 0

    # For all files:
    for f in files:
        i+=1

        print("Preparing: ", i / len(files))
        if file_identifier in f:
            # Load file
            r = renamed_load(open(path + "/" + f, "rb"))

            # Calculate final parameters (average over MCMC chain, 0 if inclusion probability < custom_threshold)
            # Need to go into level 2 of all results DataFrames!
            for r_k, r_i in r.results.items():
                for r2_k, r2_i in r_i.items():

                    if "mean_nonzero" in r2_i.params.columns:
                        r_i[r2_k].params["final_parameter"] = np.where(np.isnan(r2_i.params["mean_nonzero"]),
                                                              r2_i.params["mean"],
                                                              np.where(r2_i.params["inclusion_prob"] > custom_threshold,
                                                                       r2_i.params["mean_nonzero"],
                                                                       0))
            # Discovery rates for beta
            r.get_discovery_rates()

            # Add to results
            if keep_results:
                results.append(r)
            else:
                r._MCMCResult__raw_params = {}
                results.append(r)

    # Generate all_study_params
    all_study_params = pd.concat([r.parameters for r in results])
    simulation_parameters = ["cases", "K", "n_total", "n_samples", "b_true", "w_true", "num_results"]
    all_study_params[simulation_parameters] = all_study_params[simulation_parameters].astype(str)

    # Aggregate over identical parameter sets
    all_study_params_agg = all_study_params.groupby(simulation_parameters).sum()

    return results, all_study_params, all_study_params_agg.reset_index()

# ???
def plot_cases_vs_controls_per_param_2(K, rates_df, results, identifier_w, path = None, suptitle=None):
    """
    Optimized version of plot_cases_vs_controls_per_param
    :param K: int - number of cell types
    :param rates_df: pandas DataFrame - format as all_study_params_agg from multi_run_study_analysis_prepare
    :param results: pandas DataFrame - same format as results from multi_run_study_analysis_prepare
    :param identifier_w: string - if plotting only a subset of all ground truth effects
    :param path: string - directory to save plot to
    :param suptitle: string - Header for entirety of plots
    :return:
    """

    sns.set_style("whitegrid")

    # Get heatmap data relevant for plotting
    rates_df = rates_df.loc[(rates_df["w_true"]==str(identifier_w))].groupby("n_samples").mean().reset_index()
    rates_df["controls"] = [ast.literal_eval(x)[0] for x in rates_df["n_samples"].tolist()]
    rates_df["cases"] = [ast.literal_eval(x)[1] for x in rates_df["n_samples"].tolist()]

    # Get cell count data for each cell type
    cases_y = []
    controls_y = []
    for r in results:
        if r.parameters.loc[0, "w_true"] == identifier_w:
            for i in r.mcmc_results:
                n_cases = r.parameters.loc[i, "n_samples"][0]

                controls_y.extend(r.mcmc_results[i].y[:n_cases].tolist())
                cases_y.extend(r.mcmc_results[i].y[n_cases:].tolist())
    cases_y = cases_y
    controls_y = controls_y

    # For each cell type:
    for i in range(K):
        # Initialize plot
        fig, ax = plt.subplots(2, 1, figsize=(6, 10))
        ax[1].set_ylim(0, 1000)

        # DataFrame for heatmap
        plot_df = rates_df.loc[:,["controls", "cases", "correct_"+str(i), "false_"+str(i)]]
        plot_df["disc_rate"] = plot_df["correct_"+str(i)]/(plot_df["correct_"+str(i)] + plot_df["false_"+str(i)])
        # If Effect on cell type ==0: plot in blue, else plot in red
        if identifier_w[0][i] == 0:
            cmap = "Blues_r"
        else:
            cmap = "Reds_r"
        # Plot heatmap
        sns.heatmap(plot_df.pivot("controls", "cases", 'disc_rate'), ax=ax[0], vmin=0, vmax=1, cmap=cmap).\
            set_title("Accuracy")

        # DataFrame for boxplot
        box_df = pd.DataFrame({"controls": [y[i] for y in controls_y],
                               "cases": [y[i] for y in cases_y]})
        change = np.round(box_df["cases"].mean() - box_df["controls"].mean(), 2)
        sns.boxplot(data=box_df.loc[:, ["cases", "controls"]], ax=ax[1], order=["controls", "cases"]).\
            set_title("Average change: "+str(change)+" cells")

        # Add title
        if suptitle is not None:
            plt.suptitle(suptitle)

        # Save plot
        plt.tight_layout()
        if path is not None:
            plt.savefig(path + "_type_" + str(i+1).replace(".", ""), bbox_inches="tight")

    plt.show()