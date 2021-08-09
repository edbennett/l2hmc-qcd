"""
test.py

Test training on 2D U(1) model.
"""
from __future__ import absolute_import, division, print_function, annotations
from dataclasses import dataclass

import os
import sys
import time
import json
import copy
import argparse
import warnings
from typing import Union

import tensorflow as tf
from tensorflow.python.ops.gen_math_ops import Any

warnings.filterwarnings(action='once', category=UserWarning)
warnings.filterwarnings('once', 'keras')

if tf.__version__.startswith('1'):
    try:
        tf.compat.v1.enable_v2_behavior()
    except AttributeError:
        print('Unable to call \n'
              '`tf.compat.v1.enable_v2_behavior()`. Continuing...')
    try:
        tf.compat.v1.enable_control_flow_v2()
    except AttributeError:
        print('Unable to call \n'
              '`tf.compat.v1.enable_control_flow_v2()`. Continuing...')
    try:
        tf.compat.v1.enable_v2_tensorshape()
    except AttributeError:
        print('Unable to call \n'
              '`tf.compat.v1.enable_v2_tensorshape()`. Continuing...')
    try:
        tf.compat.v1.enable_eager_execution()
    except AttributeError:
        print('Unable to call \n'
              '`tf.compat.v1.enable_eager_execution()`. Continuing...')
    try:
        tf.compat.v1.enable_resource_variables()
    except AttributeError:
        print('Unable to call \n'
              '`tf.compat.v1.enable_resource_variables()`. Continuing...')


#  try:
#      import horovod.tensorflow as hvd
#  except ImportError:
#      pass


MODULEPATH = os.path.join(os.path.dirname(__file__), '..')
if MODULEPATH not in sys.path:
    sys.path.append(MODULEPATH)


#  CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
#  PARENT_DIR = os.path.dirname(CURRENT_DIR)
#  if PARENT_DIR not in sys.path:
#      sys.path.append(PARENT_DIR)
from functools import wraps

import utils.file_io as io

from utils.hvd_init import RANK
from config import BIN_DIR, GAUGE_LOGS_DIR
from utils.attr_dict import AttrDict
from utils.training_utils import train, TrainOutputs
from utils.inference_utils import InferenceResults, run, run_hmc
from utils.logger import Logger

logger = Logger()


# pylint:disable=import-outside-toplevel, invalid-name, broad-except
TIMING_FILE = os.path.join(BIN_DIR, 'test_benchmarks.log')
LOG_FILE = os.path.join(BIN_DIR, 'log_dirs.txt')

#  LOG_FILE = os.path.join(
#      os.path.dirname(PROJECT_DIR), 'bin', 'log_dirs.txt'
#  )
@dataclass
class TestOutputs:
    train: TrainOutputs
    run: Union[InferenceResults, None]




def parse_args():
    """Method for parsing CLI flags."""
    description = (
        "Various test functions to make sure everything runs as expected."
    )

    parser = argparse.ArgumentParser(
        description=description,
    )
    parser.add_argument('--horovod', action='store_true',
                        help=("""Running with Horovod."""))

    parser.add_argument('--test_all', action='store_true',
                        help=("""Run all tests."""))

    parser.add_argument('--test_separate_networks', action='store_true',
                        help="Test `--separate_networks` specifically.")

    parser.add_argument('--test_single_network', action='store_true',
                        help="Test `--single_network` specifically.")

    parser.add_argument('--test_conv_net', action='store_true',
                        help="Test conv. nets specifically.")

    parser.add_argument('--test_hmc_run', action='store_true',
                        help="Test HMC inference specifically.")

    parser.add_argument('--test_inference_from_model', action='store_true',
                        help=("Test running inference from saved "
                              "(trained) model specifically."))

    parser.add_argument('--test_resume_training', action='store_true',
                        help=("Test resuming training from checkpoint. "
                              "Must specify `--log_dir`."""))

    parser.add_argument('--log_dir', default=None, type=str,
                        help=("`log_dir` from which to load saved model "
                              "for running inference on."""))
    args = parser.parse_args()

    return args


def parse_test_configs(test_configs_file=None):
    """Parse `test_config.json`."""
    if test_configs_file is None:
        test_configs_file = os.path.join(BIN_DIR, 'test_configs.json')

    with open(test_configs_file, 'rt') as f:
        test_flags = json.load(f)

    test_flags = AttrDict(dict(test_flags))
    for key, val in test_flags.items():
        if isinstance(val, dict):
            test_flags[key] = AttrDict(val)

    return test_flags


