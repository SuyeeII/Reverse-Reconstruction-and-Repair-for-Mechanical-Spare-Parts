"""Import user photos and requirements without overwriting any existing case."""
from pathlib import Path
import argparse,json,shutil,re
import cv2
from repairforge.authority import read,write,digest
ROOT=Path(__file__).resolve().parents[1]
def import_case(case_id,images,scale,requirements):
    if not re.fullmatch('[A-Za-z0-9_-]{1,70}',case_id) or case_id.startswith(('dev_','test_')):raise ValueError('Use a new real_* identifier')
    target=ROOT/'inputs'/case_id
    if target.exists():raise ValueError('INPUT_ALREADY_EXISTS_NO_OVERWRITE')
    photos=sorted(Path(images).glob('*.png'))+sorted(Path(images).glob('*.jpg'))+sorted(Path(images).glob('*.jpeg'))
    if not 12<=len(photos)<=24:raise ValueError('NEED_12_TO_24_IMAGES')
    if any(f.is_symlink() or 'oracle' in f.resolve().parts for f in photos):raise ValueError('SYMLINK_OR_TRUTH_SOURCE_REJECTED')
    specification=read(requirements);allowed={'scope','force_n','young_mpa','poisson','density_g_cm3','displacement_mm','mass_g','min_wall_mm','purpose'}
    if set(specification)-allowed:raise ValueError('UNSUPPORTED_REQUIREMENT_FIELD')
    fixed={'force_n':30.,'young_mpa':2200.,'poisson':.35,'density_g_cm3':1.24,'displacement_mm':.4,'mass_g':30.,'min_wall_mm':3.}
    if any(specification.get(k)!=v for k,v in fixed.items()):raise ValueError('REQUIREMENTS_CONFLICT_WITH_FROZEN_CONTRACT_REGISTER_NEW_PROTOCOL')
    if specification.get('scope')!='non_safety_critical_equal_thickness_l':raise ValueError('UNSUPPORTED_OR_SAFETY_CRITICAL_FAMILY')
    reference=read(scale);allowed_scale={'marker_dictionary','marker_id','marker_side_mm','measurement_uncertainty_mm','source','markers'}
    if set(reference)-allowed_scale or 'markers' not in reference:raise ValueError('INDEPENDENT_REFERENCE_BOARD_REQUIRED_NO_TRUTH_CAMERA_OR_DIMENSIONS')
    for f in photos:
        im=cv2.imread(str(f))
        if im is None or min(im.shape[:2])<640:raise ValueError('INVALID_OR_TOO_SMALL_RGB_IMAGE')
    target.mkdir();(target/'images').mkdir()
    for i,f in enumerate(photos):shutil.copyfile(f,target/'images'/f'view_{i:02d}{f.suffix.lower().replace(".jpeg",".jpg")}')
    write(target/'scale.json',reference);write(target/'requirements.json',specification)
    write(target/'source.json',{'kind':'user_supplied_photographs_unvalidated','views':len(photos),'source':'user upload; physical part and material have not been independently tested','scale_input':'user separately measured reference board','disclosed_prior':'equal-thickness L family; backs/missing surfaces restored as prior','scope':'textured saturated purple surfaces, fixed-focus pinhole-compatible photos, clear circular holes; other objects/colors unsupported'})
    write(target/'import_receipt.json',{'case_id':case_id,'input_hashes':{str(p.relative_to(target)):digest(p) for p in target.rglob('*') if p.is_file()},'contract':'rf-contract-1','no_geometry_truth_supplied':True});return target
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case-id',required=True);p.add_argument('--images',required=True);p.add_argument('--scale',required=True);p.add_argument('--requirements',required=True);a=p.parse_args();print(import_case(a.case_id,a.images,a.scale,a.requirements))
