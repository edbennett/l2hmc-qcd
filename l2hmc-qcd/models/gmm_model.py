"""
gmm_model.py

Implements the GaussianMixtureModel class responsible for building the
computation graph used in tensorflow.

Author: Sam Foreman (github: @saforem2)
Date: 09/03/2019
"""
from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import time

import numpy as np
import tensorflow as tf

import utils.file_io as io

from collections import namedtuple
from utils.horovod_utils import warmup_lr  # noqa: 401
from utils.distributions import GMM, gen_ring
from base.base_model import BaseModel
from .gauge_model import allclose
from dynamics.dynamics import Dynamics
from .params import GMM_PARAMS
from config import GLOBAL_SEED, TF_FLOAT, NP_FLOAT, HAS_HOROVOD

if HAS_HOROVOD:
    import horovod.tensorflow as hvd  # noqa: 401

LFdata = namedtuple('LFdata', ['init', 'proposed', 'prob'])


def distribution_arr(x_dim, num_distributions):
    """Create array describing likelihood of drawing from distributions."""
    if num_distributions > x_dim:
        pis = [1. / num_distributions] * num_distributions
        pis[0] += 1 - sum(pis)
    if x_dim == num_distributions:
        big_pi = round(1.0 / num_distributions, x_dim)
        pis = num_distributions * [big_pi]
    else:
        big_pi = (1.0 / num_distributions) - x_dim * 1e-16
        pis = num_distributions * [big_pi]
        small_pi = (1. - sum(pis)) / (x_dim - num_distributions)
        pis.extend((x_dim - num_distributions) * [small_pi])

    return np.array(pis, dtype=NP_FLOAT)


def ring_of_gaussians(num_modes, sigma, x_dim=2, radius=1.):
    """Create ring of Gaussians for GaussianMixtureModel. 

    Args:
        num_modes (int): Number of modes for distribution.
        sigma (float): Standard deviation of each mode.
        x_dim (int): Spatial dimensionality in which the distribution exists.
        radius (float): Radius from the origin along which the modes are
            located.

    Returns:
        distribution (GMM object): Gaussian mixture distribution.
        mus (np.ndarray): Array of the means of the distribution.
        covs (np.array): Covariance matrices.
        distances (np.ndarray): Array of the differences between different
            modes. 
    """
    covs, distribution = gen_ring(r=1., var=sigma, nb_mixtures=num_modes)
    mus = np.array(distribution.mus)
    diffs = mus[1:] - mus[:-1, :]
    distances = [np.sqrt(np.dot(d, d.T)) for d in diffs]

    return distribution, mus, covs, distances


def lattice_of_gaussians(num_modes, sigma, x_dim=2, size=None):
    """Create lattice of Gaussians for GaussianMixtureModel.

    Args:
        num_modes (int): Number of modes for distribution.
        sigma (float): Standard deviation of each mode.
        x_dim (int): Spatial dimensionality in which the distribution exists.
        size (int): Spatial extent of lattice.

    Returns:
        distribution (GMM object): Gaussian mixture distribution.
        covs (np.array): Covariance matrices.
        mus (np.ndarray): Array of the means of the distribution.
        pis (np.ndarray): Array of relative probabilities for each mode. Must
            sum to 1.
    """
    if size is None:
        size = int(np.sqrt(num_modes))

    mus = np.array([(i, j) for i in range(size) for j in range(size)])
    covs = np.array([sigma * np.eye(x_dim) for _ in range(num_modes)])
    pis = [1. / num_modes] * num_modes
    pis[0] += 1. - sum(pis)

    distribution = GMM(mus, covs, pis)

    return distribution, mus, covs, pis


