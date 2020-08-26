"""
plotting.py

Methods for plotting data.
"""
import os

import arviz as az
import numpy as np
import xarray as xr
import tensorflow as tf
import seaborn as sns
import matplotlib.pyplot as plt

import utils.file_io as io

from config import (NET_WEIGHTS_HMC, NET_WEIGHTS_L2HMC, NetWeights,
                    NP_FLOAT, PI, PROJECT_DIR, TF_FLOAT)

sns.set_palette('bright')

COLORS = ['C0', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9']


def savefig(fig, fpath):
    io.check_else_make_dir(os.path.dirname(fpath))
    io.log(f'Saving figure to: {fpath}.')
    fig.savefig(fpath, dpi=400, bbox_inches='tight')


def therm_arr(arr, therm_frac=0.2, ret_steps=True):
    """Drop first `therm_frac` steps of `arr` to account for thermalization."""
    #  step_axis = np.argmax(arr.shape)
    step_axis = 0
    num_steps = arr.shape[step_axis]
    therm_steps = int(therm_frac * num_steps)
    arr = np.delete(arr, np.s_[:therm_steps], axis=step_axis)
    steps = np.arange(therm_steps, num_steps)

    if ret_steps:
        return arr, steps

    return arr


def plot_charges(steps, charges, title=None, out_dir=None):
    charges = charges.T
    if charges.shape[0] > 4:
        charges = charges[:4, :]
    fig, ax = plt.subplots()
    for idx, q in enumerate(charges):
        ax.plot(steps, np.around(q) + 5 * idx, marker='', ls='-')
    ax.set_yticks([])
    ax.set_yticklabels([])
    ax.xmargin: 0
    ax.yaxis.set_label_coords(-0.03, 0.5)
    ax.set_ylabel(r"$\mathcal{Q}$", fontsize='x-large',
                  rotation='horizontal')
    ax.set_xlabel('MC Step', fontsize='x-large')
    if title is not None:
        ax.set_title(title, fontsize='x-large')
    plt.tight_layout()

    if out_dir is not None:
        fpath = os.path.join(out_dir, 'charge_chains.png')
        io.log(f'Saving figure to: {fpath}.')
        plt.savefig(fpath, dpi=400, bbox_inches='tight')


def get_title_str_from_params(params):
    """Create a formatted string with relevant params from `params`."""
    eps = params.get('eps', None)
    net_weights = params.get('net_weights', None)
    num_steps = params.get('num_steps', None)
    lattice_shape = params.get('lattice_shape', None)

    title_str = (r"$N_{\mathrm{LF}} = $" + f'{num_steps}, '
                 r"$\varepsilon = $" + f'{tf.reduce_mean(eps):.4g}, ')

    if 'beta_init' in params and 'beta_final' in params:
        beta_init = params.get('beta_init', None)
        beta_final = params.get('beta_final', None)
        #  title_str = r"$\beta_{mathrm{init}} = $" + f'{beta_init}'
        title_str += (r"$\beta: $" + f'{beta_init:.3g}'
                      + r"$\rightarrow$" f'{beta_final:.3g}, ')
    elif 'beta' in params:
        beta = params.get('beta', None)
        title_str += r"$\beta = $" + f'{beta:.3g}, '

    title_str += f'shape: {tuple(lattice_shape)}'

    if net_weights == NET_WEIGHTS_HMC:
        title_str += f', (HMC)'

    return title_str


def mcmc_avg_lineplots(data, title=None, out_dir=None):
    for idx, (key, val) in enumerate(data.items()):
        steps, arr = val
        avg = np.mean(arr, axis=1)
        xy_data = (steps, avg)

        xlabel = 'MC Step'
        ylabel = r"$\langle$" + f'{key}' + r"$\rangle$"
        labels = (xlabel, ylabel)

        if out_dir is not None:
            fpath = os.path.join(out_dir, f'{key}_avg.png')

        _, _ = mcmc_lineplot(xy_data, labels, title=title,
                             fpath=fpath, show_avg=True,
                             color=COLORS[idx])


def mcmc_lineplot(data, labels, title=None,
                  fpath=None, show_avg=False, **kwargs):
    """Make a simple lineplot."""
    fig, ax = plt.subplots()

    if show_avg:
        avg = np.mean(data[1])
        ax.axhline(y=avg, color='gray',
                   label=f'avg: {avg:.3g}',
                   ls='-', marker='')
        ax.legend(loc='best')

    ax.plot(*data, **kwargs)
    ax.set_xlabel(labels[0], fontsize='large')
    ax.set_ylabel(labels[1], fontsize='large')
    if title is not None:
        ax.set_title(title, fontsize='x-large')

    if fpath is not None:
        savefig(fig, fpath)

    return fig, ax


def mcmc_traceplot(key, val, title=None, fpath=None):
    az.plot_trace({key: val})
    fig = plt.gcf()
    if title is not None:
        fig.suptitle(title, fontsize='x-large', y=1.06)

    if fpath is not None:
        savefig(fig, fpath)

    return fig


# pylint:disable=unsubscriptable-object
def plot_data(train_data, out_dir, flags, thermalize=False, params=None):
    out_dir = os.path.join(out_dir, 'plots')
    io.check_else_make_dir(out_dir)

    title = None if params is None else get_title_str_from_params(params)

    logging_steps = flags.get('logging_steps', 1)
    flags_file = os.path.join(out_dir, 'FLAGS.z')
    if os.path.isfile(flags_file):
        train_flags = io.loadz(flags_file)
        logging_steps = train_flags.get('logging_steps', 1)

    #  logging_steps = flags.logging_steps if 'training' in out_dir else 1

    data_dict = {}
    for key, val in train_data.data.items():
        if key == 'x':
            continue

        arr = np.array(val)
        steps = logging_steps * np.arange(len(np.array(val)))

        if thermalize or key == 'dt':
            arr, steps = therm_arr(arr, therm_frac=0.33)
            steps *= logging_steps

        labels = ('MC Step', key)
        data = (steps, arr)

        if len(arr.shape) == 1:
            lplot_fname = os.path.join(out_dir, f'{key}.png')
            _, _ = mcmc_lineplot(data, labels, title,
                                 lplot_fname, show_avg=True)

        elif len(arr.shape) > 1:
            data_dict[key] = data
            chains = np.arange(arr.shape[1])
            data_arr = xr.DataArray(arr.T,
                                    dims=['chain', 'draw'],
                                    coords=[chains, steps])

            tplot_fname = os.path.join(out_dir, f'{key}_traceplot.png')
            _ = mcmc_traceplot(key, data_arr, title, tplot_fname)

        plt.close('all')

    mcmc_avg_lineplots(data_dict, title, out_dir)
    plot_charges(*data_dict['charges'], out_dir=out_dir, title=title)

    plt.close('all')