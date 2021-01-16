"""
annealing_schedules.py

Implements various annealing schedules for training the L2HMC sampler.

Author: Sam Foreman
Date: 08/30/2020
"""
import numpy as np
import tensorflow as tf
from typing import Callable

TF_FLOAT = getattr(tf, tf.keras.backend.floatx(), tf.float32)


# pylint:disable=invalid-name
def exp_mult_cooling(
        step: int,          # Current step in annealing schedule
        t0: float,          # Initial temperature
        t1: float,          # Final temperature
        num_steps: int,     # Number of steps in annealing schedule
        alpha=None,         # Custom multiplicative scaling factor
) -> float:
    """Annealing function."""
    if alpha is None:
        alpha = tf.exp(
            (tf.math.log(t1) - tf.math.log(t0)) / num_steps
        )

    return tf.cast(t0 * (alpha ** step), TF_FLOAT)


def linear_multiplicative_cooling(
        step: int,          # Current step in annealing schedule
        t0: float,          # Initial temperature
        t1: float,          # Final temperature
        num_steps: int,     # Number of steps in annealing schedule
        alpha=None,         # Custom multiplicative scaling factor
):
    """Linear additive simulated annealing cooling schedule."""
    if alpha is None:
        alpha = (t1 - t0) / (num_steps * t1)

    return t0 / (1 + alpha * step)


def linear_additive_cooling(
        step: int,          # Current step in annealing schedule
        t0: float,          # Initial temperature
        t1: float,          # Final temperature
        num_steps: int,     # Number of steps in annealing schedule
):
    """Linear additive cooling simulated annealing schedule."""
    return t1 + (t0 - t1) * (num_steps - step) / num_steps


def quadratic_additive_cooling(
        step: int,          # Current step in annealing schedule
        t0: float,          # Initial temperature
        t1: float,          # Final temperature
        num_steps: int,     # Number of steps in annealing schedule
):
    """Quadratic additive cooling simulated annealing schedule."""
    return t1 + (t0 - t1) * ((num_steps - step) / num_steps) ** 2


def get_betas(
        steps: int,
        beta_init: float,
        beta_final: float,
        cooling_fn: Callable = exp_mult_cooling,
        discrete: bool = False
):
    """Get array of betas to use in annealing schedule."""
    if discrete:
        betas = []
        for beta in range(beta_init, beta_final):
            betas += (steps / np.abs(beta_final - beta_init)) * [beta]

        return 1. / np.array(betas)

    t_init = 1. / beta_init
    t_final = 1. / beta_final
    t_arr = np.array([
        cooling_fn(i, t_init, t_final, steps) for i in range(steps)
    ])

    return 1. / t_arr