class GaussianMixtureModel(BaseModel):
    def __init__(self, params=None):
        super(GaussianMixtureModel, self).__init__(params)
        self._model_type = 'GaussianMixtureModel'

        if params is None:
            params = GMM_PARAMS  # default parameters, defined in `config.py`.

        self.params = params
        for key, val in self.params.items():
            setattr(self, key, val)

        sigma1 = params.get('sigma1', 0.05)
        sigma2 = params.get('sigma2', 0.05)
        self.sigmas = (sigma1, sigma2)
        #  self.sigma = params.get('sigma', 0.05)
        self.eps_trainable = not self.eps_fixed
        self.num_distributions = params.get('num_distributions', 2)

        self.build()

    def build(self):
        """Build TensorFlow graph."""
        t0 = time.time()
        io.log(80 * '-')
        io.log(f'INFO: Building graph for `GaugeModel`...')
        with tf.name_scope('init'):
            # ***************************************************************
            # Create distribution defining Gaussian Mixture Model
            # ---------------------------------------------------------------
            means, covs, dist_arr, distribution = self._create_distribution(
                self.sigmas, means=None
            )
            self.means = means
            self.covs = covs
            self.dist_arr = dist_arr
            self.distribution = distribution

            self.samples_init = self.distribution.get_samples(self.num_samples)
            # ***************************************************************

            # ***********************************************
            # Create inputs as `tf.placeholders`
            # -----------------------------------------------
            io.log(f'INFO: Creating input placeholders...')
            self.inputs = self._create_inputs()
            self.x = self.inputs.x
            self.beta = self.inputs.beta
            self.net_weights = self.inputs.net_weights
            self.train_phase = self.inputs.train_phase
            # ***********************************************

            # ***********************************************
            # Create dynamics for running L2HMC leapfrog
            # -----------------------------------------------
            io.log(f'INFO: Creating `Dynamics`...')
            self.dynamics = self._create_dynamics()

            # ***************************************************************
            # Create metric function for measuring 'distance' between configs
            # ---------------------------------------------------------------
            self.metric_fn = self._create_metric_fn()

        # *******************************************************************
        # Run dynamics (i.e. augmented leapfrog) to generate new configs 
        # -------------------------------------------------------------------
        with tf.name_scope('l2hmc'):
            with tf.name_scope('main_dynamics'):
                x_dynamics = self._apply_transition(self.x, self.beta,
                                                    self.net_weights,
                                                    self.train_phase,
                                                    save_lf=self.save_lf)
            if getattr(self, 'aux_weight', 1.) > 0:
                with tf.name_scope('auxiliary_dynamics'):
                    self.z = tf.random_normal(tf.shape(self.x),
                                              dtype=TF_FLOAT,
                                              seed=GLOBAL_SEED,
                                              name='z')
                    z_dynamics = self._apply_transition(self.z, self.beta,
                                                        self.net_weights,
                                                        self.train_phase,
                                                        save_lf=False)

            self.x_out = x_dynamics['x_out']
            self.px = x_dynamics['accept_prob']
            self._parse_dynamics_output(x_dynamics)

            with tf.name_scope('check_reversibility'):
                self.x_allclose, self.v_allclose = self._check_reversibility()

        with tf.name_scope('run_ops'):
            io.log(f'INFO: Building `run_ops`...')
            run_ops = self._build_run_ops()
        # *******************************************************************

        # *******************************************************************
        # Calculate loss_op and train_op to backprop. grads through network
        # -------------------------------------------------------------------
        if not self.hmc:
            with tf.name_scope('loss'):
                io.log(f'INFO: Calculating loss function...')
                x_data = LFdata(x_dynamics['x_in'],
                                x_dynamics['x_proposed'],
                                x_dynamics['accept_prob'])
                z_data = LFdata(z_dynamics['x_in'],
                                z_dynamics['x_proposed'],
                                z_dynamics['accept_prob'])

                use_gaussian_loss = getattr(self, 'use_gaussian_loss', False)
                if use_gaussian_loss:
                    self.loss_op = self.gaussian_loss(x_data, z_data)
                else:
                    self.loss_op = self.calc_loss(x_data, z_data)

            with tf.name_scope('train'):
                io.log(f'INFO: Calculating gradients for backpropagation...')
                self.grads = self._calc_grads(self.loss_op)
                self.train_op = self._apply_grads(self.loss_op, self.grads)

        train_ops = self._build_train_ops()

        self.ops_dict = {
            'run_ops': run_ops,
            'train_ops': train_ops
        }

        # Make `run_ops` and `train_ops` collections w/ their respective ops.
        for key, val in self.ops_dict.items():
            for op in list(val.values()):
                tf.add_to_collection(key, op)

        io.log(f'INFO: Done building graph. Took: {time.time() - t0}s')
        io.log(80 * '-')
        # *******************************************************************

    def _apply_transition(self, *args, **kwargs):
        """Call `self.dynamics.apply_transition, using `x` as input."""
        return self.dynamics.apply_transition(*args, **kwargs)

    def _check_reversibility(self):
        x_in = tf.random_normal(self.x.shape,
                                dtype=TF_FLOAT,
                                seed=GLOBAL_SEED,
                                name='x_reverse_check')
        v_in = tf.random_normal(self.x.shape,
                                dtype=TF_FLOAT,
                                seed=GLOBAL_SEED,
                                name='v_reverse_check')

        dynamics_check = self.dynamics._check_reversibility(x_in, v_in,
                                                            self.beta,
                                                            self.net_weights,
                                                            self.train_phase)
        xb = dynamics_check['xb']
        vb = dynamics_check['vb']

        x_allclose = allclose(x_in, xb)  # xb = backward(forward(x_in))
        v_allclose = allclose(v_in, vb)

        return x_allclose, v_allclose

    def _create_distribution(self, sigmas, means=None):
        """Initialize distribution using utils/distributions.py."""
        diag = getattr(self, 'diag', False)

        if means is None:
            if self.centers is None:
                centers = 1.
            else:
                centers = self.centers

            means = np.zeros((self.x_dim, self.x_dim), dtype=NP_FLOAT)
            if diag:
                for i in range(self.x_dim):
                    means[i::self.x_dim, i] = centers
            else:
                means[::2, 0] = centers
                means[1::2, 0] = -centers
        else:
            means = np.array(means).astype(NP_FLOAT)

        if len(sigmas) > 1:
            covs = np.array(
                [s * np.eye(self.x_dim) for s in sigmas]
            ).astype(NP_FLOAT)
        else:
            #  cov_mtx = sigmas * np.eye(self.x_dim).astype(NP_FLOAT)
            covs = np.array(
                [sigmas * np.eye(self.x_dim) for _ in self.x_dim]
            ).astype(NP_FLOAT)
            #  covs = np.array([cov_mtx] * self.x_dim).astype(NP_FLOAT)

        dist_arr = distribution_arr(self.x_dim, self.num_distributions)
        distribution = GMM(means, covs, dist_arr)

        return means, covs, dist_arr, distribution

    def _create_dynamics(self, **params):
        """Create `Dynamics` object."""
        with tf.name_scope('create_dynamics'):
            dynamics_keys = [
                'eps', 'hmc', 'num_steps', 'use_bn',
                'dropout_prob', 'network_arch',
                'num_hidden1', 'num_hidden2'
            ]

            dynamics_params = {
                k: getattr(self, k, None) for k in dynamics_keys
            }

            dynamics_params.update({
                'eps_trainable': not self.eps_fixed,
                'num_filters': 2,
                'x_dim': self.x_dim,
                'batch_size': self.num_samples,
                '_input_shape': (self.num_samples, self.x_dim),
            })

            dynamics_params.update(params)
            potential_fn = self.distribution.get_energy_function()
            dynamics = Dynamics(potential_fn=potential_fn, **dynamics_params)

        return dynamics

    def _create_metric_fn(self):
        """Create metric fn for measuring the distance between two samples."""
        with tf.name_scope('metric_fn'):
            def metric_fn(x1, x2):
                return tf.square(x1 - x2)

        return metric_fn

    def calc_loss(self, x_data, z_data):
        """Calculate the total loss and return operation for calculating it."""
        return self._calc_loss(x_data, z_data)

    def gaussian_loss(self, x_data, z_data):
        """Calculate the Gaussian loss and return op. for calculating it."""
        #  eps = getattr(self, 'eps', 0.2)
        #  md_dist = eps * self.num_steps

        loss = self._gaussian_loss(x_data, z_data, mean=0., sigma=1.)

        return loss


    def _parse_dynamics_output(self, dynamics_output):
        """Parse output dictionary from `self.dynamics.apply_transition."""
        if self.save_lf:
            op_keys = ['masks_f', 'masks_b',
                       'lf_out_f', 'lf_out_b',
                       'pxs_out_f', 'pxs_out_b',
                       'logdets_f', 'logdets_b',
                       'fns_out_f', 'fns_out_b',
                       'sumlogdet_f', 'sumlogdet_b']
            for key in op_keys:
                try:
                    op = dynamics_output[key]
                    setattr(self, key, op)
                except KeyError:
                    continue

        with tf.name_scope('l2hmc_fns'):
            self.l2hmc_fns = {
                'l2hmc_fns_f': self._extract_l2hmc_fns(self.fns_out_f),
                'l2hmc_fns_b': self._extract_l2hmc_fns(self.fns_out_b),
            }

    def _create_inputs(self):
        """Create input paceholders (if not executing eagerly).
        Returns:
            outputs: Dictionary with the following entries:
                x: Placeholder for input lattice configuration with
                    shape = (batch_size, x_dim) where x_dim is the number of
                    links on the lattice and is equal to lattice.time_size *
                    lattice.space_size * lattice.dim.
                beta: Placeholder for inverse coupling constant.
                charge_weight: Placeholder for the charge_weight (i.e. alpha_Q,
                    the multiplicative factor that scales the topological
                    charge term in the modified loss function) .
                net_weights: Array of placeholders, each of which is a
                    multiplicative constant used to scale the effects of the
                    various S, Q, and T functions from the original paper.
                    net_weights[0] = 'scale_weight', multiplies the S fn.
                    net_weights[1] = 'transformation_weight', multiplies the Q
                    fn.  net_weights[2] = 'translation_weight', multiplies the
                    T fn.
                train_phase: Boolean placeholder indicating if the model is
                    curerntly being trained. 
        """
        def scalar_ph(name, dtype=TF_FLOAT):
            return tf.placeholder(dtype=dtype, shape=(), name=name)

        with tf.name_scope('inputs'):
            if not tf.executing_eagerly():
                x = tf.placeholder(dtype=TF_FLOAT,
                                   shape=(self.batch_size, self.x_dim),
                                   name='x')
                beta = scalar_ph('beta')
                train_phase = scalar_ph('is_training', dtype=tf.bool)
                scale_weight = scalar_ph('scale_weight')
                transl_weight = scalar_ph('translation_weight')
                transf_weight = scalar_ph('transformation_weight')
                net_weights = [scale_weight, transl_weight, transf_weight]

            Inputs = namedtuple('Inputs',
                                ['x', 'beta', 'net_weights', 'train_phase'])
            inputs = Inputs(x, beta, net_weights, train_phase)

            return inputs

        return inputs

    def _build_run_ops(self):
        """Build `run_ops` used for running inference w/ trained model."""
        keys = ['x_out', 'px', 'dynamics_eps']
        run_ops = {
            'x_out': self.x_out,
            'px': self.px,
            'dynamics_eps': self.dynamics.eps
        }

        if self.save_lf:
            keys = ['lf_out', 'pxs_out', 'masks',
                    'logdets', 'sumlogdet', 'fns_out']
            fkeys = [k + '_f' for k in keys]
            bkeys = [k + '_b' for k in keys]
            run_ops.update({k: getattr(self, k) for k in fkeys})
            run_ops.update({k: getattr(self, k) for k in bkeys})

        return run_ops

    def _build_train_ops(self):
        """Build `train_ops` used for training our model."""
        if self.hmc:
            train_ops = {}
        else:
            train_ops = {
                'train_op': self.train_op,
                'loss_op': self.loss_op,
                'x_out': self.x_out,
                'px': self.px,
                'dynamics_eps': self.dynamics.eps,
                'lr': self.lr
            }

        return train_ops

    def _extract_l2hmc_fns(self, fns):
        """Method for extracting each of the Q, S, T functions as tensors."""
        if not getattr(self, 'save_lf', True):
            return

        fnsT = tf.transpose(fns, perm=[2, 1, 0, 3, 4], name='fns_transposed')

        fn_names = ['scale', 'translation', 'transformation']
        update_names = ['v1', 'x1', 'x2', 'v2']

        l2hmc_fns = {}
        for idx, name in enumerate(fn_names):
            l2hmc_fns[name] = {}
            for subidx, subname in enumerate(update_names):
                l2hmc_fns[name][subname] = fnsT[idx][subidx]

        return l2hmc_fns
