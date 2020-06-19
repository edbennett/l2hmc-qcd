#/bin/bash

RUNNER='../l2hmc-qcd/run.py'
ARGS="$@"
# ARGS='./inference_args.txt'

export KMP_BLOCKTIME=1
export OMP_NUM_THREADS=16
export KMP_SETTINGS=TRUE
export KMP_AFFINITY='granularity=fine,verbose,compact,1,0'

# export TF_XLA_FLAGS=“--tf_xla_cpu_global_jit”

export TF_XLA_FLAGS="--tf_xla_auto_jit=2 --tf_xla_cpu_global_jit"


ipython3 -m pudb ${RUNNER} @${ARGS}
