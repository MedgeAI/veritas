#!/usr/bin/env python3
# Reproduce key quantitative values from Detorakis (2017) [Re] MNN model.
# Runs the shipped mnn_model on several Figure-1 behaviours and records
# spike counts / inter-spike-intervals. Deterministic, no external data.
import json
import numpy as np
from copy import copy
from neuron_model import mnn_model

params = {'k1': 0.2, 'k2': 0.02, 'b': 0.01, 'R1': 0.0, 'R2': 1.0,
          'El': -70.0, 'Vr': -70.0, 'Thetar': -60.0, 'a': 0.000,
          'A1': 0.0, 'A2': 0.0, 'G': 0.05, 'C': 1.0, 'ThetaInf': -50.0}

out = {}

def run(Iext, pms, IC=(0.01, 0.001, -70.0, -50.0)):
    sol, theta_, spk = mnn_model(pms, Iext, dt=0.1, IC=IC)
    return spk

# A: Tonic spiking
Iext = 1.5 * np.ones((2000,))
spk = run(Iext, params)
out['tonic_spiking_n_spikes'] = int(spk.shape[0])
out['tonic_spiking_last_spike_step'] = int(spk[-1])
out['tonic_spiking_sim_steps'] = 2000

# D: Phasic spiking (a=0.005)
pms = copy(params); pms['a'] = 0.005
Iext = 1.5 * np.ones((5000,))
spk = run(Iext, pms)
out['phasic_spiking_n_spikes'] = int(spk.shape[0])
out['phasic_spiking_last_spike_step'] = int(spk[-1])
out['phasic_spiking_sim_steps'] = 5000

# C: Spike frequency adaptation (a=0.005, Iext=2)
pms = copy(params); pms['a'] = 0.005
Iext = 2.0 * np.ones((2000,))
spk = run(Iext, pms)
isi = np.diff(spk)
out['sfa_n_spikes'] = int(spk.shape[0])
out['sfa_first_isi_steps'] = int(isi[0]) if isi.shape[0] > 0 else -1
out['sfa_last_isi_steps'] = int(isi[-1]) if isi.shape[0] > 0 else -1

# M: Tonic bursting (a=0.005, A1=10, A2=-.6, Iext=2)
pms = copy(params); pms['a'] = 0.005; pms['A1'] = 10; pms['A2'] = -0.6
Iext = 2.0 * np.ones((5000,))
spk = run(Iext, pms)
out['tonic_bursting_n_spikes'] = int(spk.shape[0])

# N: Phasic bursting (a=0.005, A1=10, A2=-.6, Iext=1.5)
pms = copy(params); pms['a'] = 0.005; pms['A1'] = 10; pms['A2'] = -0.6
Iext = 1.5 * np.ones((5000,))
spk = run(Iext, pms)
out['phasic_bursting_n_spikes'] = int(spk.shape[0])

import sys
np_v = np.__version__
out['_env'] = {'numpy': np_v, 'python': sys.version.split()[0]}
print(json.dumps(out, indent=2, sort_keys=True))
