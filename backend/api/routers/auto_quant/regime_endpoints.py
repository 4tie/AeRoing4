"""Regime detection endpoints for Auto-Quant."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ....services.auto_quant import pipeline as _pl


def register_regime_endpoints(router: APIRouter) -> None:
    """Register regime detection endpoints on the given router."""
    
    @router.get(
        "/regime/{run_id}",
        summary="Get current regime classification and probabilities",
    )
    async def get_regime_status(run_id: str) -> dict:
        """Get current regime classification and probabilities for a pipeline run.
        
        Returns:
            Dictionary with current regime, probabilities, confidence, and history
        """
        state = _pl.get_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        
        return {
            "run_id": run_id,
            "current_regime": state.current_regime,
            "regime_probabilities": state.regime_probabilities,
            "regime_history": state.regime_history,
            "regime_detection_enabled": state.regime_detection_enabled,
            "regime_model_path": state.regime_model_path,
        }

    @router.post(
        "/regime/train",
        summary="Train HMM model on historical data",
    )
    async def train_regime_model(
        body: dict,
        request: Request,
    ) -> dict:
        """Train HMM model on historical data for regime detection.
        
        Args:
            body: Dictionary with training parameters:
                - data_path: Path to historical OHLCV data (CSV or JSON)
                - n_components: Number of regimes (default 4)
                - covariance_type: Covariance type (default 'full')
                - n_iter: Maximum iterations (default 100)
        
        Returns:
            Dictionary with training status and model path
        """
        services = request.app.state.services
        settings = services.settings_store.load()
        
        # Import here to avoid circular dependency
        from ....services.auto_quant.regime_detection import create_regime_detector
        import pandas as pd
        
        data_path = body.get("data_path")
        if not data_path:
            raise HTTPException(status_code=400, detail="data_path is required")
        
        data_path = Path(data_path)
        if not data_path.exists():
            raise HTTPException(status_code=404, detail=f"Data file not found: {data_path}")
        
        # Load data
        if data_path.suffix == ".csv":
            df = pd.read_csv(data_path)
        elif data_path.suffix == ".json":
            df = pd.read_json(data_path)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use CSV or JSON.")
        
        # Validate data columns
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")
        
        # Create and train detector
        detector = create_regime_detector(
            n_components=body.get("n_components", 4),
            covariance_type=body.get("covariance_type", "full"),
            n_iter=body.get("n_iter", 100),
        )
        
        try:
            detector.train(df)
            
            # Save model
            model_dir = Path(settings.user_data_directory_path) / "regime_models"
            model_dir.mkdir(parents=True, exist_ok=True)
            model_path = model_dir / "regime_model.pkl"
            detector.save_model(model_path)
            
            return {
                "success": True,
                "message": "Regime model trained successfully",
                "model_path": str(model_path),
                "n_components": detector.n_components,
                "regime_mapping": detector.regime_mapping,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")

    @router.post(
        "/regime/predict",
        summary="Predict regime for current market data",
    )
    async def predict_regime(
        body: dict,
        request: Request,
    ) -> dict:
        """Predict regime for current market data.
        
        Args:
            body: Dictionary with:
                - data: OHLCV data (list of dicts or DataFrame-like structure)
                - model_path: Path to trained model (optional, uses default)
        
        Returns:
            Dictionary with predicted regime and probabilities
        """
        services = request.app.state.services
        settings = services.settings_store.load()
        
        # Import here to avoid circular dependency
        from ....services.auto_quant.regime_detection import create_regime_detector
        import pandas as pd
        
        data = body.get("data")
        if not data:
            raise HTTPException(status_code=400, detail="data is required")
        
        # Convert data to DataFrame
        if isinstance(data, list):
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame(data)
        
        # Validate data columns
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")
        
        # Load model
        model_path = body.get("model_path")
        if not model_path:
            model_path = Path(settings.user_data_directory_path) / "regime_models" / "regime_model.pkl"
        else:
            model_path = Path(model_path)
        
        if not model_path.exists():
            raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")
        
        # Create detector and load model
        detector = create_regime_detector()
        detector.load_model(model_path)
        
        try:
            result = detector.predict(df)
            return result.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")