def catch_exception(fn):
    """Decorator function for catching a method with `pudb`."""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:
            print(type(e))
            print(e)

    return wrapper


def test_hmc_run(
        configs: dict[str, Any],
        make_plots: bool = True,
) -> TestOutputs:
    """Testing generic HMC."""
    logger.info(f'Testing generic HMC')
    t0 = time.time()
    configs = AttrDict(**dict(copy.deepcopy(configs)))
    configs['dynamics_config']['hmc'] = True
    #  hmc_dir = os.path.join(os.path.dirname(PROJECT_DIR),
    #                         'gauge_logs_eager', 'test', 'hmc_runs')
    hmc_dir = os.path.join(GAUGE_LOGS_DIR, 'hmc_test_logs')
    run_out = run_hmc(configs, hmc_dir=hmc_dir, make_plots=make_plots)

    logger.info(f'Passed! Took: {time.time() - t0:.4f} seconds')
    return TestOutputs(None, run_out)


def test_conv_net(
        configs: dict[str, Any],
        make_plots: bool = True,
) -> TestOutputs:
    """Test convolutional networks."""
    t0 = time.time()
    logger.info(f'Testing convolutional network')
    configs = AttrDict(**dict(copy.deepcopy(configs)))
    #  flags.use_conv_net = True
    configs['dynamics_config']['use_conv_net'] = True
    configs['conv_config'] = dict(
        sizes=[2, 2],
        filters=[16, 32],
        pool_sizes=[2, 2],
        use_batch_norm=True,
        conv_paddings=['valid', 'valid'],
        conv_activations=['relu', 'relu'],
        input_shape=configs['dynamics_config']['x_shape'][1:],
    )
    train_out = train(configs, make_plots=make_plots,
                      num_chains=8, verbose=False)
    runs_dir = os.path.join(train_out.logdir, 'inference')
    run_out = None
    if RANK == 0:
        run_out = run(train_out.dynamics, configs, x=train_out.x,
                      runs_dir=runs_dir, make_plots=make_plots)
    logger.info(f'Passed! Took: {time.time() - t0:.4f} seconds')

    return TestOutputs(train_out, run_out)


def test_single_network(
        configs: dict[str, Any],
        make_plots: bool = True,
) -> TestOutputs:
    """Test training on single network."""
    t0 = time.time()
    logger.info(f'Testing single network')
    configs_ = dict(copy.deepcopy(configs))
    configs_['dynamics_config']['separate_networks'] = False
    train_out = train(configs_, make_plots=make_plots,
                      verbose=False, num_chains=8)
    logdir = train_out.logdir
    runs_dir = os.path.join(logdir, 'inference')
    run_out = None
    if RANK == 0:
        run_out = run(train_out.dynamics, configs_, x=train_out.x,
                      runs_dir=runs_dir, make_plots=make_plots)

    logger.info(f'Passed! Took: {time.time() - t0:.4f} seconds')
    return TestOutputs(train_out, run_out)


def test_separate_networks(
        configs: dict[str, Any],
        make_plots: bool = True,
) -> TestOutputs:
    """Test training on separate networks."""
    t0 = time.time()
    logger.info(f'Testing separate networks')
    configs_ = dict(copy.deepcopy(configs))
    configs_['hmc_steps'] = 0
    configs_['dynamics_config']['separate_networks'] = True
    configs_['compile'] = False
    train_out = train(configs_, make_plots=make_plots,
                      verbose=False, num_chains=8)
    x = train_out.x
    dynamics = train_out.dynamics
    logdir = train_out.logdir
    runs_dir = os.path.join(logdir, 'inference')
    run_out = None
    if RANK == 0:
        run_out = run(dynamics, configs_, x=x,
                      runs_dir=runs_dir, make_plots=make_plots)

    logger.info(f'Passed! Took: {time.time() - t0:.4f} seconds')
    return TestOutputs(train_out, run_out)



