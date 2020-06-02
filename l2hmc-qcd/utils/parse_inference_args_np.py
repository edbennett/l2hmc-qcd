import sys
import argparse
import shlex


def parse_args():
    """Parse command line arguments."""
    description = 'Run tf-independent inference on trained model.'
    parser = argparse.ArgumentParser(
        description=description,
        fromfile_prefix_chars='@',
    )

    parser.add_argument('--log_dir',
                        dest='log_dir',
                        required=False,
                        default=None,
                        help=("""log_dir containing `weights.pkl` file of
                              trained models' network weights."""))

    parser.add_argument('--hmc',
                        dest='hmc',
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed sets all `net_weights`
                              to 0."""))

    parser.add_argument('--hmc_start',
                        dest='hmc_start',
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed will run HMC to get
                              thermalized configuration as initial state for
                              running inference on trained model."""))

    parser.add_argument('--num_steps',
                        dest='num_steps',
                        required=False,
                        default=None,
                        help=("""Number of leapfrog steps
                              (i.e. trajectory length)."""))

    parser.add_argument("--batch_size",
                        dest="batch_size",
                        type=int,
                        default=None,
                        required=False,
                        help=("""Number of samples (batch size) to use for
                              training.\n (Default: 20)"""))

    parser.add_argument('--eps',
                        dest='eps',
                        type=float,
                        default=None,
                        required=False,
                        help=("""Step size to use during inference. If no value
                              is passed, `eps = None` and the optimal step size
                              (determined during training) will be used."""))

    parser.add_argument('--init',
                        dest='init',
                        type=str,
                        default=None,
                        required=False,
                        help=("""String specifying how to initialize samples
                              when running inference. Possible values are:
                              'zeros', 'ones', or 'random'.
                              (Default: 'random')"""))

    parser.add_argument("--run_steps",
                        dest="run_steps",
                        type=int,
                        default=10000,
                        required=False,
                        help=("""Number of evaluation 'run' steps to perform
                              after training (i.e. length of desired chain
                              generate using trained L2HMC sample).
                              (Default: 5000)"""))

    parser.add_argument("--mix_samplers",
                        dest="mix_samplers",
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed will intermittently
                              mix between L2HMC and HMC."""))

    parser.add_argument('--direction',
                        dest='direction',
                        type=str,
                        default='rand',
                        required=False,
                        help=("""Specify direction to run dynamics. Must be one
                              of `'random', 'forward', 'backward'`. (DEFAULT:
                              'rand')"""))

    parser.add_argument('--zero_masks',
                        dest='zero_masks',
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed will use `zero_masks`
                              (i.e. m = [1, 1, ..., 1] mb = [0, 0, ..., 0]) for
                              `x` sub-updates in L2HMC update."""))

    parser.add_argument('--symplectic_check',
                        dest='symplectic_check',
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed will run additional
                              volume scaling analysis to test if the sampler is
                              symplectic."""))

    parser.add_argument('--dont_save',
                        dest='dont_save',
                        action='store_true',
                        required=False,
                        help=("""Flag that when passed will prevent inference
                              data from being saved after completing run."""))

    parser.add_argument("--print_steps",
                        dest="print_steps",
                        type=int,
                        default=1,
                        required=False,
                        help=("""Number of steps after which to print new data
                              when running inference using numpy."""))

    parser.add_argument("--beta",
                        dest="beta",
                        type=float,
                        default=5.,
                        required=False,
                        help=("""Flag specifying a singular value of beta at
                              which to run inference using the trained
                              L2HMC sampler. (Default: None"""))

    parser.add_argument('-xsw',
                        '--x_scale_weight',
                        dest='x_scale_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the `scale_weight`
                              parameter, a multiplicative weight that scales
                              the contribution of the `scale` (S) function when
                              performing the augmented L2HMC molecular dynamics
                              update."""))

    parser.add_argument('-xtw',
                        '--x_translation_weight',
                        dest='x_translation_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the `translation_weight`
                              parameter, a multiplicative weight that scales
                              the contribution of the `translation` (T)
                              function when performing the augmented L2HMC
                              molecular dynamics update."""))

    parser.add_argument('-xqw',
                        '--x_transformation_weight',
                        dest='x_transformation_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the
                              `transformation_weight` parameter, a
                              multiplicative weight that scales the
                              contribution of the `transformation` (Q) function
                              when performing the augmented L2HMC molecular
                              dynamics update."""))

    parser.add_argument('-vsw', '--v_scale_weight',
                        dest='v_scale_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the `scale_weight`
                              parameter, a multiplicative weight that scales
                              the contribution of the `scale` (S) function when
                              performing the augmented L2HMC molecular dynamics
                              update."""))

    parser.add_argument('-vtw', '--v_translation_weight',
                        dest='v_translation_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the `translation_weight`
                              parameter, a multiplicative weight that scales
                              the contribution of the `translation` (T)
                              function when performing the augmented L2HMC
                              molecular dynamics update."""))

    parser.add_argument('-vqw', '--v_transformation_weight',
                        dest='v_transformation_weight',
                        type=float,
                        default=1.,
                        required=False,
                        help=("""Specify the value of the
                              `transformation_weight` parameter, a
                              multiplicative weight that scales the
                              contribution of the `transformation` (Q) function
                              when performing the augmented L2HMC molecular
                              dynamics update."""))

    parser.add_argument('--nsv', '--num_singular_values',
                        dest='num_singular_values',
                        type=int,
                        default=-1,
                        required=False,
                        help=("""Specify the number of singular values to keep
                              when reconstructing the weight matrix. (Default:
                              -1, keep all singular values). """))

    parser.add_argument('--switch_steps',
                        dest='switch_steps',
                        type=int,
                        default=10000,
                        required=False,
                        help=("""Flag that when passed (together with
                              `--mix_samplers`) determines how often to switch
                              between L2HMC and HMC during inference."""))

    parser.add_argument('--hmc_steps',
                        dest='hmc_steps',
                        type=int,
                        default=10000,
                        required=False,
                        help=("""Flag that when passed (together with
                              `--mix_samplers`) determines the number of HMC
                              leapfrog steps to run."""))


    if sys.argv[1].startswith('@'):
        args = parser.parse_args(shlex.split(open(sys.argv[1][1:]).read(),
                                             comments=True))
    else:
        args = parser.parse_args()

    return args