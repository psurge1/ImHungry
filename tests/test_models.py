import pytest
from pydantic import ValidationError

from imhungry.models import Nutrition, Profile, DateRange, Intake, CheckIn, BehaviorPattern


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "12"])
def test_nutrition_rejects_invalid_numbers(bad):
    with pytest.raises(ValidationError):
        Nutrition(energy_kcal=bad, protein_g=1, carbs_g=1, fat_g=1)


def test_unknown_is_not_zero_and_no_identity_input():
    with pytest.raises(ValidationError):
        Nutrition(energy_kcal=100)
    assert "fiber_g" not in Nutrition(energy_kcal=100, protein_g=1, carbs_g=1, fat_g=1).data()
    with pytest.raises(ValidationError):
        Profile(user_id="someone-else")
    with pytest.raises(ValidationError):
        Profile(timezone="unknown")


def test_ranges_and_checkin_validation():
    assert DateRange(start_date="2026-09-14").end_date.isoformat() == "2026-09-14"
    with pytest.raises(ValidationError):
        DateRange(start_date="2026-01-01", end_date="2027-01-02")
    with pytest.raises(ValidationError):
        CheckIn(recorded_at="2026-09-14T12:00:00Z", subjective={"hunger": 11})
    with pytest.raises(ValidationError):
        CheckIn(recorded_at="2026-09-14T12:00:00Z")
    with pytest.raises(ValidationError):
        BehaviorPattern(category="hunger", description="Evening hunger", user_confirmed=False)
