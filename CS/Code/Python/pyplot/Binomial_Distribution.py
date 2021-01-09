import numpy as np
import scipy.stats as sps

n = 10
p = 0.3
k = np.arange(n + 1)
PX = sps.binom.pmf(k, n, p)
print(sum(PX[2:]))