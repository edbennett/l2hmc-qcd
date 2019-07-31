"""
runner.py

Implements GaugeModelRunner class responsible for running the L2HMC algorithm
on a U(1) gauge model.

Author: Sam Foreman (github: @saforem2)
Date: 04/09/2019
"""
import os
import time
import pickle
from scipy.stats import sem
from collections import Counter, OrderedDict

import numpy as np

import utils.file_io as io
from lattice.lattice import u1_plaq_exact
from variables import RUN_HEADER

#  ops = [                         # list of tensorflow operations to run
#      self.model.x_out,           # new samples (MD + MH accept/reject)
#      self.model.px,              # prob. of accepting proposed samples
#      self.model.actions_op,      # tot. action of each sample
#      self.model.plaqs_op,        # avg. plaquette of each sample
#      self.model.charges_op,      # topological charge Q, of each sample
#      self.model.charge_diffs_op  # Q(x_out) - Q(samples_in)
#  ]


class GaugeModelRunner:

    def __init__(self, sess, params, inputs, run_ops, logger=None):
        """
        Args:
            sess: tf.Session() object.
            model: GaugeModel object (defined in `models/gauge_model.py`)
            logger: RunLogger object (defined in `loggers/run_logger.py`),
                defaults to None. This is to simplify communication when using
                Horovod since the RunLogger object exists only on
                hvd.rank() == 0, which is responsible for all file I/O.
        """
        self.sess = sess
        self.params = params
        self.logger = logger
        self.run_ops_dict = self.build_run_ops_dict(params, run_ops)
        self.inputs_dict = self.build_inputs_dict(inputs)
        self.eps = self.sess.run(self.run_ops_dict['dynamics_eps'])
        #  self.eps = self.sess.run(self.model.dynamics.eps)

    def build_run_ops_dict(self, params, run_ops):
        """Build dictionary of tensorflow operations used for inference."""
        run_ops_dict = {
            'x_out': run_ops[0],
            'px': run_ops[1],
            'actions_op': run_ops[2],
            'plaqs_op': run_ops[3],
            'avg_plaqs_op': run_ops[4],
            'charges_op': run_ops[5],
            'charge_diffs_op': run_ops[6]
        }

        if params['save_lf']:
            run_ops_dict.update({
                'lf_out_f': run_ops[7],
                'pxs_out_f': run_ops[8],
                'masks_f': run_ops[9],
                'logdets_f': run_ops[10],
                'sumlogdet_f': run_ops[11],
                'lf_out_b': run_ops[12],
                'pxs_out_b': run_ops[13],
                'masks_b': run_ops[14],
                'logdets_b': run_ops[15],
                'sumlogdet_b': run_ops[16],
            })

        run_ops_dict['dynamics_eps'] = run_ops[-1]

        return run_ops_dict

    def build_inputs_dict(self, inputs):
        """Build dictionary of tensorflow placeholders used as inputs."""
        inputs_dict = {
            'x': inputs[0],
            'beta': inputs[1],
            'charge_weight': inputs[2],
            'train_phase': inputs[3],
            'net_weights': [inputs[4], inputs[5], inputs[6]]
        }

        return inputs_dict

    def calc_charge_autocorrelation(self, charges):
        autocorr = np.correlate(charges, charges, mode='full')
        return autocorr

    def save_run_data(self, run_data, run_strings, samples, **kwargs):
        """Save run information.

        Args:
            run_data: All run data generated from `run` method.
            run_strings: list of all strings generated from `run` method.
            samples: Optional collection of all samples generated from `run`
            method. Only relevant if model.sve_samples is True
        """
        run_dir = kwargs['run_dir']
        observables_dir = os.path.join(run_dir, 'observables')

        io.check_else_make_dir(run_dir)
        io.check_else_make_dir(observables_dir)

        save_samples = self.params.get('save_samples', False)
        #  if self.model.save_samples:
        if save_samples:
            samples_file = os.path.join(run_dir, 'run_samples.pkl')
            io.log(f"Saving samples to: {samples_file}.")
            with open(samples_file, 'wb') as f:
                pickle.dump(samples, f)

        run_stats = self.calc_observables_stats(run_data,
                                                kwargs['therm_frac'])

        data_file = os.path.join(run_dir, 'run_data.pkl')
        io.log(f"Saving run_data to: {data_file}.")
        with open(data_file, 'wb') as f:
            pickle.dump(run_data, f)

        stats_data_file = os.path.join(run_dir, 'run_stats.pkl')
        io.log(f"Saving run_stats to: {stats_data_file}.")
        with open(stats_data_file, 'wb') as f:
            pickle.dump(run_stats, f)

        for key, val in run_data.items():
            out_file = key + '.pkl'
            out_file = os.path.join(observables_dir, out_file)
            io.save_data(val, out_file, name=key)

        for key, val in run_stats.items():
            out_file = key + '_stats.pkl'
            out_file = os.path.join(observables_dir, out_file)
            io.save_data(val, out_file, name=key)

        history_file = os.path.join(run_dir, 'run_history.txt')
        _ = [io.write(s, history_file, 'a') for s in run_strings]

        self.write_run_stats(run_stats, **kwargs)

    def run_step(self, step, run_steps, inputs, net_weights):
        """Perform a single run step.

        Args:
            step (int): Current step.
            run_steps (int): Total number of run_steps to perform.
            inputs (tuple): Tuple consisting of (samples_in, beta_np, eps,
                plaq_exact) where samples_in (np.ndarray) is the input batch of
                samples, beta (float)is the input value of beta, eps is the
                step size, and plaq_exact (float) is the expected avg. value of
                the plaquette at this value of beta.
        Returns:
            out_data: Dictionary containing the output of running all of the
            tensorflow operations in `ops` defined below.
        """
        samples_in, beta_np, eps, plaq_exact = inputs

        #  ops = [
        #      self.model.x_out,
        #      self.model.px,
        #      self.model.actions_op,
        #      self.model.plaqs_op,
        #      self.model.charges_op,
        #      self.model.charge_diffs_op,
        #  ]
        ops = [
            self.run_ops_dict['x_out'],
            self.run_ops_dict['px'],
            self.run_ops_dict['actions_op'],
            self.run_ops_dict['plaqs_op'],
            self.run_ops_dict['charges_op'],
            self.run_ops_dict['charge_diffs_op']
        ]

        #  if self.model.save_lf:
        if self.params['save_lf']:
            ops.extend([
                self.run_ops_dict['lf_out_f'],
                self.run_ops_dict['pxs_out_f'],
                self.run_ops_dict['lf_out_b'],
                self.run_ops_dict['pxs_out_b'],
                self.run_ops_dict['masks_f'],
                self.run_ops_dict['masks_b'],
                self.run_ops_dict['logdets_f'],
                self.run_ops_dict['logdets_b'],
                self.run_ops_dict['sumlogdet_f'],
                self.run_ops_dict['sumlogdet_b']
            ])

        #  feed_dict = {
        #      self.model.x: samples_in,
        #      self.model.beta: beta_np,
        #      self.model.net_weights[0]: net_weights[0],
        #      self.model.net_weights[1]: net_weights[1],
        #      self.model.net_weights[2]: net_weights[2],
        #      self.model.train_phase: False
        #  }

        feed_dict = {
            self.inputs_dict['x']: samples_in,
            self.inputs_dict['beta']: beta_np,
            self.inputs_dict['net_weights'][0]: net_weights[0],
            self.inputs_dict['net_weights'][1]: net_weights[1],
            self.inputs_dict['net_weights'][2]: net_weights[2],
            self.inputs_dict['train_phase']: False
        }

        start_time = time.time()
        outputs = self.sess.run(ops, feed_dict=feed_dict)
        dt = time.time() - start_time
        out_data = {
            'step': step,
            'beta': beta_np,
            'eps': self.eps,
            'samples': np.mod(outputs[0], 2 * np.pi),
            'px': outputs[1],
            'actions': outputs[2],
            'plaqs': outputs[3],
            'charges': outputs[4],
            'charge_diffs': outputs[5],
        }
        #  if self.model.save_lf:
        if self.params['save_lf']:
            lf_outputs = {
                'lf_out_f': outputs[6],
                'pxs_out_f': outputs[7],
                'lf_out_b': outputs[8],
                'pxs_out_b': outputs[9],
                'masks_f': outputs[10],
                'masks_b': outputs[11],
                'logdets_f': outputs[12],
                'logdets_b': outputs[13],
                'sumlogdet_f': outputs[14],
                'sumlogdet_b': outputs[15],
            }
            out_data.update(lf_outputs)

        data_str = (f'{step:>5g}/{run_steps:<6g} '
                    f'{dt:^9.4g} '                      # time / step
                    f'{np.mean(outputs[1]):^9.4g} '     # accept. prob
                    f'{self.eps:^9.4g} '                # step size
                    f'{beta_np:^9.4g} '                 # beta val
                    f'{np.mean(outputs[2]):^9.4g} '     # avg. actions
                    f'{np.mean(outputs[3]):^9.4g} '     # avg. plaquettes
                    f'{plaq_exact:^9.4g} '              # exact plaquette val
                    f'{outputs[5]:^9.4g} ')             # top. charge diff

        return out_data, data_str

    def run(self, run_steps, **kwargs):
        """Run the simulation to generate samples and calculate observables.

        Args:
            run_steps: Number of steps to run the sampler for.
            current_step: Integer passed when the sampler is ran intermittently
                during training, as a way to monitor the models performance
                during training. By passing the current training step as
                current_step, this data is saved to a unique directory labeled
                by the current_step.
            beta: Float value indicating the inverse coupling constant that the
                sampler is to be run at.

        Returns:
            observables: Tuple of observables dictionaries consisting of:
                (actions_dict, plaqs_dict, charges_dict, charge_diffs_dict).
        """
        run_steps = int(run_steps)

        beta = kwargs.get('beta_final', self.params.get('beta_final', 5))
        net_weights = kwargs.get('net_weights', [1., 1., 1.])
        therm_frac = kwargs.get('therm_frac', 10)

        if beta is None:
            beta = self.params['beta_final']
            #  beta = self.model.beta_final

        if net_weights is None:
            # scale_weight, transformation_weight, translation_weight
            net_weights = [1., 1., 1.]

        plaq_exact = u1_plaq_exact(beta)

        # start with randomly generated samples
        #  samples_np = np.random.randn(*(self.model.batch_size,
        #                                 self.model.x_dim))
        x_dim = (self.params['space_size']
                 * self.params['time_size']
                 * self.params['dim'])

        samples_np = np.random.randn(*(self.params['num_samples'], x_dim))

        try:
            io.log(RUN_HEADER)
            for step in range(run_steps):
                inputs = (samples_np, beta, self.eps, plaq_exact)
                out_data, data_str = self.run_step(step, run_steps,
                                                   inputs, net_weights)
                samples_np = out_data['samples']

                if self.logger is not None:
                    self.logger.update(self.sess, out_data,
                                       net_weights, data_str)

            if self.logger is not None:
                self.logger.save_run_data(therm_frac=therm_frac)

        except (KeyboardInterrupt, SystemExit):
            io.log("\nKeyboardInterrupt detected!")
            io.log("Saving current state and exiting.")
            if self.logger is not None:
                self.logger.save_run_data(therm_frac=therm_frac)

    def calc_observables_stats(self, run_data, therm_frac=10):
        """Calculate statistics for lattice observables.

        Args:
            run_data: Dictionary of observables data. Keys denote the
                observables name.
            therm_frac: Fraction of data to throw out for thermalization.

        Returns:
            stats: Dictionary containing statistics for each observable in
            run_data. Additionally, contains `charge_probs` which is a
            dictionary of the form {charge_val: charge_val_probability}.
        """
        def get_stats(data, t_frac=10):
            if isinstance(data, dict):
                arr = np.array(list(data.values()))
            elif isinstance(data, (list, np.ndarray)):
                arr = np.array(data)

            num_steps = arr.shape[0]
            therm_steps = num_steps // t_frac
            arr = arr[therm_steps:, :]
            avg = np.mean(arr, axis=0)
            err = sem(arr, axis=0)
            stats = np.array([avg, err]).T
            return stats

        actions_stats = get_stats(run_data['actions'], therm_frac)
        plaqs_stats = get_stats(run_data['plaqs'], therm_frac)

        charges_arr = np.array(list(run_data['charges'].values()), dtype=int)
        charges_stats = get_stats(charges_arr, therm_frac)

        suscept_arr = charges_arr ** 2
        suscept_stats = get_stats(suscept_arr)

        charge_probs = {}
        counts = Counter(list(charges_arr.flatten()))
        total_counts = np.sum(list(counts.values()))
        for key, val in counts.items():
            charge_probs[key] = val / total_counts

        charge_probs = OrderedDict(sorted(charge_probs.items(),
                                          key=lambda k: k[0]))

        stats = {
            'actions': actions_stats,
            'plaqs': plaqs_stats,
            'charges': charges_stats,
            'suscept': suscept_stats,
            'charge_probs': charge_probs
        }

        return stats

    def write_run_stats(self, stats, **kwargs):
        """Write statistics in human readable format to .txt file."""
        run_steps = kwargs['run_steps']
        beta = kwargs['beta']
        current_step = kwargs['current_step']
        therm_steps = kwargs['therm_steps']
        training = kwargs['training']
        run_dir = kwargs['run_dir']

        out_file = os.path.join(run_dir, 'run_stats.txt')

        actions_avg, actions_err = stats['actions'].mean(axis=0)
        plaqs_avg, plaqs_err = stats['plaqs'].mean(axis=0)
        charges_avg, charges_err = stats['charges'].mean(axis=0)
        suscept_avg, suscept_err = stats['suscept'].mean(axis=0)

        #  actions_arr = np.array(
        #      list(run_data['actions'].values())
        #  )[therm_steps:, :]
        #
        #  plaqs_arr = np.array(
        #      list(run_data['plaqs'].values())
        #  )[therm_steps:, :]
        #
        #  charges_arr = np.array(
        #      list(run_data['charges'].values()),
        #      dtype=np.int32
        #  )[therm_steps:, :]
        #
        #  charges_squared_arr = charges_arr ** 2
        #
        #  actions_err = sem(actions_arr, axis=None)
        #
        #  plaqs_avg = np.mean(plaqs_arr)
        #  plaqs_err = sem(plaqs_arr, axis=None)
        #
        #  q_avg = np.mean(charges_arr)
        #  q_err = sem(charges_arr, axis=None)
        #
        #  q2_avg = np.mean(charges_squared_arr)
        #  q2_err = sem(charges_squared_arr, axis=None)

        ns = self.params['num_samples']
        #  ns = self.model.num_samples
        suscept_k1 = f'  \navg. over all {ns} samples < Q >'
        suscept_k2 = f'  \navg. over all {ns} samples < Q^2 >'
        actions_k1 = f'  \navg. over all {ns} samples < action >'
        plaqs_k1 = f'  \n avg. over all {ns} samples < plaq >'

        _est_key = '  \nestimate +/- stderr'

        suscept_ss = {
            suscept_k1: f"{charges_avg:.4g} +/- {charges_err:.4g}",
            suscept_k2: f"{suscept_avg:.4g} +/- {suscept_err:.4g}",
            _est_key: {}
        }

        actions_ss = {
            actions_k1: f"{actions_avg:.4g} +/- {actions_err:.4g}\n",
            _est_key: {}
        }

        plaqs_ss = {
            'exact_plaq': f"{u1_plaq_exact(beta):.4g}\n",
            plaqs_k1: f"{plaqs_avg:.4g} +/- {plaqs_err:.4g}\n",
            _est_key: {}
        }

        def format_stats(x, name=None):
            return [f'{name}: {i[0]:.4g} +/- {i[1]:.4g}' for i in x]

        def zip_keys_vals(stats_strings, keys, vals):
            for k, v in zip(keys, vals):
                stats_strings[_est_key][k] = v
            return stats_strings

        keys = [f"sample {idx}" for idx in range(ns)]

        suscept_vals = format_stats(stats['suscept'], '< Q^2 >')
        actions_vals = format_stats(stats['actions'], '< action >')
        plaqs_vals = format_stats(stats['plaqs'], '< plaq >')

        suscept_ss = zip_keys_vals(suscept_ss, keys, suscept_vals)
        actions_ss = zip_keys_vals(actions_ss, keys, actions_vals)
        plaqs_ss = zip_keys_vals(plaqs_ss, keys, plaqs_vals)

        def accumulate_strings(d):
            all_strings = []
            for k1, v1 in d.items():
                if isinstance(v1, dict):
                    for k2, v2 in v1.items():
                        all_strings.append(f'{k2} {v2}')
                else:
                    all_strings.append(f'{k1}: {v1}\n')

            return all_strings

        actions_strings = accumulate_strings(actions_ss)
        plaqs_strings = accumulate_strings(plaqs_ss)
        suscept_strings = accumulate_strings(suscept_ss)

        charge_probs_strings = []
        for k, v in stats['charge_probs'].items():
            charge_probs_strings.append(f'  probability[Q = {k}]: {v}\n')

        train_str = (f" stats after {current_step} training steps.\n"
                     f"{ns} chains ran for {run_steps} steps at "
                     f"beta = {beta}.")

        run_str = (f" stats for {ns} chains ran for {run_steps} steps "
                   f" at beta = {beta}.")

        if training:
            str0 = "Topological susceptibility" + train_str
            str1 = "Total actions" + train_str
            str2 = "Average plaquette" + train_str
            str3 = "Topological charge probabilities" + train_str[6:]
            therm_str = ''
        else:
            str0 = "Topological susceptibility" + run_str
            str1 = "Total actions" + run_str
            str2 = "Average plaquette" + run_str
            str3 = "Topological charge probabilities" + run_str[6:]
            therm_str = (
                f'Ignoring first {therm_steps} steps for thermalization.'
            )

        ss0 = (1 + max(len(str0), len(therm_str))) * '-'
        ss1 = (1 + max(len(str1), len(therm_str))) * '-'
        ss2 = (1 + max(len(str2), len(therm_str))) * '-'
        ss3 = (1 + max(len(str3), len(therm_str))) * '-'

        io.log(f"Writing statistics to: {out_file}")

        def log_and_write(sep_str, str0, therm_str, stats_strings, file):
            io.log(sep_str)
            io.log(str0)
            io.log(therm_str)
            io.log('')
            _ = [io.log(s) for s in stats_strings]
            io.log(sep_str)
            io.log('')

            io.write(sep_str, file, 'a')
            io.write(str0, file, 'a')
            io.write(therm_str, file, 'a')
            _ = [io.write(s, file, 'a') for s in stats_strings]
            io.write('\n', file, 'a')

        log_and_write(ss0, str0, therm_str, suscept_strings, out_file)
        log_and_write(ss1, str1, therm_str, actions_strings, out_file)
        log_and_write(ss2, str2, therm_str, plaqs_strings, out_file)
        log_and_write(ss3, str3, therm_str, charge_probs_strings, out_file)