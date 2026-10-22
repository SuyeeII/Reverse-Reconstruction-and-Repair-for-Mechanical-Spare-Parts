import importlib,json
from pathlib import Path

def test_real_solver_rejects_thin_candidate_and_accepts_refinement(tmp_path):
    assert importlib.util.find_spec('repairforge.evaluate') is not None, 'independent solver gate required'
    from repairforge.evaluate import evaluate_design
    from repairforge.authority import read
    contract=read(Path(__file__).resolve().parents[1]/'configs/acceptance.json')
    p={'length_mm':50.,'width_mm':40.,'height_mm':40.,'thickness_mm':3.,'hole_pitch_mm':24.,'hole_radius_mm':3.,'base_hole_x_mm':32.,'wall_hole_z_mm':25.}
    thin=evaluate_design(p,tmp_path/'thin',contract)
    assert not thin['accepted_physics']
    assert thin['violations']
    p={**p,'thickness_mm':7.,'fillet_mm':4.}
    thick=evaluate_design(p,tmp_path/'thick',contract)
    assert thick['accepted_physics'],thick
    assert len(thick['mesh_reports'])==2
    assert thick['mesh_reports'][-1]['reaction_relative_error']<1e-5

def test_real_slicer_exports_nonempty_extrusion_paths(tmp_path):
    assert importlib.util.find_spec('repairforge.manufacture') is not None, 'real slicer required'
    from repairforge.physics import make_cad
    from repairforge.manufacture import slice_part
    p={'length_mm':50.,'width_mm':40.,'height_mm':40.,'thickness_mm':5.,'hole_pitch_mm':24.,'hole_radius_mm':3.,'base_hole_x_mm':32.,'wall_hole_z_mm':25.}
    make_cad(p,tmp_path)
    r=slice_part(tmp_path/'part.stl',tmp_path/'print')
    assert r['exit_code']==0
    assert r['layers']>100
    assert r['extrusion_segments']>1000
    assert r['gcode_bytes']>10000
