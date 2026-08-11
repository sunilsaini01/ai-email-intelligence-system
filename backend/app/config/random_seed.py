import random

import numpy as np

SEED = 42

random.seed(SEED)
np.random.seed(SEED)

print(f"Global random seed set to {SEED}")