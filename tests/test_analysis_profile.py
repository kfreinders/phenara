import pytest

from scripts.analysis.config import AnalysisConfig
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.roi import AnalysisCrop, RoiCircle, RoiDefinition


def make_profile() -> AnalysisProfile:
    config = AnalysisConfig(roi_rows=1, roi_cols=1)
    return AnalysisProfile(
        schema_version=1,
        config=config,
        roi=RoiDefinition(
            schema_version=2,
            rows=1,
            columns=1,
            source_width=200,
            source_height=100,
            config_fingerprint=config.fingerprint,
            circles=(RoiCircle(0, 0, 0.5, 0.5, 0.2),),
            analysis_crop=AnalysisCrop(0.1, 0.1, 0.8, 0.8),
        ),
    )


def test_analysis_profile_round_trips_and_persists(tmp_path):
    profile = make_profile()
    path = tmp_path / "analysis-profile.json"

    profile.save(path)

    assert AnalysisProfile.load(path) == profile


def test_analysis_profile_rejects_roi_from_other_settings():
    profile = make_profile()
    mismatched = AnalysisConfig(threshold=profile.config.threshold + 1)

    with pytest.raises(ValueError, match="different analysis settings"):
        AnalysisProfile(1, mismatched, profile.roi)
