import numpy as np
from librosa import load
from matplotlib import pyplot as plt
import soundfile as sf

y, sr = load('car_10dB.wav', sr=None)
x, sr = load('clean.wav', sr=None)
n = y - x
z = np.concatenate((n[:2*sr],y),0)

sf.write('car_10dB_2s_silence.wav', z, 16000)

