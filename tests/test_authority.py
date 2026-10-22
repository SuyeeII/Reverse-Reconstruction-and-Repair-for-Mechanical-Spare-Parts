import importlib
import pytest

def api():
    assert importlib.util.find_spec('repairforge.authority') is not None, 'versioned executor is required'
    return importlib.import_module('repairforge.authority')

def test_stale_duplicate_and_out_of_bounds_actions_are_rejected(tmp_path):
    a=api(); s=a.Store(tmp_path)
    s.create('test',{'limits':{'mass_g':30},'candidate_budget':4,'parameter_bounds':{'thickness_mm':[2,8]}})
    first=s.propose('test','d1',0,{'thickness_mm':3.})
    assert first['state_version']==1
    for decision,version,params,match in [('d1',1,{'thickness_mm':4},'DUPLICATE'),('d2',0,{'thickness_mm':4},'STALE'),('d3',1,{'thickness_mm':10},'BOUNDS')]:
        with pytest.raises(a.Rejected,match=match): s.propose('test',decision,version,params)
    assert s.state('test')['state_version']==1
    assert len(s.candidates('test'))==1

def test_contract_tampering_is_rejected(tmp_path):
    a=api(); s=a.Store(tmp_path); s.create('test',{'candidate_budget':4,'parameter_bounds':{}})
    (tmp_path/'test'/'contract.json').write_text('{}')
    with pytest.raises(a.Rejected,match='CONTRACT'): s.propose('test','d1',0,{})
