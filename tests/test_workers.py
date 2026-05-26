from unittest.mock import patch, MagicMock, PropertyMock
from autovc.workers.tasks import _execute_verification

def test_task_signature():
    import inspect
    sig = inspect.signature(_execute_verification)
    assert "job_id" in sig.parameters

def test_execute_builds_result():
    mock_session = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 1
    mock_pot = MagicMock()
    mock_pot.kim_model_id = "test_model"
    mock_pot.species = ["U"]
    type(mock_job).potential = PropertyMock(return_value=mock_pot)
    mock_job.properties_requested = ["lattice_constant"]
    mock_session.query.return_value.filter.return_value.first.return_value = mock_job
    with patch("autovc.workers.tasks.PropertyCalculator") as mock_pc, \
         patch("autovc.workers.tasks.get_reference_value") as mock_ref:
        mock_pc.return_value.compute_lattice_constant.return_value = {"value": 3.42, "unit": "angstrom", "property": "lattice_constant"}
        mock_ref.return_value = {"value": 3.47, "unit": "angstrom"}
        _execute_verification(1, mock_session)
        mock_session.add.assert_called()
