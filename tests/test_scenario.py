import pandas as pd

from icpms_intel.scenario import ScenarioInputs, run_scenario


def test_accelerated_scenario_exceeds_constrained():
    signals = pd.DataFrame({"sector": ["Battery & Critical Minerals"] * 5})
    low, _ = run_scenario(signals, ScenarioInputs(macro_factor=.8, regulation_factor=.8, technology_factor=.8))
    high, _ = run_scenario(signals, ScenarioInputs(macro_factor=1.2, regulation_factor=1.2, technology_factor=1.2))
    assert high["Expected index"].mean() > low["Expected index"].mean()


def test_scenario_is_deterministic():
    signals = pd.DataFrame({"sector": ["Environmental & Water"]})
    a, b = run_scenario(signals, ScenarioInputs(seed=99))
    c, d = run_scenario(signals, ScenarioInputs(seed=99))
    assert a.equals(c)
    assert b.equals(d)

