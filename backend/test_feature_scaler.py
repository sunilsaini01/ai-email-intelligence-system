import numpy as np

from app.feature_engineering.feature_scaler import (
    EngineeredFeatureScaler,
)

# -----------------------
# Dummy engineered features
# -----------------------

train = np.array([
    [100, 10, 2],
    [200, 15, 4],
    [300, 20, 6],
], dtype=np.float32)

test = np.array([
    [150, 12, 3],
], dtype=np.float32)

scaler = EngineeredFeatureScaler()

scaled_train = scaler.fit_transform(train)

print("Scaled Train")
print(scaled_train)

scaled_test = scaler.transform(test)

print("\nScaled Test")
print(scaled_test)

scaler.save("backend/feature_scaler.pkl")

loaded = EngineeredFeatureScaler.load(
    "backend/feature_scaler.pkl"
)

print("\nLoaded scaler successfully.")