def test_resume_training(
        configs: dict[str, Any],
        make_plots: bool = True,
) -> TestOutputs:
    """Test restoring a training session from a checkpoint."""
    t0 = time.time()
    logger.info(f'Testing resuming training')
    #  restore_dir = configs.get('restore_dir', None)
    #  logdir = configs.get('logdir', configs.get('log_dir', None))
    #  if logdir is None:
    #      dirs = configs.get('dirs', None)
    #      if dirs is not None:
    #          logdir = dirs.get('log_dir', dirs.get('logdir', None))

    #  assert logdir is not None
    #
    #  #  fpath = os.path.join(logdir, 'train_configs.json')
    #  fpath = os.path.join(logdir, 'train_configs.z')
    #  if os.path.isfile(fpath):
    #      train_configs = io.loadz(fpath)
    #  else:
    #      try:
    #          fpath = os.path.join(logdir, 'train_configs.json')
    #          with open(fpath, 'r') as f:
    #              train_configs = json.load(f)
    #      except FileNotFoundError:
    #          try:
    #              train_configs = io.loadz(os.path.join(logdir, 'FLAGS.z'))
    #          except FileNotFoundError as err:
    #              raise(err)

    #  logger.info('Restored train_configs successfully.')
    #  logger.info('Setting `restored_flag` in `train_configs`.')
    #  train_configs['log_dir'] = logdir
    #  train_configs['restored'] = True
    #  train_configs['ensure_new'] = False

    #  logger.info(f'logdir: {train_configs["log_dir"]}')
    #  logger.info(f'restored: {train_configs["restored"]}')

    configs_ = copy.deepcopy(configs)
    assert configs_.get('restore_from', None) is not None

    train_out = train(configs_, make_plots=make_plots,
                      verbose=False, num_chains=8)
    dynamics = train_out.dynamics
    logdir = train_out.logdir
    x = train_out.x
    runs_dir = os.path.join(logdir, 'inference')
    run_out = None
    if RANK == 0:
        run_out = run(dynamics, configs_, x=x, runs_dir=runs_dir)

    logger.info(f'Passed! Took: {time.time() - t0:.4f} seconds')
    return TestOutputs(train_out, run_out)


def test():
    """Run tests."""
    configs = parse_test_configs()

    sep_configs = copy.deepcopy(configs)
    conv_configs = copy.deepcopy(configs)
    single_configs = copy.deepcopy(configs)

    sep_out = test_separate_networks(sep_configs, make_plots=True)

    #  sep_configs_copy = copy.deepcopy(sep_out.train.configs)
    sep_configs['train_steps'] += 10
    sep_configs['restore_from'] = sep_out.train.logdir
    sep_configs['log_dir'] = None
    _ = test_resume_training(sep_configs, make_plots=True)

    bf = sep_configs.get('beta_final')
    beta_final = bf + 1
    sep_configs['beta_final'] = beta_final
    logger.log(f'Increasing beta: {bf} -> {beta_final}')
    sep_configs['ensure_new'] = True
    sep_configs['beta_final'] = sep_configs['beta_final'] + 1

    _ = test_resume_training(sep_configs, make_plots=True)

    single_net_out = test_single_network(single_configs, make_plots=True)
    single_configs['restore_from'] = single_net_out.train.logdir
    #  single_configs_copy['ensure_new'] = False
    #  single_configs_copy = copy.deepcopy(single_net_out.train.configs)
    single_configs['dynamics_config']['separate_networks'] = False
    _ = test_resume_training(single_configs)

    configs['ensure_new'] = True
    configs['log_dir'] = None

    _ = test_separate_networks(configs)

    configs['ensure_new'] = True
    configs['log_dir'] = None

    _ = test_single_network(configs)

    _ = test_conv_net(conv_configs)

    if RANK  == 0:
        _ = test_hmc_run(configs)

    logger.info(f'All tests passed!')


def main(args, flags=None):
    """Main method."""
    fn_map = {
        'test_hmc_run': test_hmc_run,
        'test_separate_networks': test_separate_networks,
        'test_single_network': test_single_network,
        'test_resume_training': test_resume_training,
        'test_conv_net': test_conv_net,
        #  'test_inference_from_model': test_inference_from_model,
    }
    if flags is None:
        flags = parse_test_configs()

    for arg, fn in fn_map.items():
        if args.__dict__.get(arg):
            if arg == 'test_resume_training':
                _ = fn(args.log_dir)
            else:
                _ = fn(flags)


if __name__ == '__main__':
    ARGS = parse_args()
    if ARGS.horovod:
        ARGS.horovod = True

    _ = test() if ARGS.test_all else main(ARGS)
