import backend.config  # noqa: F401 – sets up sys.path
from fastapi import APIRouter
from backend.config import REC_PATH
from backend.serializers import df_to_records
from data_manager import load_recommendations

router = APIRouter()


@router.get("")
def get_recommendations():
    """Return all recommendations as JSON."""
    df = load_recommendations(REC_PATH)
    return df_to_records(df)
