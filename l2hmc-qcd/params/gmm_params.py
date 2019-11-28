GMM_PARAMS = {                # Default parameters for `GaussianMixtureModel`
    'x_dim': 2,
    'center': 2.,
    'sigma1': 0.02,
    'sigma2': 0.02,
    'num_distributions': 2,
    'arrangement': 'xaxis',
    'size': 1.,
    'batch_size': 200,
    'beta_init': 1./10.,
    'beta_final': 1.,
    'beta_fixed': False,
    'eps_fixed': False,
    'eps': 0.25,
    'hmc': False,
    'network_arch': 'generic',
    'num_steps': 10,
    'use_bn': False,
    'dropout_prob': 0.,
    'num_hidden1': 10,
    'num_hidden2': 10,
    'save_lf': True,
    'loss_scale': 0.1,
    'aux_weight': 1.,
    'clip_value': 0.,
    'lr_init': 1e-3,
    'warmup_lr': False,
    'lr_decay_steps': 1000,
    'lr_decay_rate': 0.96,
    'train_steps': 5000,
    'zero_translation': False,
    'float64': False,
    'trace': False,
    'profiler': False,
    'horovod': False,
    'comet': False,
    'restore': False,
    'theta': False,
    'num_intra_threads': 0,
    'using_hvd': False,
}