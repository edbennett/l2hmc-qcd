import os
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

import pickle
import numpy as np
try:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

#  from .formatters import latexify
import utils.file_io as io
from utils.data_loader import DataLoader


def load_and_sep(out_file, keys=('forward', 'backward')):
    with open(out_file, 'rb') as f:
        data = pickle.load(f)

    return (np.array(data[k]) for k in keys)


params = {
    #  'backend': 'ps',
    #  'text.latex.preamble': [r'\usepackage{gensymb}'],
    'axes.labelsize': 16,   # fontsize for x and y labels (was 10)
    'axes.titlesize': 16,
    'legend.fontsize': 10,  # was 10
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    #  'text.usetex': True,
    #  'figure.figsize': [fig_width, fig_height],
    'font.family': 'serif'
}

try:
    mpl.rcParams.update(params)
except FileNotFoundError:
    params['text.usetex'] = False
    params['text.latex.preamble'] = None
    try:
        mpl.rcParams.update(params)
    except FileNotFoundError:
        pass


class LeapfrogPlotter:
    def __init__(self, figs_dir, run_logger=None,
                 run_dir=None, therm_perc=0.005, skip_perc=0.01):
        self.figs_dir = figs_dir
        self.pdfs_dir = os.path.join(self.figs_dir, 'pdfs_plots')
        io.check_else_make_dir(self.pdfs_dir)

        if run_logger is None:
            if run_dir is None:
                raise AttributeError(
                    """Either a `run_logger` object containing data or a
                    `run_dir` from which to load data must be specified.
                    Exiting.
                    """
                )
            else:
                try:
                    data = self.load_data(run_dir)
                    self.samples = data[0]
                    self.lf_f, self.lf_b = data[1]
                    self.logdets_f, self.logdets_b = data[2]
                    self.sumlogdet_f, self.sumlogdet_b = data[3]
                except FileNotFoundError:
                    io.log(f'''Unable to load leapfrog data from run_dir:
                           {run_dir}. Exiting.''')
                    return

        else:
            self.samples = np.array(run_logger.samples_arr)
            self.lf_f = np.array(run_logger.lf_out['forward'])
            self.lf_b = np.array(run_logger.lf_out['backward'])
            self.logdets_f = np.array(run_logger.logdets['forward'])
            self.logdets_b = np.array(run_logger.logdets['backward'])
            self.sumlogdet_f = np.array(run_logger.sumlogdet['forward'])
            self.sumlogdet_b = np.array(run_logger.sumlogdet['backward'])

        self.lf_f_diffs = self.lf_f[1:] - self.lf_f[:-1]
        self.lf_b_diffs = self.lf_b[1:] - self.lf_b[:-1]
        self.samples_diffs = self.samples[1:] - self.samples[:-1]
        self.tot_lf_steps = self.lf_f_diffs.shape[0]
        self.tot_md_steps = self.samples_diffs.shape[0]
        self.num_lf_steps = self.tot_lf_steps // self.tot_md_steps
        #  self.therm_steps = int(therm_perc * self.tot_lf_steps)
        #  self.skip_steps = int(skip_perc * self.tot_lf_steps)
        #  self.step_multiplier = (
        #      self.lf_f_diffs.shape[0] // self.samples_diffs.shape[0]
        #  )

    def load_data(self, run_dir):
        loader = DataLoader(run_dir)
        io.log("Loading samples...")
        samples = loader.load_samples(run_dir)
        io.log('done.')
        io.log("Loading leapfrogs...")
        leapfrogs = loader.load_leapfrogs(run_dir)
        io.log("Loading logdets...")
        logdets = loader.load_logdets(run_dir)
        io.log("Loading sumlogdets...")
        sumlogdets = loader.load_sumlogdets(run_dir)
        return (samples, leapfrogs, logdets, sumlogdets)

    def print_memory(self):
        if HAS_PSUTIL:
            pid = os.getpid()
            py = psutil.Process(pid)
            memory_use = py.memory_info()[0] / 2. ** 30
            io.log(80 * '-')
            io.log(f'memory use: {memory_use}')
            io.log(80 * '-')

    def get_colors(self, num_samples=20):
        reds_cmap = mpl.cm.get_cmap('Reds', num_samples + 1)
        blues_cmap = mpl.cm.get_cmap('Blues', num_samples + 1)
        idxs = np.linspace(0.2, 0.75, num_samples + 1)
        reds = [reds_cmap(i) for i in idxs]
        blues = [blues_cmap(i) for i in idxs]

        return reds, blues

    def save_attr(self, name, attr, out_dir):
        assert os.path.isdir(out_dir)
        out_file = os.path.join(out_dir, name + '.npz')

        if os.path.isfile(out_file):
            io.log(f'File {out_file} already exists. Skipping.')
        else:
            io.log(f'Saving {name} to: {out_file}')
            np.savez_compressed(out_file, attr)

    def update_figs_dir(self, figs_dir):
        self.figs_dir = figs_dir
        self.pdfs_dir = os.path.join(self.figs_dir, 'pdfs')

        io.check_else_make_dir(figs_dir)
        io.check_else_make_dir(self.pdfs_dir)

    def make_plots(self, run_dir, num_samples=20, save=True, ret=False):
        """Make plots of the leapfrog differences and logdets.

        Immediately after creating and saving the plots, delete these
        (no-longer needed) attributes to free up memory.

        Args:
            run_dir (str): Path to directory in which to save all of the
                relevant instance attributes.
            num_samples (int): Number of samples to include when creating
                plots.
            save (bool): Boolean indicating whether or not plotted data should
                be saved.

        NOTE:
            `save` is very data intensive and will produce LARGE (compressed)
            `.npz` files.
        """
        run_key = run_dir.split('/')[-1].split('_')
        beta_idx = run_key.index('beta') + 1
        beta = run_key[beta_idx]

        self.print_memory()
        fig_ax1 = self.plot_lf_diffs(beta, num_samples)

        self.print_memory()
        fig_ax2 = self.plot_logdets(beta, num_samples)

        if save:
            self.save_attr('lf_forward', self.lf_f, out_dir=run_dir)
            self.save_attr('lf_backward', self.lf_b, out_dir=run_dir)
            self.save_attr('samples_out', self.samples, out_dir=run_dir)

            self.save_attr('logdets_forward', self.logdets_f, out_dir=run_dir)
            self.save_attr('logdets_backward', self.logdets_b, out_dir=run_dir)

            self.save_attr('sumlogdet_forward',
                           self.sumlogdet_f, out_dir=run_dir)
            self.save_attr('sumlogdet_backward',
                           self.sumlogdet_b, out_dir=run_dir)
        if ret:
            return fig_ax1, fig_ax2

    def plot_lf_diffs(self, beta, num_samples=20):
        reds, blues = self.get_colors(num_samples)
        samples_y_avg = np.mean(self.samples_diffs, axis=(1, 2))
        samples_x_avg = np.arange(len(samples_y_avg))

        indiv_kwargs = {
            'ls': '-',
            'alpha': 0.9,
            'lw': 0.5
        }

        fig, (ax1, ax2) = plt.subplots(2, 1)
        for idx in range(num_samples):
            yf = np.mean(self.lf_f_diffs, axis=-1)
            try:
                xf = np.arange(len(yf))
            except:
                import pdb
                pdb.set_trace()
            yb = np.mean(self.lf_b_diffs, axis=-1)
            xb = np.arange(len(yb))

            _ = ax1.plot(xf, yf[:, idx], color=reds[idx], **indiv_kwargs)
            _ = ax1.plot(xb, yb[:, idx], color=blues[idx], **indiv_kwargs)

        yf_avg = np.mean(self.lf_f_diffs, axis=(1, 2))
        yb_avg = np.mean(self.lf_b_diffs, axis=(1, 2))
        xf_avg = np.arange(len(yf))
        xb_avg = np.arange(len(yb))

        _ = ax1.plot(xf_avg, yf_avg, label='forward', color='r', lw=1.)
        _ = ax1.plot(xb_avg, yb_avg, label='backward', color='b', lw=1.)

        _ = ax2.plot(samples_x_avg, samples_y_avg, color='k', lw=1.,
                     label='MD avg.')

        _ = ax1.set_xlabel('Leapfrog step', fontsize=16)
        _ = ax2.set_xlabel('MD step', fontsize=16)

        ylabel = r'$\langle \delta\phi_{\mu}(i)\rangle$'
        _ = ax1.set_ylabel(ylabel, fontsize=16)
        _ = ax2.set_ylabel(ylabel, fontsize=16)

        _ = ax1.legend(loc='best', fontsize=10)
        _ = ax2.legend(loc='best', fontsize=10)
        fig.tight_layout()
        #  fig.subplots_adjust(hspace=0.5)

        out_file = os.path.join(self.pdfs_dir,
                                f'leapfrog_diffs_beta{beta}.pdf')
        out_file_zoom = os.path.join(self.pdfs_dir,
                                     f'leapfrog_diffs_beta{beta}_zoom.pdf')
        io.log(f'Saving figure to: {out_file}')
        _ = plt.savefig(out_file, dpi=400, bbox_inches='tight')

        lf_xlim = 100
        md_xlim = lf_xlim // self.num_lf_steps

        _ = ax1.set_xlim((0, lf_xlim))
        _ = ax2.set_xlim((0, md_xlim))
        _ = plt.savefig(out_file_zoom, dpi=400, bbox_inches='tight')

        #  _ = plt.close('all')
        return fig, (ax1, ax2)

    def plot_logdets(self, beta, num_samples=20):
        reds, blues = self.get_colors(num_samples)

        sumlogdet_yf_avg = np.mean(self.sumlogdet_f, axis=-1)
        sumlogdet_yb_avg = np.mean(self.sumlogdet_b, axis=-1)
        sumlogdet_xf_avg = np.arange(len(sumlogdet_yf_avg))
        sumlogdet_xb_avg = np.arange(len(sumlogdet_yb_avg))

        fig, (ax1, ax2) = plt.subplots(2, 1)
        for idx in range(num_samples):
            yf = self.logdets_f[:, idx]
            xf = np.arange(len(yf))
            yb = self.logdets_b[:, idx]
            xb = np.arange(len(yb))

            _ = ax1.plot(xf, yf, color=reds[idx], alpha=0.9, lw=0.5)
            _ = ax1.plot(xb, yb, color=blues[idx], alpha=0.9, lw=0.5)

        yf_avg = np.mean(self.logdets_f, axis=-1)
        yb_avg = np.mean(self.logdets_b, axis=-1)

        xf_avg = np.arange(len(yf_avg))
        xb_avg = np.arange(len(yb_avg))

        _ = ax1.plot(xf_avg, yf_avg, label='forward',
                     alpha=0.9, ls='-', color='r', lw=1.)
        _ = ax1.plot(xb_avg, yb_avg, label='backward',
                     alpha=0.9, ls='-', color='b', lw=1.)

        _ = ax2.plot(sumlogdet_xf_avg, sumlogdet_yf_avg, label='forward',
                     alpha=0.9, color='r', lw=1., ls='-')

        _ = ax2.plot(sumlogdet_xb_avg, sumlogdet_yb_avg, label='backward',
                     alpha=0.9, color='b', lw=1., ls='-')

        _ = ax1.set_xlabel('Leapfrog step', fontsize=16)
        _ = ax1.set_ylabel(r'$\mathcal{J}^{(t)}$', fontsize=16)
        _ = ax2.set_xlabel('MD step', fontsize=16)
        _ = ax2.set_ylabel(r'$\mathcal{J}$', fontsize=16)
        _ = ax1.legend(loc='best', fontsize=10)
        _ = ax2.legend(loc='best', fontsize=10)
        _ = fig.tight_layout()
        #  _ = fig.subplots_adjust(hspace=0.5)

        #  out_file = os.path.join(self.figs_dir,
        #                          f'avg_logdets_beta{beta}.png')
        out_file = os.path.join(self.pdfs_dir,
                                f'avg_logdets_beta{beta}.pdf')
        out_file_zoom = os.path.join(self.pdfs_dir,
                                     f'avg_logdets_beta{beta}_zoom.pdf')
        io.log(f'Saving figure to: {out_file}')
        _ = plt.savefig(out_file, dpi=400, bbox_inches='tight')

        lf_xlim = 100
        md_xlim = lf_xlim // self.num_lf_steps

        _ = ax1.set_xlim((0, lf_xlim))
        _ = ax2.set_xlim((0, md_xlim))
        _ = plt.savefig(out_file_zoom, dpi=400, bbox_inches='tight')
        #  _ = plt.close('all')
        return fig, (ax1, ax2)