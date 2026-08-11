import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler


class EngineeredFeatureScaler:
    """
    Scale engineered features independently of TF-IDF.

    Fit only on training data.
    """
    
    def __init__(self):
        """
        Initialize the StandardScaler.
        """

        self._scaler = StandardScaler()
        self._fitted = False
        
    def fit_transform(
        self,
        feature_matrix: np.ndarray,
    ) -> np.ndarray:
        """
        Fit the scaler on training data and transform it.
        """

        result = self._scaler.fit_transform(feature_matrix)

        self._fitted = True

        return result
    def transform(
        self,
        feature_matrix: np.ndarray,
    ) -> np.ndarray:
        """
        Transform validation/test data using the fitted scaler.
        """

        if not self._fitted:
            raise RuntimeError(
                "Scaler must be fitted before transform."
            )

        return self._scaler.transform(feature_matrix)
    
    def save(
        self,
        path: str,
    ) -> None:
        """
        Save the fitted scaler.
        """

        joblib.dump(
            self,
            path,
        )
        
    @classmethod
    def load(
        cls,
        path: str,
        ) -> "EngineeredFeatureScaler":
        """
        Load a previously saved scaler.
        """

        return joblib.load(path)